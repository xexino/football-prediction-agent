"""Virtual bankroll, simulated bet placement and settlement. SIMULATION ONLY — no real money,
no bookmaker accounts, no external transactions of any kind."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import BankrollTransaction, Fixture, OddsObservation, Settlement, VirtualBet, log, session_scope
from .models.markets import settle
from .timeutil import utcnow

POSTPONE_VOID_HOURS = 48


def balance(s: Session) -> float:
    last = s.scalars(select(BankrollTransaction).order_by(BankrollTransaction.id.desc()).limit(1)).first()
    return last.balance_after if last else 0.0


def ensure_bankroll(s: Session) -> None:
    if s.scalar(select(func.count(BankrollTransaction.id))) == 0:
        amt = settings.risk.initial_bankroll
        s.add(BankrollTransaction(tx_type="initial", amount=amt, balance_after=amt,
                                  note=f"Initial virtual bankroll €{amt:.2f} (simulation)"))
        s.flush()


def _tx(s: Session, tx_type: str, amount: float, bet_id: int | None, note: str) -> None:
    bal = round(balance(s) + amount, 2)
    s.add(BankrollTransaction(tx_type=tx_type, amount=round(amount, 2), balance_after=bal, bet_id=bet_id, note=note))
    s.flush()


def place_bet(s: Session, *, prediction, assessment_row, fixture: Fixture, model_version_id: int) -> VirtualBet | None:
    risk = settings.risk
    now = utcnow()
    if now >= fixture.kickoff_utc - timedelta(minutes=5):
        return None
    n_match = s.scalar(select(func.count(VirtualBet.id)).where(VirtualBet.fixture_id == fixture.id))
    if n_match >= risk.max_bets_per_match:
        return None
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    n_day = s.scalar(select(func.count(VirtualBet.id)).where(VirtualBet.created_at >= day_start))
    if n_day >= risk.max_bets_per_day:
        return None
    stake = min(risk.stake, risk.max_stake)  # flat staking only; never increased after losses
    if balance(s) < stake:
        log("WARNING", "betting", "virtual bankroll exhausted — no further bets")
        return None
    bet = VirtualBet(prediction_id=prediction.id, value_assessment_id=assessment_row.id, fixture_id=fixture.id,
                     model_version_id=model_version_id, market=assessment_row.market,
                     selection=assessment_row.selection, line=assessment_row.line, price=assessment_row.price,
                     bookmaker=assessment_row.bookmaker, stake=stake,
                     potential_return=round(stake * assessment_row.price, 2), model_prob=assessment_row.model_prob,
                     ev=assessment_row.ev, created_at=now, kickoff_utc=fixture.kickoff_utc, status="pending")
    s.add(bet)
    s.flush()
    _tx(s, "stake", -stake, bet.id, f"Stake on bet #{bet.id}")
    return bet


def _closing_price(s: Session, bet: VirtualBet) -> float | None:
    o = s.scalars(select(OddsObservation).where(
        OddsObservation.fixture_id == bet.fixture_id, OddsObservation.kind == "closing",
        OddsObservation.bookmaker == bet.bookmaker).order_by(OddsObservation.retrieved_at.desc())).first()
    if o is None:
        return None
    if bet.market == "1X2":
        return getattr(o, bet.selection)
    if bet.market == "OU25":
        return getattr(o, f"{bet.selection}25")
    if bet.market == "AH" and o.ah_line == bet.line:
        return o.ah_home if bet.selection == "home" else o.ah_away
    return None


def settle_pending() -> dict:
    """Settle every pending bet whose fixture has a verified, conflict-free result."""
    out = {"settled": 0, "voided": 0, "still_pending": 0, "conflicts": 0}
    with session_scope() as s:
        now = utcnow()
        for bet in s.scalars(select(VirtualBet).where(VirtualBet.status == "pending")).all():
            fx = s.get(Fixture, bet.fixture_id)
            if fx.result_conflict:
                out["conflicts"] += 1
                out["still_pending"] += 1
                continue
            if fx.status == "finished" and fx.home_goals is not None:
                outcome, payout, rule = settle(bet.market, bet.selection, bet.line, bet.price, bet.stake,
                                               fx.home_goals, fx.away_goals)
                src = fx.result_source or "unknown"
            elif (fx.status in ("postponed", "cancelled", "abandoned")
                  or fx.kickoff_utc > bet.kickoff_utc + timedelta(hours=POSTPONE_VOID_HOURS)) and \
                    now > bet.kickoff_utc + timedelta(hours=POSTPONE_VOID_HOURS):
                outcome, payout, rule, src = "void", bet.stake, f"Match {fx.status}, not played within {POSTPONE_VOID_HOURS}h: stake refunded", fx.status
            else:
                out["still_pending"] += 1
                continue
            s.add(Settlement(bet_id=bet.id, home_goals=fx.home_goals, away_goals=fx.away_goals,
                             result_source=src, outcome=outcome, payout=payout, rule=rule))
            cp = _closing_price(s, bet)
            bet.status, bet.settled_at, bet.payout = outcome, now, payout
            bet.profit = round(payout - bet.stake, 2)
            if cp:
                bet.closing_price = cp
                bet.clv = round(bet.price / cp - 1, 4)
            if payout > 0:
                _tx(s, "refund" if outcome == "void" else "payout", payout, bet.id,
                    f"Bet #{bet.id} {outcome} ({fx.home_goals}-{fx.away_goals})" if outcome != "void" else f"Bet #{bet.id} void")
            out["voided" if outcome == "void" else "settled"] += 1
    return out
