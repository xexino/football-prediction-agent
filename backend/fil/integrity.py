"""Database integrity & ledger reconciliation checks (used by jobs, the workflow guard and tests)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .config import settings

MANIFEST_TABLES = ("fixtures", "odds_observations", "predictions", "value_assessments", "virtual_bets",
                   "settlements", "bankroll_transactions", "eb_predictions", "eb_bets", "eb_settlements",
                   "eb_bankroll_transactions", "eb_live_snapshots", "eb_live_events")
from .db import IMMUTABLE

# Triggers every persisted database must already have (checked on the raw file BEFORE migrations run,
# so a removed trigger is detected instead of silently re-created).
BASE_TRIGGERS = tuple(f"trg_{t}_{k}" for t in IMMUTABLE for k in ("noupdate", "nodelete")) + (
    "trg_bets_no_resettle", "trg_bets_prekickoff", "trg_eb_bets_no_resettle", "trg_eb_bets_prekickoff")
# Added by later releases; installed by `fil migrate` (init_db) and required afterwards.
LATER_TRIGGERS = ("trg_bets_settled_frozen", "trg_bets_clv_once", "trg_eb_bets_settled_frozen", "trg_eb_bets_clv_once")
REQUIRED_TRIGGERS = BASE_TRIGGERS + LATER_TRIGGERS


def manifest(db_path: Path | str | None = None) -> dict:
    """Row counts of the append-only/immutable tables. Used to refuse persisting a database that
    has *fewer* audit records than the one it would replace (accidental reset / stale restore)."""
    con = sqlite3.connect(str(db_path or settings.db_path))
    try:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in MANIFEST_TABLES}
    finally:
        con.close()


def check_database(db_path: Path | str | None = None, pre_migration: bool = False) -> dict:
    """Read-only integrity check. Never creates or repairs anything (opens the file in read-only mode)."""
    path = Path(db_path or settings.db_path)
    if not path.exists() or path.stat().st_size == 0:
        return {"ok": False, "problems": [f"database file missing or empty: {path}"], "counts": {}}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
    except sqlite3.DatabaseError as exc:
        return {"ok": False, "problems": [f"not a readable SQLite database: {exc}"], "counts": {}}
    problems = []
    required = BASE_TRIGGERS if pre_migration else REQUIRED_TRIGGERS
    try:
        res = con.execute("PRAGMA quick_check").fetchone()[0]
        if res != "ok":
            problems.append(f"quick_check: {res}")
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            problems.append(f"{len(fk)} foreign-key violations")
        trig = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        missing = [t for t in required if t not in trig]
        if missing:
            problems.append(f"missing immutability triggers: {missing}")
        # bankroll ledger: balance chain must be consistent
        rows = con.execute("SELECT id, amount, balance_after FROM bankroll_transactions ORDER BY id").fetchall()
        bal = 0.0
        for _id, amt, after in rows:
            bal = round(bal + amt, 2)
            if abs(bal - after) > 0.005:
                problems.append(f"bankroll chain broken at tx {_id} ({bal} != {after})")
                break
        # every stake has exactly one bet, settled bets have a settlement row, payouts reconcile
        n_bets = con.execute("SELECT COUNT(*) FROM virtual_bets").fetchone()[0]
        n_stakes = con.execute("SELECT COUNT(*) FROM bankroll_transactions WHERE tx_type='stake'").fetchone()[0]
        if n_bets != n_stakes:
            problems.append(f"{n_bets} bets but {n_stakes} stake transactions")
        unsettled = con.execute("SELECT COUNT(*) FROM virtual_bets b LEFT JOIN settlements s ON s.bet_id=b.id "
                                "WHERE b.status!='pending' AND s.id IS NULL").fetchone()[0]
        if unsettled:
            problems.append(f"{unsettled} settled bets without settlement record")
        pay = con.execute("SELECT COALESCE(SUM(payout),0) FROM settlements").fetchone()[0]
        paid = con.execute("SELECT COALESCE(SUM(amount),0) FROM bankroll_transactions WHERE tx_type IN ('payout','refund')").fetchone()[0]
        if abs(pay - paid) > 0.01:
            problems.append(f"settlement payouts {pay} != bankroll credits {paid}")
        mism = con.execute("SELECT COUNT(*) FROM virtual_bets b JOIN settlements s ON s.bet_id=b.id "
                           "WHERE b.payout IS NULL OR ABS(b.payout - s.payout) > 0.005").fetchone()[0]
        if mism:
            problems.append(f"{mism} settled bets whose payout differs from the settlement record")
        late = con.execute("SELECT COUNT(*) FROM virtual_bets WHERE created_at >= kickoff_utc").fetchone()[0]
        if late:
            problems.append(f"{late} bets created at/after kickoff")
        dups = con.execute("SELECT COUNT(*) FROM (SELECT competition_id, home_team_id, away_team_id, match_date, COUNT(*) c "
                           "FROM fixtures GROUP BY 1,2,3,4 HAVING c>1)").fetchone()[0]
        if dups:
            problems.append(f"{dups} duplicate fixtures")
        bad_scores = con.execute("SELECT COUNT(*) FROM fixtures WHERE status='finished' AND (home_goals IS NULL OR home_goals<0 "
                                 "OR away_goals<0 OR home_goals>20 OR away_goals>20)").fetchone()[0]
        if bad_scores:
            problems.append(f"{bad_scores} finished fixtures with invalid scores")
        # Engine B ledger: same reconciliation, completely separate tables
        if con.execute("SELECT name FROM sqlite_master WHERE name='eb_bankroll_transactions'").fetchone():
            bal = 0.0
            for _id, amt, after in con.execute("SELECT id, amount, balance_after FROM eb_bankroll_transactions ORDER BY id"):
                bal = round(bal + amt, 2)
                if abs(bal - after) > 0.005:
                    problems.append(f"Engine B bankroll chain broken at tx {_id}")
                    break
            nb = con.execute("SELECT COUNT(*) FROM eb_bets").fetchone()[0]
            ns = con.execute("SELECT COUNT(*) FROM eb_bankroll_transactions WHERE tx_type='stake'").fetchone()[0]
            if nb != ns:
                problems.append(f"Engine B: {nb} bets but {ns} stake transactions")
        counts = {t: (con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      if con.execute("SELECT name FROM sqlite_master WHERE name=?", (t,)).fetchone() else 0)
                  for t in MANIFEST_TABLES}
    finally:
        con.close()
    return {"ok": not problems, "problems": problems, "counts": counts}


def guard_replace(new_db: str, old_manifest_json: str | None, pre_migration: bool = False) -> tuple[bool, str]:
    """Return (allowed, reason). Refuse to replace a persisted database with one holding fewer
    immutable records (would silently erase predictions/bets)."""
    chk = check_database(new_db, pre_migration=pre_migration)
    if not chk["ok"]:
        return False, f"new database fails integrity: {chk['problems']}"
    if not old_manifest_json:
        return True, "no previous manifest"
    old = json.loads(old_manifest_json)
    new = chk["counts"]
    shrunk = {t: (old[t], new.get(t, 0)) for t in ("predictions", "virtual_bets", "settlements", "bankroll_transactions",
                                                 "value_assessments", "eb_predictions", "eb_bets", "eb_settlements",
                                                 "eb_bankroll_transactions", "eb_live_snapshots", "eb_live_events")
              if new.get(t, 0) < old.get(t, 0)}
    if shrunk:
        return False, f"immutable tables would shrink (old, new): {shrunk}"
    return True, "ok"
