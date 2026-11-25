"""Engine B virtual betting — an independent €100 bankroll with a medium-risk profile.

Shares NOTHING with Engine A's ledger (separate tables, separate rules). Simulation only.
Selections are allowed only on markets with a real bookmaker price (1X2, Over/Under 2.5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select

from ..db import EBBankrollTransaction, EBBet, EBSettlement, Fixture, OddsObservation, log, session_scope
from ..models.markets import devig, settle
from ..timeutil import utcnow


@dataclass
class RiskB:
    initial_bankroll: float = 500.0   # owner decision 2026-11-25 (was 100); difference booked as "top_up"
    stake: float = 10.0               # was 1.0
    max_bets_per_match: int = 2
    max_daily_exposure: float = 100.0  # scaled with the stake (was 10 at €1 stakes)
    min_quality: float = 60.0
    min_confidence: float = 50.0
    market_shrink: float = 0.25          # p = w*model + (1-w)*market  (Engine A uses 0.10)
    min_edge: float = 0.03               # conservative EV
    min_prob: float = 0.20
    min_odds: float = 1.40
    max_odds: float = 6.00
    max_model_market_gap: float = 0.20
    # 1X2 selections DISABLED by evidence: walk-forward validation (2026-11-23, 4,845 matches) gave 470 1X2
    # bets at ROI -23.5% with 95% CI [-36.7%, -9.8%] — a significant loss. O/U 2.5 stays (inconclusive).
    markets: tuple = ("OU25",)
    bet_books: tuple = ("B365", "PS", "BW")
    ref_books: tuple = ("BFE", "PS", "Avg")


RISK = RiskB()


def balance(s) -> float:
    t = s.scalars(select(EBBankrollTransaction).order_by(EBBankrollTransaction.id.desc()).limit(1)).first()
    return t.balance_after if t else 0.0


def ensure_bankroll(s) -> None:
    if not s.scalar(select(func.count(EBBankrollTransaction.id))):
        s.add(EBBankrollTransaction(tx_type="initial", amount=RISK.initial_bankroll, balance_after=RISK.initial_bankroll,
                                    note="Engine B initial virtual bankroll (simulation)"))
        s.flush()
        return
    cap = s.scalar(select(func.coalesce(func.sum(EBBankrollTransaction.amount), 0)).where(
        EBBankrollTransaction.tx_type.in_(("initial", "top_up")))) or 0
    missing = round(RISK.initial_bankroll - cap, 2)
    if missing > 0:
        _tx(s, "top_up", missing, None, f"Engine B virtual bankroll raised to €{RISK.initial_bankroll:.2f} by the owner (simulation)")


def _tx(s, kind, amount, bet_id, note):
    s.add(EBBankrollTransaction(tx_type=kind, amount=round(amount, 2), balance_after=round(balance(s) + amount, 2),
                                bet_id=bet_id, note=note))
    s.flush()


def candidates(markets: dict, snaps: dict, quality: float, confidence: float, risk: RiskB = RISK) -> list[dict]:
    """Evaluate every bettable selection; returns dicts with qualifies + reasons (also used by validation)."""
    out = []
    specs = [("1X2", ("home", "draw", "away"), ("home", "draw", "away")), ("OU25", ("over", "under"), ("over25", "under25"))]
    for market, sels, cols in specs:
        if market not in risk.markets:
            continue
        ref = next((snaps[b] for b in risk.ref_books if b in snaps and all(getattr(snaps[b], c) for c in cols)), None)
        bet = next((snaps[b] for b in risk.bet_books if b in snaps and all(getattr(snaps[b], c) for c in cols)), None)
        fair = devig([getattr(ref, c) for c in cols]) if ref else None
        mk = markets["1X2"] if market == "1X2" else markets["OU25"]
        for k, (sel, col) in enumerate(zip(sels, cols)):
            p = mk[sel]
            price = getattr(bet, col) if bet else None
            q = fair[k] if fair else None
            reasons = []
            if price is None:
                reasons.append("no bookable price")
            if q is None:
                reasons.append("no market reference")
            pc = risk.market_shrink * p + (1 - risk.market_shrink) * q if q is not None else None
            ev = pc * price - 1 if (pc is not None and price) else None
            if ref is not None:
                ovr = sum(1 / getattr(ref, c) for c in cols) - 1
                if ovr < -0.02 or ovr > 0.15:
                    reasons.append(f"reference margin {ovr:.0%} implausible (data error)")
            if bet is not None and q is not None:
                bet_fair = devig([getattr(bet, c) for c in cols])[k]
                if abs(bet_fair - q) > 0.06:
                    reasons.append("bookmaker and reference prices disagree (possible data error)")
            if price and not (risk.min_odds <= price <= risk.max_odds):
                reasons.append(f"odds {price:.2f} outside [{risk.min_odds}, {risk.max_odds}]")
            if quality < risk.min_quality:
                reasons.append(f"data quality {quality:.0f} < {risk.min_quality:.0f}")
            if confidence < risk.min_confidence:
                reasons.append(f"confidence {confidence:.0f} < {risk.min_confidence:.0f}")
            if p < risk.min_prob:
                reasons.append(f"probability {p:.0%} < {risk.min_prob:.0%}")
            if q is not None and abs(p - q) > risk.max_model_market_gap:
                reasons.append(f"model/market gap {abs(p - q):.0%} too large")
            if ev is None or ev < risk.min_edge:
                reasons.append(f"edge {0 if ev is None else ev:+.1%} below {risk.min_edge:+.0%}")
            out.append({"market": market, "selection": sel, "line": 2.5 if market == "OU25" else None, "price": price,
                        "bookmaker": bet.bookmaker if bet else None, "odds_observation_id": bet.id if bet else None,
                        "model_prob": p, "market_prob": q, "conservative_prob": pc, "ev": ev,
                        "qualifies": not reasons, "reasons": reasons})
    return out


def choose(cands: list[dict], already: int, risk: RiskB = RISK) -> list[dict]:
    """Best edge first; at most one selection per market; respects the per-match limit."""
    chosen, used = [], set()
    for c in sorted((c for c in cands if c["qualifies"]), key=lambda c: -c["ev"]):
        if already + len(chosen) >= risk.max_bets_per_match or c["market"] in used:
            continue
        chosen.append(c)
        used.add(c["market"])
    return chosen


def place(s, *, prediction, fixture, cand: dict, quality: float) -> EBBet | None:
    now = utcnow()
    if now >= fixture.kickoff_utc - timedelta(minutes=5):
        return None
    if s.scalar(select(func.count(EBBet.id)).where(EBBet.fixture_id == fixture.id)) >= RISK.max_bets_per_match:
        return None
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    exposure = s.scalar(select(func.coalesce(func.sum(EBBet.stake), 0)).where(EBBet.created_at >= day)) or 0
    if exposure + RISK.stake > RISK.max_daily_exposure or balance(s) < RISK.stake:
        return None
    b = EBBet(prediction_id=prediction.id, fixture_id=fixture.id, model_version_id=prediction.model_version_id,
              mode="prematch", market=cand["market"], selection=cand["selection"], line=cand["line"], price=cand["price"],
              bookmaker=cand["bookmaker"], odds_observation_id=cand["odds_observation_id"], stake=RISK.stake,
              model_prob=cand["model_prob"], market_prob=cand["market_prob"], ev=cand["ev"],
              reason=f"edge {cand['ev']:+.1%}: model {cand['model_prob']:.1%} vs market {cand['market_prob']:.1%} "
                     f"@ {cand['price']:.2f} ({cand['bookmaker']})", data_quality=quality,
              created_at=now, kickoff_utc=fixture.kickoff_utc)
    s.add(b)
    s.flush()
    _tx(s, "stake", -RISK.stake, b.id, f"Engine B stake on bet #{b.id}")
    return b


def settle_pending() -> dict:
    out = {"settled": 0, "voided": 0, "pending": 0}
    with session_scope() as s:
        now = utcnow()
        for b in s.scalars(select(EBBet).where(EBBet.status == "pending")).all():
            fx = s.get(Fixture, b.fixture_id)
            if fx.result_conflict:
                out["pending"] += 1
                continue
            if fx.status == "finished" and fx.home_goals is not None:
                outcome, payout, rule = settle(b.market, b.selection, b.line, b.price, b.stake, fx.home_goals, fx.away_goals)
                src = fx.result_source or "?"
            elif (fx.status in ("postponed", "cancelled", "abandoned") or fx.kickoff_utc > b.kickoff_utc + timedelta(hours=48)) \
                    and now > b.kickoff_utc + timedelta(hours=48):
                outcome, payout, rule, src = "void", b.stake, "not played within 48h: stake refunded", fx.status
            else:
                out["pending"] += 1
                continue
            s.add(EBSettlement(bet_id=b.id, home_goals=fx.home_goals, away_goals=fx.away_goals, result_source=src,
                               outcome=outcome, payout=payout, rule=rule))
            cl = s.scalars(select(OddsObservation).where(OddsObservation.fixture_id == b.fixture_id,
                                                         OddsObservation.kind == "closing",
                                                         OddsObservation.bookmaker == b.bookmaker)).first()
            cp = None
            if cl is not None:
                cp = getattr(cl, b.selection, None) if b.market == "1X2" else getattr(cl, f"{b.selection}25", None)
            b.status, b.settled_at, b.payout, b.profit = outcome, now, payout, round(payout - b.stake, 2)
            if cp:
                b.closing_price, b.clv = cp, round(b.price / cp - 1, 4)
            if payout > 0:
                _tx(s, "refund" if outcome == "void" else "payout", payout, b.id, f"Engine B bet #{b.id} {outcome}")
            out["voided" if outcome == "void" else "settled"] += 1
    if out["settled"] or out["voided"]:
        log("INFO", "engine_b", f"settled {out}")
    return out
