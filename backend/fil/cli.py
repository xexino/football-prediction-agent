"""Command-line interface:  python -m fil <command>

  serve                 run API + dashboard (+ scheduler) on FIL_HOST:FIL_PORT
  bootstrap             first-time full import + daily cycle
  job <name>            run one job (daily, fixtures_odds, results, prematch_review, weekly, backup)
  backtest [--step N]   walk-forward backtest
  backup | restore F    database backup / restore
  export-static DIR     write the dashboard + JSON snapshot for static hosting (GitHub Pages)
  status                print a short status summary
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="fil")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    sub.add_parser("bootstrap")
    j = sub.add_parser("job")
    j.add_argument("name")
    b = sub.add_parser("backtest")
    b.add_argument("--step", type=int, default=14)
    sub.add_parser("backup")
    r = sub.add_parser("restore")
    r.add_argument("file")
    e = sub.add_parser("export-static")
    e.add_argument("dir")
    sub.add_parser("status")
    sub.add_parser("integrity")
    m = sub.add_parser("manifest")
    m.add_argument("out")
    g = sub.add_parser("guard", help="exit 1 if DB must not replace the persisted one")
    g.add_argument("db")
    g.add_argument("prev_manifest", nargs="?")
    rr = sub.add_parser("run-report", help="markdown report of the latest job runs")
    rr.add_argument("--last", type=int, default=1)
    a = ap.parse_args(argv)

    if a.cmd == "guard":
        from .integrity import guard_replace

        prev = Path(a.prev_manifest).read_text() if a.prev_manifest and Path(a.prev_manifest).exists() else None
        ok, why = guard_replace(a.db, prev)
        print(("OK: " if ok else "REFUSED: ") + why)
        sys.exit(0 if ok else 1)

    from .db import init_db

    if a.cmd == "restore":
        from .backup import restore

        restore(Path(a.file))
        print("restored", a.file)
        return
    init_db()
    from .collect import register_all

    register_all()
    if a.cmd == "serve":
        import uvicorn

        from .config import settings

        uvicorn.run("fil.api:app", host=settings.host, port=settings.port, log_level="info")
    elif a.cmd in ("bootstrap", "job"):
        from .jobs import run_job

        res = run_job("bootstrap" if a.cmd == "bootstrap" else a.name, timeout_s=45 * 60)
        print(json.dumps({k: res.get(k) for k in ("status", "error")} | {"report": (res.get("summary") or {}).get("report")},
                         default=str, indent=1)[:6000])
        if res.get("status") == "error":
            sys.exit(1)
    elif a.cmd == "backtest":
        from .backtest import run_backtest

        res = run_backtest(step_days=a.step, progress=lambda i, t: print(f"step {i} {t:%Y-%m-%d}", flush=True))
        print(json.dumps({k: res[k] for k in ("metrics", "strategy", "strategy_by_market", "ensemble_weight_scan", "market_blend_scan")}, indent=1))
    elif a.cmd == "backup":
        from .backup import backup

        print(backup())
    elif a.cmd == "export-static":
        export_static(Path(a.dir))
    elif a.cmd == "integrity":
        from .integrity import check_database

        res = check_database()
        print(json.dumps(res, indent=1))
        sys.exit(0 if res["ok"] else 1)
    elif a.cmd == "manifest":
        from .integrity import manifest

        Path(a.out).write_text(json.dumps(manifest()))
        print(Path(a.out).read_text())
    elif a.cmd == "run-report":
        from sqlalchemy import select

        from .db import JobRun, session_scope
        from .jobs import report_markdown

        with session_scope() as s:
            runs = s.scalars(select(JobRun).where(JobRun.status != "skipped").order_by(JobRun.id.desc()).limit(a.last)).all()
            print("\n\n".join(report_markdown(r) for r in reversed(runs)))
    elif a.cmd == "status":
        from .api import health, overview

        print(json.dumps({"health": health(), "bankroll": overview()["bankroll"]}, indent=1, default=str))


def export_static(out: Path):
    """Snapshot every dashboard endpoint to JSON next to the built frontend (read-only site)."""
    from . import api

    static = Path(api.STATIC)
    out.mkdir(parents=True, exist_ok=True)
    if static.exists():
        shutil.copytree(static, out, dirs_exist_ok=True)
    data = out / "data"
    data.mkdir(exist_ok=True)
    snap = {
        "health": api.health(), "overview": api.overview(), "upcoming": api.upcoming(days=14),
        "predictions": api.predictions(limit=2000), "bets": api.bets(limit=5000), "analytics": api.analytics(),
        "sources": api.sources(), "system": api.system(), "health_detail": api.health_detail(), "standings": api.standings(), "reports": api.get_reports(limit=30), "meta": api.meta(),
    }
    from . import api_b

    snap.update(insights=api_b.insights(), engine_b_performance=api_b.performance(), engine_compare=api_b.compare(),
                coverage_matrix=api_b.coverage_matrix())
    for k, v in snap.items():
        (data / f"{k}.json").write_text(json.dumps(v, default=str))
    (data / "insights").mkdir(exist_ok=True)
    for it in snap["insights"]["items"]:
        (data / "insights" / f"{it['id']}.json").write_text(json.dumps(api_b.insight_detail(it["id"]), default=str))
    (data / "engine_b").mkdir(exist_ok=True)
    (data / "engine_b" / "performance.json").write_text(json.dumps(snap["engine_b_performance"], default=str))
    (out / "static-mode.json").write_text(json.dumps({"static": True, "exported_at": snap["health"]["time_utc"]}))
    print(f"exported {len(snap)} endpoints to {data}")


if __name__ == "__main__":
    main()
