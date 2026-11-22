"""Value detection: compare model probabilities with de-vigged market probabilities.

EV per unit stake = p_model × decimal_odds − 1.
A selection only qualifies on the *conservative* EV, where the model probability is shrunk
toward the market (p_c = w·p_model + (1−w)·p_market), and after every risk filter passes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import settings
from .models.markets import ah_ev, ah_outcomes, devig, overround

REFERENCE_BOOKS = ["BFE", "PS", "Pinnacle", "Betfair", "Avg"]  # sharpest first
BET_BOOKS = ["B365", "PS", "Pinnacle", "BW", "Unibet", "William Hill", "Bet365"]
NON_BOOKABLE = {"Max", "Avg", "BFE"}


@dataclass
class Assessment:
    market: str
    selection: str
    line: float | None
    price: float | None
    bookmaker: str
    odds_observation_id: int | None
    implied_prob: float | None
    market_prob: float | None
    model_prob: float
    conservative_prob: float | None
    overround: float | None
    ev: float | None
    ev_conservative: float | None
    reject_reasons: list = field(default_factory=list)

    @property
    def qualifies(self) -> bool:
        return not self.reject_reasons


def pick(snaps: dict, prefs: list[str], need: tuple[str, ...], bookable: bool = False):
    for b in prefs:
        o = snaps.get(b)
        if o is not None and all(getattr(o, k) for k in need):
            return o
    if bookable:
        for b, o in snaps.items():
            if b not in NON_BOOKABLE and all(getattr(o, k) for k in need):
                return o
    return None


def assess(pred: dict, snaps: dict, quality: float, confidence: float, n_min: int,
           team_news_ok: bool, odds_age_h: float | None) -> list[Assessment]:
    """snaps: bookmaker -> latest pre-match OddsObservation (all from before now)."""
    rules = settings.value
    w = rules.market_shrink
    mk = pred["markets"]
    out: list[Assessment] = []

    def common_rejects(a: Assessment):
        r = a.reject_reasons
        if a.price is None:
            r.append("no bookable price from a named bookmaker")
            return
        if quality < rules.min_data_quality:
            r.append(f"data quality {quality:.0f} < {rules.min_data_quality:.0f}")
        if confidence < rules.min_confidence:
            r.append(f"model confidence {confidence:.0f} < {rules.min_confidence:.0f}")
        if n_min < rules.min_team_matches:
            r.append(f"insufficient team history ({n_min} < {rules.min_team_matches} matches)")
        if rules.require_team_news and not team_news_ok:
            r.append("team news unavailable/unresolved")
        if not (rules.min_odds <= a.price <= rules.max_odds):
            r.append(f"odds {a.price:.2f} outside [{rules.min_odds}, {rules.max_odds}]")
        if a.overround is not None and a.overround > rules.max_overround:
            r.append(f"bookmaker margin {a.overround:.1%} too high")
        if odds_age_h is None or odds_age_h > rules.max_odds_age_hours:
            r.append("odds snapshot too old")
        if a.market_prob is not None and a.overround is not None and a.implied_prob is not None:
            bet_fair = a.implied_prob / (1 + a.overround)
            if abs(bet_fair - a.market_prob) > 0.08:
                r.append("bookmaker prices inconsistent with market reference (possible data error)")
        if a.market_prob is None:
            r.append("no reliable market reference price")
        elif abs(a.model_prob - a.market_prob) > rules.max_model_market_gap:
            r.append(f"model/market gap {abs(a.model_prob - a.market_prob):.0%} too large (likely missing information)")
        if a.ev_conservative is None or a.ev_conservative < rules.min_ev_conservative:
            r.append(f"conservative EV {0 if a.ev_conservative is None else a.ev_conservative:+.1%} below {rules.min_ev_conservative:+.0%}")

    # ---------------------------------------------------------------- 1X2
    ref = pick(snaps, REFERENCE_BOOKS, ("home", "draw", "away"))
    bet = pick(snaps, BET_BOOKS, ("home", "draw", "away"), bookable=True)
    mprobs = devig([ref.home, ref.draw, ref.away]) if ref else None
    for k, sel in enumerate(("home", "draw", "away")):
        p = mk["1X2"][sel]
        price = getattr(bet, sel) if bet else None
        q = mprobs[k] if mprobs else None
        pc = w * p + (1 - w) * q if q is not None else None
        a = Assessment("1X2", sel, None, price, bet.bookmaker if bet else "", bet.id if bet else None,
                       1 / price if price else None, q, p, pc,
                       overround([bet.home, bet.draw, bet.away]) if bet else None,
                       p * price - 1 if price else None, pc * price - 1 if (price and pc is not None) else None)
        common_rejects(a)
        out.append(a)

    # ---------------------------------------------------------------- Over/Under 2.5
    ref = pick(snaps, REFERENCE_BOOKS, ("over25", "under25"))
    bet = pick(snaps, BET_BOOKS, ("over25", "under25"), bookable=True)
    mprobs = devig([ref.over25, ref.under25]) if ref else None
    for k, sel in enumerate(("over", "under")):
        p = mk["OU25"][sel]
        price = getattr(bet, f"{sel}25") if bet else None
        q = mprobs[k] if mprobs else None
        pc = w * p + (1 - w) * q if q is not None else None
        a = Assessment("OU25", sel, 2.5, price, bet.bookmaker if bet else "", bet.id if bet else None,
                       1 / price if price else None, q, p, pc,
                       overround([bet.over25, bet.under25]) if bet else None,
                       p * price - 1 if price else None, pc * price - 1 if (price and pc is not None) else None)
        common_rejects(a)
        out.append(a)

    # ---------------------------------------------------------------- Asian handicap (bookmaker's main line)
    bet = pick(snaps, BET_BOOKS, ("ah_home", "ah_away", "ah_line"), bookable=True)
    if bet is None:  # B365 main-line AH can have ah_line == 0.0 which is falsy
        for b in BET_BOOKS:
            o = snaps.get(b)
            if o is not None and o.ah_home and o.ah_away and o.ah_line is not None:
                bet = o
                break
    if bet is not None and bet.ah_line is not None:
        line = bet.ah_line
        ref = None
        for b in REFERENCE_BOOKS:
            o = snaps.get(b)
            if o is not None and o.ah_home and o.ah_away and o.ah_line == line:
                ref = o
                break
        matrix = pred["matrix"]
        mprobs = devig([ref.ah_home, ref.ah_away]) if ref else None
        for k, sel in enumerate(("home", "away")):
            price = bet.ah_home if sel == "home" else bet.ah_away
            ev = ah_ev(matrix, line, price, sel)
            mm, ll = (matrix, line) if sel == "home" else (matrix.T, -line)
            wn, hw, push, hl = ah_outcomes(mm, ll)
            p_equiv = wn + 0.5 * hw + 0.5 * push
            q = mprobs[k] if mprobs else None
            ev_c = w * ev + (1 - w) * (q * price - 1) if q is not None else None
            a = Assessment("AH", sel, line, price, bet.bookmaker, bet.id, 1 / price, q, p_equiv,
                           (w * p_equiv + (1 - w) * q) if q is not None else None,
                           overround([bet.ah_home, bet.ah_away]), ev, ev_c)
            common_rejects(a)
            out.append(a)
    return out


def select_bets(assessments: list[Assessment], already: list[tuple[str, str]], slots: int) -> list[Assessment]:
    """Pick at most `slots` bets: best conservative EV first, one per market, and never both a
    1X2 and an AH selection on the same match (highly correlated)."""
    chosen: list[Assessment] = []
    used_markets = {m for m, _ in already}
    for a in sorted((a for a in assessments if a.qualifies), key=lambda a: -(a.ev_conservative or 0)):
        if len(chosen) >= slots:
            break
        if a.market in used_markets:
            a.reject_reasons.append("another selection in this market already chosen")
            continue
        if a.market in ("1X2", "AH") and ({"1X2", "AH"} & used_markets):
            a.reject_reasons.append("correlated with an existing result-market bet on this match")
            continue
        chosen.append(a)
        used_markets.add(a.market)
    return chosen


def book_dispersion(snaps: dict) -> float | None:
    probs = []
    for b, o in snaps.items():
        if b in ("Max",) or not (o.home and o.draw and o.away):
            continue
        probs.append(devig([o.home, o.draw, o.away], "proportional")[0])
    return float(np.std(probs)) if len(probs) >= 2 else None
