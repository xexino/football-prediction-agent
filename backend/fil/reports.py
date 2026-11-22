"""Daily and weekly reports (stored in the database and shown on the dashboard)."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
from sqlalchemy import func, select

from .db import Competition, DataSource, Fixture, Prediction, Report, SystemLog, VirtualBet, session_scope
from .stats import bets_table, perf, summary
from .timeutil import rome, utcnow


def _pct(x):
    return "n/a" if x is None else f"{x:+.1%}"


def daily_report() -> dict:
    now = utcnow()
    start = now - timedelta(days=1)
    with session_scope() as s:
        comps = {c.id: c for c in s.scalars(select(Competition))}
        preds = s.execute(select(Prediction, Fixture).join(Fixture, Fixture.id == Prediction.fixture_id)
                          .where(Prediction.created_at >= start)).all()
        new_bets = bets_table(s, since=start)
        settled = [b for b in bets_table(s) if b["settled_at"] and b["settled_at"] >= start]
        upcoming = s.scalar(select(func.count(Fixture.id)).where(Fixture.status == "scheduled", Fixture.kickoff_utc > now,
                                                              Fixture.kickoff_utc < now + timedelta(days=7)))
        errors = s.scalars(select(SystemLog).where(SystemLog.ts >= start, SystemLog.level.in_(["WARNING", "ERROR"]))).all()
        teams = {}
        from .db import Team
        for t in s.scalars(select(Team)):
            teams[t.id] = t.name
        lines = [f"# Daily report — {rome(now)} (Europe/Rome)", "",
                 f"* Upcoming fixtures (7 days): **{upcoming}**",
                 f"* Predictions generated/revised (24h): **{len(preds)}** — BET: {sum(1 for p, _ in preds if p.decision == 'BET')}, "
                 f"NO BET: {sum(1 for p, _ in preds if p.decision == 'NO_BET')}",
                 f"* New simulated bets: **{len(new_bets)}**; settled in last 24h: **{len(settled)}** "
                 f"(P/L €{sum((b['payout'] or 0) - b['stake'] for b in settled):+.2f})", ""]
        if new_bets:
            lines.append("## New virtual bets")
            for b in new_bets:
                lines.append(f"* #{b['id']} {b['competition']} {b['market']} {b['selection']} @ {b['price']:.2f} (stake €{b['stake']:.2f})")
        else:
            lines.append("**NO BET** — no sufficiently reliable value opportunity identified in the last 24h.")
        sm = summary()
        lines += ["", "## Bankroll", f"* Current: €{sm['current_bankroll']:.2f} (start €{sm['starting_bankroll']:.2f}); "
                  f"settled ROI {_pct(sm['roi'])}; pending {sm['pending']}",
                  "", f"## Warnings/errors (24h): {len(errors)}"]
        for e in errors[-10:]:
            lines.append(f"* [{e.component}] {e.message[:200]}")
        content = {"upcoming": upcoming, "predictions": len(preds), "new_bets": len(new_bets), "settled": len(settled),
                   "bankroll": sm["current_bankroll"], "errors": len(errors)}
        rep = Report(kind="daily", period_start=start, period_end=now, content=content, markdown="\n".join(lines))
        s.add(rep)
        return content


def weekly_report() -> dict:
    now = utcnow()
    start = now - timedelta(days=7)
    with session_scope() as s:
        comps = {c.id: c.code for c in s.scalars(select(Competition))}
        rows = s.execute(select(Prediction, Fixture).join(Fixture, Fixture.id == Prediction.fixture_id).where(
            Prediction.created_at >= start)).all()
        evals = [p for p, f in rows if p.evaluated and p.revision == 0]
        bets = [b for b in bets_table(s) if b["created_at"] >= start]
        p = perf(bets)
        by_comp = {}
        for pr, f in rows:
            if pr.evaluated and pr.revision == 0:
                by_comp.setdefault(comps[f.competition_id], []).append(pr.eval_logloss)
        seg = {k: round(float(np.mean(v)), 4) for k, v in by_comp.items() if len(v) >= 3}
        best = sorted(seg.items(), key=lambda x: x[1])[:3]
        worst = sorted(seg.items(), key=lambda x: -x[1])[:3]
        dq = s.scalars(select(DataSource).where(DataSource.status != "ok")).all()
        low_q = sum(1 for pr, _ in rows if pr.data_quality < 70)
        content = {
            "matches_analyzed": len({f.id for _, f in rows}), "simulated_bets": len(bets), "performance": p,
            "brier": round(float(np.mean([x.eval_brier for x in evals])), 4) if evals else None,
            "log_loss": round(float(np.mean([x.eval_logloss for x in evals])), 4) if evals else None,
            "best_segments": best, "worst_segments": worst,
            "data_problems": [f"{d.name}: {d.status}" for d in dq] + ([f"{low_q} predictions below quality 70"] if low_q else []),
            "recommendations": [
                "Connect a team-news/lineup provider (API-Football key) — team news currently contributes 0/10 quality points.",
                "Keep flat €1 staking until ≥ 300 settled bets show positive CLV.",
                "Review competitions in 'worst segments' before trusting their predictions.",
            ],
        }
        md = [f"# Weekly performance report — week ending {rome(now)}", "",
              f"* Matches analysed: {content['matches_analyzed']}", f"* Simulated bets: {len(bets)} (settled {p['settled']})",
              f"* P/L: €{p['profit']:+.2f}; ROI {_pct(p['roi'])}; win rate {_pct(p['win_rate'])}",
              f"* Brier: {content['brier']}; log loss: {content['log_loss']} ({len(evals)} evaluated predictions)",
              f"* Best segments (log loss): {best}", f"* Worst segments: {worst}",
              "* Data problems: " + ("; ".join(content["data_problems"]) or "none"), "", "## Recommendations"] + \
             [f"* {r}" for r in content["recommendations"]]
        s.add(Report(kind="weekly", period_start=start, period_end=now, content=content, markdown="\n".join(md)))
        return content
