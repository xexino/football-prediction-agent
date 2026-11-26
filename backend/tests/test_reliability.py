"""Reliability / self-monitoring tests (autopilot hardening, 2026-11-23)."""
from __future__ import annotations

import gzip
import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fil.ops import schedule, status, watchdog

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/autopilot.yml").read_text()


# --------------------------------------------------------------------------- A. workflow logic
def _workflow_crons():
    return re.findall(r'-\s*cron:\s*"([^"]+)"', WORKFLOW)


def test_every_workflow_cron_is_routed_and_valid():
    crons = _workflow_crons()
    assert crons and set(crons) == set(schedule.SCHEDULES), "autopilot.yml and fil/ops/schedule.py must list the same crons"
    for c in crons:
        schedule.parse(c)  # raises on an invalid expression


@pytest.mark.parametrize("cron,job", [("10 5 * * *", "daily"), ("40 */3 * * *", "results,fixtures_odds"),
                                      ("25 6 * * 1", "weekly"), ("7,27,47 11-23 * * *", "live")])
def test_cron_to_job_routing(cron, job):
    assert schedule.route("schedule", cron) == job


def test_unknown_schedule_is_an_error_not_a_default_job():
    with pytest.raises(schedule.RoutingError):
        schedule.route("schedule", "0 0 * * *")
    with pytest.raises(schedule.RoutingError):
        schedule.route("push")


def test_manual_dispatch_is_validated():
    assert schedule.route("workflow_dispatch", requested="weekly") == "weekly"
    assert schedule.route("workflow_dispatch", requested="results, fixtures_odds") == "results,fixtures_odds"
    assert schedule.route("workflow_dispatch", requested="") == "daily"
    for bad in ("drop_tables", "daily;rm -rf /", "daily,unknown"):
        with pytest.raises(schedule.RoutingError):
            schedule.route("workflow_dispatch", requested=bad)


def test_empty_database_always_bootstraps():
    assert schedule.route("schedule", "10 5 * * *", db_source="none") == "bootstrap"


def test_live_and_three_hourly_never_share_a_minute():
    live = schedule.parse("7,27,47 11-23 * * *")[0]
    three = schedule.parse("40 */3 * * *")[0]
    assert not (live & three)


def test_workflow_failure_semantics():
    # the scheduled cron string must not be interpolated into shell code (injection); it is passed via env
    assert "case \"${{ github.event.schedule }}\"" not in WORKFLOW
    assert "${{ github.event.inputs.job }}\"" not in WORKFLOW
    # persist and export never run after a failed restore
    for step in ("Persist database (guarded)", "Export static dashboard"):
        block = WORKFLOW.split(f"name: {step}")[1].split("- name:")[0]
        assert "steps.restore.outcome == 'success'" in block, step
    # the run report may not change the outcome, and errors are not swallowed with `|| true`
    assert "|| true" not in WORKFLOW
    # database first, manifest last
    assert WORKFLOW.index("data/fil.db.gz --clobber") < WORKFLOW.index("data/manifest.json --clobber")
    # provider secrets only in the Run step
    run_block = WORKFLOW.split("name: Run\n")[1].split("- name:")[0]
    assert WORKFLOW.count("secrets.") == run_block.count("secrets.")


def test_cron_slots():
    s = schedule.slots("40 */3 * * *", datetime(2026, 11, 23, 0, 0), datetime(2026, 11, 23, 7, 0))
    assert [t.hour for t in s] == [0, 3, 6]
    assert schedule.matches("25 6 * * 1", datetime(2026, 11, 23, 6, 25))  # Monday
    assert not schedule.matches("25 6 * * 1", datetime(2026, 11, 24, 6, 25))


# --------------------------------------------------------------------------- watchdog
NOW = datetime(2026, 11, 23, 12, 0)


def _run(i, created, conclusion="success", event="schedule", title="Autopilot · 40 */3 * * *", status_="completed", dur=5):
    c = created
    return {"id": i, "event": event, "status": status_, "conclusion": conclusion if status_ == "completed" else None,
            "created_at": c.isoformat() + "Z", "run_started_at": c.isoformat() + "Z",
            "updated_at": (c + timedelta(minutes=dur)).isoformat() + "Z", "display_title": title, "html_url": f"u/{i}"}


def _all_slots(start, end, conclusion="success"):
    runs, i = [], 0
    for cron in schedule.SCHEDULES:
        for t in schedule.slots(cron, start, end):
            i += 1
            runs.append(_run(i, t + timedelta(minutes=3), conclusion, title=f"Autopilot · {cron}"))
    return runs


def test_watchdog_healthy_when_every_slot_ran():
    rep = watchdog.evaluate(_all_slots(NOW - timedelta(hours=26), NOW - timedelta(minutes=10)), NOW)
    assert rep["status"] == "HEALTHY" and not rep["alert"], rep["findings"]


def test_watchdog_detects_missing_scheduled_runs():
    rep = watchdog.evaluate([_run(1, NOW - timedelta(hours=1))], NOW)
    codes = {f["code"] for f in rep["findings"]}
    assert "missed_schedules" in codes and rep["alert"] and rep["status"] == "FAILED"
    assert rep["scorecard"]["scheduled_slots_missed"]["critical"] >= 2


def test_watchdog_respects_first_seen():
    runs = [_run(1, NOW - timedelta(minutes=30), title="Autopilot · daily", event="workflow_dispatch")]
    rep = watchdog.evaluate(runs, NOW, first_seen=NOW - timedelta(minutes=50))
    assert rep["status"] == "HEALTHY"


def test_watchdog_detects_failures_stuck_and_staleness():
    base = _all_slots(NOW - timedelta(hours=26), NOW - timedelta(minutes=10))
    newest = max(base, key=lambda r: r["created_at"] if "40 */3" in r["display_title"] else "")
    newest["conclusion"] = "failure"
    rep = watchdog.evaluate(base, NOW)
    assert any(f["code"] == "critical_failure" for f in rep["findings"]) and rep["alert"]
    stuck = base + [_run(999, NOW - timedelta(minutes=120), status_="in_progress")]
    assert any(f["code"] == "stuck" for f in watchdog.evaluate(stuck, NOW)["findings"])
    old = [_run(1, NOW - timedelta(hours=10), event="workflow_dispatch", title="Autopilot · daily")]
    rep = watchdog.evaluate(old, NOW, first_seen=NOW - timedelta(hours=11))
    assert any(f["code"] == "success_overdue" for f in rep["findings"])


def test_watchdog_live_failures_are_best_effort():
    runs = _all_slots(NOW - timedelta(hours=26), NOW - timedelta(minutes=10))
    live = sorted((r for r in runs if "7,27,47" in r["display_title"]), key=lambda r: r["created_at"], reverse=True)
    live[0]["conclusion"] = "failure"
    rep = watchdog.evaluate(runs, NOW)
    assert rep["status"] == "DEGRADED" and not rep["alert"]
    for r in live[:3]:
        r["conclusion"] = "failure"
    assert watchdog.evaluate(runs, NOW)["alert"]


def test_watchdog_issue_deduplication_and_recovery():
    bad = watchdog.evaluate([], NOW)
    assert bad["alert"]
    d1 = watchdog.decide(bad, [])
    assert d1["action"] == "create" and watchdog.FP_MARK in d1["body"]
    issue = {"number": 7, "body": d1["body"], "comments": []}
    assert watchdog.decide(bad, [issue])["action"] == "none"  # same incident: no spam
    other = watchdog.evaluate([_run(1, NOW - timedelta(minutes=120), status_="in_progress")], NOW)
    assert watchdog.decide(other, [issue])["action"] == "comment"  # problem set changed
    good = watchdog.evaluate(_all_slots(NOW - timedelta(hours=26), NOW - timedelta(minutes=10)), NOW)
    d = watchdog.decide(good, [issue])
    assert d["action"] == "close" and "Recovered" in d["body"]
    assert watchdog.decide(good, [])["action"] == "none"


def test_watchdog_cli(tmp_path):
    (tmp_path / "runs.json").write_text(json.dumps({"workflow_runs": []}))
    assert watchdog.main(["--runs", str(tmp_path / "runs.json"), "--out", str(tmp_path / "d.json"),
                          "--now", "2026-11-23T12:00:00Z"]) == 0
    out = json.loads((tmp_path / "d.json").read_text())
    assert out["decision"]["action"] == "create"


# --------------------------------------------------------------------------- B. operational status model
OK_ENV = {"OPS_RUN_ID": "1", "OPS_RESTORE": "success", "OPS_ROUTE": "success", "OPS_JOB_STATUS": "success",
          "OPS_PERSIST": "persisted", "OPS_EXPORT": "success", "OPS_JOB": "daily", "OPS_EVENT": "schedule"}


def test_ops_status_healthy_degraded_failed():
    st, h = status.build(OK_ENV, [])
    assert st["current"]["state"] == "HEALTHY" and st["last_success_at"] and not st["current"]["partial"]
    st, _ = status.build({**OK_ENV, "OPS_RUN_ID": "2", "OPS_JOB_STATUS": "partial"}, h)
    assert st["current"]["state"] == "DEGRADED" and st["current"]["partial"]
    st, _ = status.build({**OK_ENV, "OPS_RUN_ID": "3", "OPS_PERSIST": "refused"}, h)
    assert st["current"]["state"] == "FAILED" and st["current"]["failure_stage"] == "persist"


def test_ops_status_after_failed_restore_uses_previous_snapshot():
    st, h = status.build({"OPS_RUN_ID": "9", "OPS_RESTORE": "failure", "OPS_ROUTE": "skipped",
                          "OPS_EXPORT": "skipped"}, [])
    cur = st["current"]
    assert cur["state"] == "FAILED" and cur["failure_stage"] == "restore"
    assert cur["dashboard_data"] == "previous_snapshot" and cur["partial"]
    assert cur["stages"]["persist"] == "not_run"


def test_ops_status_failed_run_and_consecutive_failures():
    h = []
    for i in range(3):
        st, h = status.build({**OK_ENV, "OPS_RUN_ID": str(i), "OPS_JOB_STATUS": "error"}, h)
    assert st["current"]["failure_stage"] == "run" and st["consecutive_failures"] == 3
    st, h = status.build({**OK_ENV, "OPS_RUN_ID": "ok"}, h)
    assert st["consecutive_failures"] == 0 and st["last_failure_stage"] == "run"


def test_ops_status_persist_step_failure_and_live_unchanged():
    st, _ = status.build({**OK_ENV, "OPS_PERSIST": "", "OPS_PERSIST_STEP": "failure"}, [])
    assert st["current"]["failure_stage"] == "persist"
    st, _ = status.build({**OK_ENV, "OPS_PERSIST": "unchanged", "OPS_JOB": "live"}, [])
    assert st["current"]["state"] == "HEALTHY"


def test_ops_status_cli_tolerates_damaged_history(tmp_path, monkeypatch):
    prev = tmp_path / "prev.json"
    prev.write_text("{not json")
    for k, v in OK_ENV.items():
        monkeypatch.setenv(k, v)
    assert status.main(["--site", str(tmp_path / "site"), "--prev", str(prev)]) == 0
    out = json.loads((tmp_path / "site/data/ops_status.json").read_text())
    assert out["current"]["state"] == "HEALTHY"
    assert len(json.loads((tmp_path / "site/data/ops_history.json").read_text())) == 1


def test_ops_status_history_is_bounded():
    h = []
    for i in range(status.HISTORY_KEEP + 20):
        _, h = status.build({**OK_ENV, "OPS_RUN_ID": str(i)}, h)
    assert len(h) == status.HISTORY_KEEP


# --------------------------------------------------------------------------- D. database safety
def test_integrity_cli_does_not_heal_missing_triggers(db, capsys):
    from fil import cli
    from fil.config import settings

    con = sqlite3.connect(settings.db_path)
    con.execute("DROP TRIGGER trg_predictions_nodelete")
    con.commit()
    con.close()
    with pytest.raises(SystemExit) as e:
        cli.main(["integrity"])
    assert e.value.code == 1
    assert "trg_predictions_nodelete" in capsys.readouterr().out
    trig = {r[0] for r in sqlite3.connect(settings.db_path).execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert "trg_predictions_nodelete" not in trig  # the check did not re-create it


def test_pre_migration_check_accepts_older_schema_then_migrate_adds_triggers(db):
    from fil import cli
    from fil.config import settings
    from fil.integrity import LATER_TRIGGERS, check_database

    con = sqlite3.connect(settings.db_path)
    for t in LATER_TRIGGERS:
        con.execute(f"DROP TRIGGER {t}")
    con.commit()
    con.close()
    assert check_database(pre_migration=True)["ok"]
    assert not check_database()["ok"]
    cli.main(["migrate"])
    assert check_database()["ok"]


def test_integrity_rejects_missing_or_corrupt_file(tmp_path):
    from fil.integrity import check_database

    assert not check_database(tmp_path / "nope.db")["ok"]
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not sqlite" * 100)
    assert not check_database(bad)["ok"]


@pytest.fixture
def settled_bet(db):
    """A minimal settled bet inserted directly (triggers are what is under test, not the settlement code)."""
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("INSERT INTO virtual_bets (id, prediction_id, value_assessment_id, fixture_id, model_version_id, market, selection, "
                "price, bookmaker, stake, potential_return, model_prob, ev, created_at, kickoff_utc, status) VALUES "
                "(1, 1, 1, 1, 1, '1X2', 'home', 2.0, 'B365', 1.0, 2.0, 0.55, 0.1, '2026-01-01 10:00:00', '2026-01-01 15:00:00', 'pending')")
    con.execute("UPDATE virtual_bets SET status='won', payout=2.0, profit=1.0, settled_at='2026-01-01 17:00:00' WHERE id=1")
    con.commit()
    yield con
    con.close()


def test_settled_bet_payout_cannot_change(settled_bet):
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        settled_bet.execute("UPDATE virtual_bets SET payout=5.0 WHERE id=1")
    with pytest.raises(sqlite3.IntegrityError):
        settled_bet.execute("UPDATE virtual_bets SET profit=4.0 WHERE id=1")


def test_settled_bet_clv_fills_once(settled_bet):
    settled_bet.execute("UPDATE virtual_bets SET closing_price=1.9, clv=0.0526 WHERE id=1")
    settled_bet.commit()
    with pytest.raises(sqlite3.IntegrityError, match="only be filled once"):
        settled_bet.execute("UPDATE virtual_bets SET clv=0.5 WHERE id=1")


def test_restore_rejects_corrupt_backup_and_keeps_original(db, tmp_path):
    from fil import backup
    from fil.config import settings
    from fil.integrity import manifest

    before = manifest()
    bad = tmp_path / "bad.db.gz"
    with gzip.open(bad, "wb") as f:
        f.write(b"garbage" * 1000)
    with pytest.raises(RuntimeError):
        backup.restore(bad)
    assert manifest() == before  # original untouched
    assert not Path(str(settings.db_path) + ".restore-candidate").exists()
    trunc = tmp_path / "trunc.db.gz"
    trunc.write_bytes(b"\x1f\x8b\x08\x00broken")
    with pytest.raises(RuntimeError):
        backup.restore(trunc)
    assert manifest() == before


def test_guard_refuses_stale_restored_asset(db, tmp_path):
    """The restored database must hold at least as many immutable records as its manifest."""
    from fil.config import settings
    from fil.integrity import guard_replace, manifest

    m = manifest()
    m["predictions"] = m.get("predictions", 0) + 5  # manifest describes a NEWER database than the file
    ok, why = guard_replace(str(settings.db_path), json.dumps(m), pre_migration=True)
    assert not ok and "shrink" in why


# --------------------------------------------------------------------------- E. pipeline / providers
def test_odds_api_errors_are_not_masked(db, monkeypatch):
    from fil import collect
    from fil.db import DataSource, session_scope
    from fil.providers.base import ProviderError

    oapi = collect.provider("the_odds_api")
    monkeypatch.setattr(type(oapi), "configured", property(lambda self: True))
    oapi.register()

    def boom(self, code):
        raise ProviderError("HTTP 401: access denied")
    monkeypatch.setattr(type(oapi), "odds", boom)
    for _ in range(3):  # three failing runs of the real collection function
        res = collect.collect_odds_api(oapi)
        assert res["records"] == 0 and res["errors"]  # a failure is reported, never an empty "success"
    with session_scope() as s:
        ds = s.query(DataSource).filter_by(key="the_odds_api").one()
        assert ds.status == "error"
        assert ds.quota_info["circuit"]["failures"] == 3 and ds.quota_info["circuit"]["open_until"]
        assert ds.quota_info["last_error_kind"] == "auth_failed"
    assert oapi.circuit_open()


@pytest.mark.parametrize("msg,kind", [("rate limited (429) at x", "rate_limited"), ("HTTP 401: access denied", "auth_failed"),
                                      ("HTTP 503 at x", "unavailable"), ("malformed JSON", "invalid_response"),
                                      ("API key not configured", "missing_credentials")])
def test_provider_error_kinds(msg, kind):
    from fil.providers.base import error_kind

    assert error_kind(msg) == kind


def test_probability_renormalisation():
    from fil.pipeline import _renormalise

    out = _renormalise({"1X2": {"home": 0.45487, "draw": 0.25793, "away": 0.28721},
                        "OU25": {"over": 0.50001, "under": 0.50001}, "OTHER": {"a": 0.3}})
    assert abs(sum(out["1X2"].values()) - 1) < 1e-9
    assert abs(sum(out["OU25"].values()) - 1) < 1e-9
    assert out["OTHER"] == {"a": 0.3}
    assert out["1X2"]["home"] == pytest.approx(0.45486)  # residue taken from the largest outcome only


# --------------------------------------------------------------------------- F. dashboard truthfulness
def test_health_uses_degraded_and_reports_live(db):
    from fil import health

    h = health.compute(include_db_check=True)
    assert "WARNING" not in json.dumps(h["states"])
    assert h["components"]["live"]["state"] == "UNKNOWN"  # no live snapshot: never claimed
    assert h["components"]["database"]["state"] == "HEALTHY"


def test_local_server_does_not_invent_pipeline_status():
    from fil.api import ops_status

    assert ops_status()["current"] is None


def test_frontend_never_hides_simulation_notice_without_replacement():
    css = (ROOT / "frontend/src/styles.css").read_text()
    main = (ROOT / "frontend/src/main.tsx").read_text()
    assert ".mobile-disclaimer" in css and "mobile-disclaimer" in main and "SIMULATION ONLY" in main
    assert "OpsBanner" in main


def test_watchdog_queue_time_and_manual_runs():
    base = _all_slots(NOW - timedelta(hours=26), NOW - timedelta(minutes=10))
    queued = base + [_run(500, NOW - timedelta(minutes=100), status_="queued")]  # waiting in the concurrency queue
    assert not any(f["code"] == "stuck" for f in watchdog.evaluate(queued, NOW)["findings"])
    manual = base + [_run(501, NOW - timedelta(minutes=5), "failure", event="workflow_dispatch", title="Autopilot · engine_b")]
    rep = watchdog.evaluate(manual, NOW)
    assert any(f["code"] == "manual_failure" for f in rep["findings"]) and not rep["alert"]


def test_manifest_covers_live_events():
    from fil.integrity import MANIFEST_TABLES

    assert "eb_live_events" in MANIFEST_TABLES


# --------------------------------------------------------------------------- dispatcher / gate / catch-up (2026-11-25)
from fil.ops import dispatcher


def test_dispatcher_due_slots():
    assert dispatcher.due(datetime(2026, 11, 25, 9, 40)) == [("40 */3 * * *", "results,fixtures_odds")]
    assert dispatcher.due(datetime(2026, 11, 25, 5, 10)) == [("10 5 * * *", "daily")]
    assert dispatcher.due(datetime(2026, 11, 25, 12, 7)) == [("7,27,47 11-23 * * *", "live")]
    assert dispatcher.due(datetime(2026, 11, 25, 9, 41)) == []
    assert [j for _, j in dispatcher.due(datetime(2026, 11, 23, 6, 25))] == ["weekly"]  # Monday


def _api_run(i, created, title, event="schedule", conclusion="success", actor="xexino", status_="completed"):
    return {"id": i, "created_at": created.isoformat() + "Z", "updated_at": (created + timedelta(minutes=6)).isoformat() + "Z",
            "run_started_at": created.isoformat() + "Z", "display_title": title, "event": event,
            "conclusion": conclusion if status_ == "completed" else None, "status": status_,
            "triggering_actor": {"login": actor}, "html_url": f"u/{i}"}


def test_dispatcher_skips_slots_covered_by_cron_runs():
    slot = datetime(2026, 11, 25, 9, 40)
    runs = [_api_run(1, slot + timedelta(minutes=2), "Autopilot · 40 */3 * * *")]
    assert dispatcher.covered(runs, "40 */3 * * *", "results,fixtures_odds", slot)
    old = [_api_run(1, slot - timedelta(hours=3), "Autopilot · 40 */3 * * *")]
    assert not dispatcher.covered(old, "40 */3 * * *", "results,fixtures_odds", slot)


def test_gate_skips_late_duplicate_cron_runs_only():
    now = datetime(2026, 11, 25, 15, 45)
    done = [_api_run(1, datetime(2026, 11, 25, 5, 10), "Autopilot · daily", event="workflow_dispatch", actor=watchdog.BOT)]
    assert dispatcher.is_duplicate(done, "daily", 99, now)  # GitHub delivered the 05:10 cron 10 h late
    failed = [_api_run(1, datetime(2026, 11, 25, 5, 10), "Autopilot · daily", conclusion="failure")]
    assert not dispatcher.is_duplicate(failed, "daily", 99, now)  # a failed run does not cover the slot
    assert not dispatcher.is_duplicate([], "daily", 99, now)
    live = [_api_run(1, now - timedelta(minutes=30), "Autopilot · live", event="workflow_dispatch", actor=watchdog.BOT)]
    assert not dispatcher.is_duplicate(live, "live", 99, now)


def test_watchdog_counts_dispatcher_runs_as_covering_slots():
    runs = []
    i = 0
    for cron, (job, _k, _d) in schedule.SCHEDULES.items():
        for t in schedule.slots(cron, NOW - timedelta(hours=26), NOW - timedelta(minutes=10)):
            i += 1
            runs.append(_api_run(i, t + timedelta(minutes=1), f"Autopilot · {job}", event="workflow_dispatch", actor=watchdog.BOT))
    rep = watchdog.evaluate(runs, NOW)
    assert rep["status"] == "HEALTHY", rep["findings"]
    # dispatcher failures are alerted (they are not the owner's manual runs)
    crit = max((r for r in runs if r["display_title"].endswith("results,fixtures_odds")), key=lambda r: r["created_at"])
    crit["conclusion"] = "failure"
    assert any(f["code"] == "critical_failure" for f in watchdog.evaluate(runs, NOW)["findings"])


def test_catch_up_rules():
    old = [_api_run(1, NOW - timedelta(hours=5), "Autopilot · results,fixtures_odds", event="workflow_dispatch", actor=watchdog.BOT),
           _api_run(2, NOW - timedelta(hours=10), "Autopilot · daily", event="workflow_dispatch", actor=watchdog.BOT)]
    running_dispatcher = [{"status": "in_progress"}]
    acts = watchdog.catch_up(old, running_dispatcher, NOW)
    assert acts == [{"workflow": "autopilot.yml", "job": "results,fixtures_odds", "reason": acts[0]["reason"]}]
    assert any(a["workflow"] == "dispatcher.yml" for a in watchdog.catch_up(old, [], NOW))
    no_daily = [_api_run(1, NOW - timedelta(hours=1), "Autopilot · results,fixtures_odds")]
    assert watchdog.catch_up(no_daily, running_dispatcher, NOW)[0]["job"] == "daily"
    busy = old + [_api_run(3, NOW - timedelta(minutes=5), "Autopilot · live", status_="in_progress")]
    assert watchdog.catch_up(busy, running_dispatcher, NOW) == []
    failing = old + [_api_run(4, NOW - timedelta(hours=1), "Autopilot · results,fixtures_odds", event="workflow_dispatch",
                              actor=watchdog.BOT, conclusion="failure")]
    assert watchdog.catch_up(failing, running_dispatcher, NOW) == []  # bounded: no retry loop


def test_autopilot_has_gate_and_job_level_concurrency():
    assert "needs: gate" in WORKFLOW and "if: needs.gate.outputs.run == 'true'" in WORKFLOW
    head = WORKFLOW.split("jobs:")[0]
    assert "concurrency:" not in head  # the gate must never wait in (or displace) the run queue
    disp = (ROOT / ".github/workflows/dispatcher.yml").read_text()
    assert "dispatcher.py" in disp and "actions: write" in disp


# --------------------------------------------------------------------------- data/UI audit fixes (2026-11-25)
def test_fixtures_job_settles_and_evaluates_engine_a():
    from fil.jobs import JOBS

    names = [n for n, _f, _c in JOBS["fixtures_odds"]()]
    assert names.index("fixtures") < names.index("settle") < names.index("predict")
    assert "evaluate" in names


def test_overdue_results_are_not_healthy(db):
    from datetime import timedelta as td

    from fil import health
    from fil.db import Competition, Fixture, Team, session_scope
    from fil.timeutil import utcnow
    from sqlalchemy import select

    with session_scope() as s:
        comp = s.scalars(select(Competition)).first()
        a, b = Team(name="Alpha FC", country=comp.country), Team(name="Beta FC", country=comp.country)
        s.add_all([a, b]); s.flush()
        for h in (5, 40, 41, 42, 43, 44):
            ko = utcnow() - td(hours=h)
            s.add(Fixture(competition_id=comp.id, home_team_id=a.id, away_team_id=b.id, kickoff_utc=ko,
                          match_date=str((ko - td(days=h)).date()), status="scheduled", first_seen_source="test"))
    r = health.compute(include_db_check=False)["components"]["results"]
    assert r["overdue"] == 6 and r["overdue_24h"] == 5 and r["state"] == "STALE"


def test_ambiguous_alias_is_never_guessed(db):
    from fil.db import Team, TeamAlias, session_scope
    from fil.teamnames import TeamResolver

    with session_scope() as s:
        t1, t2 = Team(name="Paris FC", country="France"), Team(name="Paris SG", country="France")
        s.add_all([t1, t2]); s.flush()
        s.add_all([TeamAlias(alias_norm="paris", source="x", team_id=t1.id, confidence=0.9),
                   TeamAlias(alias_norm="paris", source="y", team_id=t2.id, confidence=0.9)])
        s.flush()
        tid, _ = TeamResolver(s).resolve("Paris", "z", country="France", create=False)
        assert tid is None


def test_stale_cache_marks_provider_degraded(db):
    from fil.collect import provider
    from fil.db import DataSource, session_scope

    p = provider("intl_results")
    p.register()
    p.stale_served = 2
    p.mark_success(records=1, requests=1)
    with session_scope() as s:
        ds = s.query(DataSource).filter_by(key="intl_results").one()
        assert ds.status == "degraded" and "stale cache" in ds.last_error
    p.mark_success(records=1, requests=1)
    with session_scope() as s:
        assert s.query(DataSource).filter_by(key="intl_results").one().status == "ok"


def test_corrupt_exchange_prices_are_not_used_as_reference():
    from types import SimpleNamespace as NS

    from fil.value import pick, plausible

    bad_bfe = NS(home=2.0, draw=1.10, away=4.0, over25=None, under25=None)   # overround ~ +66 %
    ps = NS(home=2.05, draw=3.6, away=3.9, over25=None, under25=None)
    assert not plausible("BFE", bad_bfe, ("home", "draw", "away"))
    assert plausible("PS", ps, ("home", "draw", "away"))
    assert pick({"BFE": bad_bfe, "PS": ps}, ["BFE", "PS", "Avg"], ("home", "draw", "away")) is ps
    good_bfe = NS(home=2.1, draw=3.7, away=4.1, over25=None, under25=None)
    assert pick({"BFE": good_bfe, "PS": ps}, ["BFE", "PS"], ("home", "draw", "away")) is good_bfe


def test_engine_b_market_skips_corrupt_bfe():
    from types import SimpleNamespace as NS

    from fil.engine_b.pipeline import market_1x2

    m = market_1x2({"BFE": NS(home=2.0, draw=1.10, away=4.0), "PS": NS(home=2.05, draw=3.6, away=3.9)})
    assert m["bookmaker"] == "PS"


# --------------------------------------------------------------------------- model 1.1.0 + identity dry run
def test_sot_proxy_real_xg_first_and_missing_stays_missing():
    from fil.models.engine import PARAMS, with_sot_proxy

    ms = [{"hxg": 1.4, "axg": 0.9, "hsot": 10, "asot": 2},      # real xG wins
          {"hxg": None, "axg": None, "hsot": 5, "asot": 3},    # proxy
          {"hxg": None, "axg": None, "hsot": None, "asot": 4}]  # incomplete SOT: stays missing (never 0)
    out = with_sot_proxy(ms, PARAMS["sot_xg_coef"])
    assert (out[0]["hxg"], out[0]["axg"]) == (1.4, 0.9)
    assert out[1]["hxg"] == pytest.approx(5 * 0.3184) and out[1]["axg"] == pytest.approx(3 * 0.3184)
    assert out[2]["hxg"] is None and out[2]["axg"] is None
    assert ms[1]["hxg"] is None  # input not mutated
    assert PARAMS["dc_sot_proxy"] is True and PARAMS["sot_xg_coef"] == 0.3184  # frozen


def test_identity_dry_run_never_writes(db, tmp_path):
    from fil.config import settings
    from fil.db import Team, session_scope
    from fil.identity import dry_run
    from fil.integrity import manifest

    with session_scope() as s:
        s.add_all([Team(name="Arsenal", country="England"), Team(name="Arsenal", country="Europe")])
    before = (manifest(), Path(settings.db_path).stat().st_mtime)
    r = dry_run(tmp_path / "r.md", tmp_path / "r.json")
    assert (manifest(), Path(settings.db_path).stat().st_mtime) == before
    assert (tmp_path / "r.md").read_text().startswith("# UEFA team identity")
    assert r["europe_teams"] == 1


def test_dispatcher_starts_watchdog_and_fails_loudly(monkeypatch):
    calls = []
    monkeypatch.setattr(dispatcher, "dispatch", lambda repo, wf, job=None: calls.append((wf, job)) or True)
    monkeypatch.setattr(dispatcher, "recent_runs", lambda repo: [])
    # simulate the minute loop body for 12:17 and 12:50 / 13:50
    for t in (datetime(2026, 11, 25, 12, 17), datetime(2026, 11, 25, 12, 50), datetime(2026, 11, 25, 13, 50)):
        if t.minute in dispatcher.WATCHDOG_MINUTES and (t.minute == 17 or t.hour % 3 == 0):
            dispatcher.dispatch("r", "watchdog.yml")
    assert calls == [("watchdog.yml", None), ("watchdog.yml", None)]
    src = (ROOT / "backend/fil/ops/dispatcher.py").read_text()
    assert "return 0 if ok else 1" in src


def test_unresolved_round_complete_is_labelled_not_stale(db):
    from datetime import timedelta as td

    from fil import health
    from fil.db import Competition, Fixture, Team, session_scope
    from fil.timeutil import utcnow
    from sqlalchemy import select

    with session_scope() as s:
        comp = s.scalars(select(Competition)).first()
        ts = [Team(name=f"T{i}", country=comp.country) for i in range(10)]
        s.add_all(ts); s.flush()
        ko = utcnow() - td(days=5)
        orphan = Fixture(competition_id=comp.id, home_team_id=ts[0].id, away_team_id=ts[1].id, kickoff_utc=ko,
                         match_date=str(ko.date()), status="scheduled", first_seen_source="test")
        s.add(orphan)
        for i in range(2, 10, 2):  # the rest of the round has results
            s.add(Fixture(competition_id=comp.id, home_team_id=ts[i].id, away_team_id=ts[i + 1].id, kickoff_utc=ko,
                          match_date=str(ko.date()), status="finished", home_goals=1, away_goals=0, first_seen_source="test"))
        s.flush()
        oid = orphan.id
    r = health.compute(include_db_check=False)["components"]["results"]
    assert r["unresolved_round_complete"] == [oid] and r["overdue"] == 0 and r["state"] == "HEALTHY"
    with session_scope() as s:  # the stored status is never changed by health
        assert s.get(Fixture, oid).status == "scheduled"


def test_identity_report_lists_ambiguous_aliases(db, tmp_path):
    from fil.db import Team, TeamAlias, session_scope
    from fil.identity import dry_run

    with session_scope() as s:
        a, b = Team(name="Paris FC", country="France"), Team(name="Paris SG", country="France")
        s.add_all([a, b]); s.flush()
        s.add_all([TeamAlias(alias_norm="paris", source="thesportsdb", team_id=a.id),
                   TeamAlias(alias_norm="paris", source="thesportsdb", team_id=b.id)])
    r = dry_run(tmp_path / "r.md")
    assert any(x["alias"] == "paris" and len(x["team_ids"]) == 2 for x in r["ambiguous_aliases"])


def test_persist_retries_survive_transient_upload_errors():
    block = WORKFLOW.split("name: Persist database (guarded)")[1].split("- uses:")[0]
    assert "for i in 1 2 3 4 5" in block  # 3 consecutive GitHub 5xx on 2026-11-25 15:44 exhausted 3 attempts


def test_successful_manual_recovery_ends_failure_streak():
    fail = _api_run(1, NOW - timedelta(hours=3), "Autopilot · results,fixtures_odds", event="workflow_dispatch",
                    actor=watchdog.BOT, conclusion="failure")
    recover = _api_run(2, NOW - timedelta(minutes=50), "Autopilot · results,fixtures_odds", event="workflow_dispatch",
                       actor="xexino")
    rep = watchdog.evaluate([recover, fail], NOW, first_seen=NOW - timedelta(hours=4))
    assert not any(f["code"] == "critical_failure" for f in rep["findings"])
    rep = watchdog.evaluate([fail], NOW, first_seen=NOW - timedelta(hours=4))
    assert any(f["code"] == "critical_failure" for f in rep["findings"])
    # a failing manual run still never raises the incident
    bad_manual = _api_run(3, NOW - timedelta(minutes=10), "Autopilot · daily", event="workflow_dispatch", conclusion="failure")
    rep = watchdog.evaluate([bad_manual, recover], NOW, first_seen=NOW - timedelta(hours=4))
    assert not any(f["code"] == "critical_failure" for f in rep["findings"])


def test_watchdog_notification_retries_and_catch_up_first():
    wd = (ROOT / ".github/workflows/watchdog.yml").read_text()
    act = wd.split("name: Act on decision")[1]
    assert act.index("catch_up // [])[]") < act.index('repos/$GH_REPO/issues" -f title')  # self-healing first
    assert "open_with_title" in act and "fp_posted" in act and "is_closed" in act  # idempotent retries
    assert 'cu_fail=1' in act and '[ "$cu_fail" = 0 ] || exit 1' in act          # catch-up failures are loud
    assert "set -euo pipefail" not in act


def test_only_manual_results_work_ends_failure_streak():
    fail = _api_run(1, NOW - timedelta(hours=3), "Autopilot · results,fixtures_odds", event="workflow_dispatch",
                    actor=watchdog.BOT, conclusion="failure")
    for title in ("Autopilot · engine_b", "Autopilot · backup", "Autopilot · weekly", "Autopilot · live"):
        other = _api_run(2, NOW - timedelta(minutes=30), title, event="workflow_dispatch", actor="xexino")
        rep = watchdog.evaluate([other, fail], NOW, first_seen=NOW - timedelta(hours=4))
        assert any(f["code"] == "critical_failure" for f in rep["findings"]), title


def test_thesportsdb_results_cache_stays_fresh():
    from fil.providers.others import TheSportsDB

    assert TheSportsDB.ENDPOINT_TTL["eventspastleague.php"] <= int(2.5 * 3600) < 3 * 3600
    assert TheSportsDB.ENDPOINT_TTL["eventsnextleague.php"] > 3 * 3600


def test_postponed_fixtures_get_their_own_phase():
    src = (ROOT / "backend/fil/api_b.py").read_text()
    assert '"postponed" if f.status in ("postponed", "cancelled", "abandoned")' in src


# --------------------------------------------------------------------------- owner decision: €500 bankroll, €10 stakes
def test_bankroll_top_up_keeps_history_and_chain(db):
    from sqlalchemy import select

    from fil.betting import capital, ensure_bankroll
    from fil.config import settings
    from fil.db import BankrollTransaction, session_scope
    from fil.integrity import check_database

    assert settings.risk.stake == 10.0 and settings.risk.max_stake == 10.0 and settings.risk.initial_bankroll == 500.0
    with session_scope() as s:  # an existing €100 ledger with one €1 stake (history before the change)
        s.add(BankrollTransaction(tx_type="initial", amount=100.0, balance_after=100.0, note="old"))
        s.flush()
    with session_scope() as s:
        ensure_bankroll(s)
        ensure_bankroll(s)  # idempotent
    with session_scope() as s:
        txs = s.scalars(select(BankrollTransaction).order_by(BankrollTransaction.id)).all()
        assert [(t.tx_type, t.amount, t.balance_after) for t in txs] == [("initial", 100.0, 100.0), ("top_up", 400.0, 500.0)]
        assert capital(s) == 500.0
    assert check_database()["ok"]


def test_engine_b_stake_scaled():
    from fil.engine_b.betting import RISK

    assert RISK.stake == 10.0 and RISK.initial_bankroll == 500.0 and RISK.max_daily_exposure == 100.0


# ------------------------------------------------------------------ the "Act on decision" step, executed for real
# Council cycle 2026-11-26 00:50: every watchdog run since 2026-11-25 19:11 failed because, under `pipefail`, the
# fingerprint grep exits 1 when there is no incident body (action "none"). A text check of the step could not see
# that, so the step is now run with GitHub's own shell (`bash -e`) against a fake `gh`.
import os
import shutil
import subprocess

FAKE_GH = r"""#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
case "$*" in
  *"--jq [.[] | select"*) echo 0 ;;      # no open incident with this title yet
  *"--jq .state"*) echo open ;;
  *"comments?per_page"*) : ;;             # fingerprint not posted yet
  *) echo '{}' ;;
esac
"""


def _act_step() -> str:
    """The `run: |` block of the step (YAML block scalar: every line indented deeper than `run:`)."""
    lines = (ROOT / ".github/workflows/watchdog.yml").read_text().split("name: Act on decision", 1)[1].splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "run: |")
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = []
    for ln in lines[start + 1:]:
        if ln.strip() and len(ln) - len(ln.lstrip()) <= indent:
            break
        body.append(ln)
    pad = min(len(ln) - len(ln.lstrip()) for ln in body if ln.strip())
    return "\n".join(ln[pad:] for ln in body) + "\n"


def _run_act(tmp_path, decision: dict) -> tuple[int, list[str], str]:
    (tmp_path / "bin").mkdir()
    gh = tmp_path / "bin" / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    (tmp_path / "decision.json").write_text(json.dumps(decision))
    (tmp_path / "act.sh").write_text(_act_step())
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "GH_REPO": "o/r",
           "GH_LOG": str(tmp_path / "gh.log"), "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md")}
    p = subprocess.run(["bash", "-e", str(tmp_path / "act.sh")], cwd=tmp_path, env=env, capture_output=True, text=True,
                       timeout=60)
    log = (tmp_path / "gh.log").read_text().splitlines() if (tmp_path / "gh.log").exists() else []
    return p.returncode, log, p.stdout + p.stderr


needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")


@needs_jq
def test_act_step_succeeds_when_nothing_to_report(tmp_path):
    rc, log, out = _run_act(tmp_path, {"status": "DEGRADED", "catch_up": [],
                                       "decision": {"action": "none", "reason": "no incident"}})
    assert rc == 0, out
    assert "no notification needed" in out and log == []


@needs_jq
def test_act_step_missing_catch_up_list_is_harmless(tmp_path):
    rc, _, out = _run_act(tmp_path, {"status": "HEALTHY", "decision": {"action": "none", "reason": "ok"}})
    assert rc == 0, out


@needs_jq
def test_act_step_catch_up_then_create_incident(tmp_path):
    body = "Autopilot failed\n<!-- watchdog-fingerprint: abc123 -->"
    rc, log, out = _run_act(tmp_path, {"status": "FAILED",
                                       "catch_up": [{"workflow": "autopilot.yml", "job": "results,fixtures_odds",
                                                     "reason": "missed slot"}],
                                       "decision": {"action": "create", "title": "Autopilot incident", "body": body}})
    assert rc == 0, out
    runs = [i for i, line in enumerate(log) if line.startswith("workflow run autopilot.yml")]
    creates = [i for i, line in enumerate(log) if line.startswith("api repos/o/r/issues -f title=")]
    assert runs and creates and runs[0] < creates[0]          # self-healing before the notification
    assert len(creates) == 1                                  # exactly one issue
    assert "Autopilot is FAILED" in out                       # loud in the log


@needs_jq
def test_act_step_close_comments_then_closes(tmp_path):
    rc, log, out = _run_act(tmp_path, {"status": "HEALTHY", "catch_up": [],
                                       "decision": {"action": "close", "issue": 21,
                                                    "body": "recovered <!-- watchdog-fingerprint: def456 -->"}})
    assert rc == 0, out
    assert any(line.startswith("api repos/o/r/issues/21/comments -F body=") for line in log)
    assert any(line.startswith("api -X PATCH repos/o/r/issues/21") for line in log)


# ------------------------------------------------------------------ overdue-results fallback (TheSportsDB by day)
def _ev(home="Cremonese", away="Avellino", hg="0", ag="1", status="FT", league="4394", day="2026-11-25", **kw):
    return {"idLeague": league, "strStatus": status, "strHomeTeam": home, "strAwayTeam": away,
            "intHomeScore": hg, "intAwayScore": ag, "dateEvent": day, **kw}


FX = [dict(id=7, date="2026-11-25", home_names={"cremonese"}, away_names={"avellino"})]


def test_overdue_matching_accepts_only_explicit_full_time_of_this_league():
    from fil.collect import overdue_events_to_results as m

    assert m([_ev()], "4394", FX) == [(7, 0, 1)]
    assert m([_ev(league="4328")], "4394", FX) == []            # event from another league
    for st in ("HT", "2H", "1H", "Live", "AET", "PST", "SUSP", "", "Not Started"):
        assert m([_ev(status=st)], "4394", FX) == [], st        # never a stuck live score or a postponement
    assert m([_ev(strPostponed="yes")], "4394", FX) == []
    assert m([_ev(hg=None)], "4394", FX) == []
    assert m([_ev(home="Cremonese FC")], "4394", FX) == [(7, 0, 1)]  # only normalisation (FC dropped)
    assert m([_ev(home="Cremona")], "4394", FX) == []           # no fuzzy matching
    assert m([_ev(day="2026-11-24")], "4394", FX) == []         # same date only
    two = FX + [dict(id=8, date="2026-11-25", home_names={"cremonese"}, away_names={"avellino"})]
    assert m([_ev()], "4394", two) == []                        # ambiguous: no guess


def _seed_overdue(ko):
    from fil.db import Competition, Fixture, Team, session_scope
    from sqlalchemy import select

    with session_scope() as s:
        comp = s.scalar(select(Competition).where(Competition.code == "ITA2"))
        h, a = Team(name="Cremonese", country="Italy"), Team(name="Avellino", country="Italy")
        s.add_all([h, a]); s.flush()
        f = Fixture(competition_id=comp.id, season="2026", home_team_id=h.id, away_team_id=a.id, kickoff_utc=ko,
                    match_date=ko.strftime("%Y-%m-%d"), neutral=False, status="scheduled",
                    first_seen_source="football_data_uk", external_ids={})
        s.add(f); s.flush()
        return f.id


def _counts():
    from fil.db import Fixture, Team, TeamAlias, session_scope
    from sqlalchemy import func, select

    with session_scope() as s:
        return tuple(s.scalar(select(func.count(t.id))) for t in (Fixture, Team, TeamAlias))


def test_overdue_fallback_records_result_without_creating_anything(db, monkeypatch):
    from fil import collect
    from fil.db import Fixture, session_scope
    from fil.timeutil import utcnow

    ko = utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(hours=6)
    fid = _seed_overdue(ko)
    before = _counts()
    calls = []

    def fake_events(endpoint, params, ttl=None):
        calls.append((endpoint, params))
        return ([_ev(day=ko.strftime("%Y-%m-%d")),
                 _ev(home="Pisa", away="Modena", hg="1", ag="1", day=ko.strftime("%Y-%m-%d"))],  # unknown match
                "u", utcnow())

    tsdb = collect.provider("thesportsdb")
    monkeypatch.setattr(tsdb, "_events", fake_events)
    monkeypatch.setattr(collect, "provider", lambda k: tsdb)
    out = collect.collect_overdue_results()
    assert out["asked"] == 1 and out["results_found"] == 1
    assert calls == [("eventsday.php", {"d": ko.strftime("%Y-%m-%d"), "l": "4394"})]
    assert _counts() == before                                   # no fixture, team or alias created
    with session_scope() as s:
        f = s.get(Fixture, fid)
        assert (f.status, f.home_goals, f.away_goals) == ("finished", 0, 1)
        assert f.result_source == "thesportsdb"                  # visibly single-source
    # a second run asks nothing new for this fixture (it is no longer overdue)
    assert collect.collect_overdue_results()["pairs"] == 0


def test_overdue_fallback_stops_at_first_rate_limit(db, monkeypatch):
    from fil import collect
    from fil.providers.base import ProviderError
    from fil.timeutil import utcnow

    base = utcnow().replace(minute=0, second=0, microsecond=0)
    for d in (1, 2, 3):
        from fil.db import Competition, Fixture, Team, session_scope
        from sqlalchemy import select

        with session_scope() as s:
            comp = s.scalar(select(Competition).where(Competition.code == "ENG3"))
            h, a = Team(name=f"H{d}", country="England"), Team(name=f"A{d}", country="England")
            s.add_all([h, a]); s.flush()
            ko = base - timedelta(days=d)
            s.add(Fixture(competition_id=comp.id, season="2026", home_team_id=h.id, away_team_id=a.id, kickoff_utc=ko,
                          match_date=ko.strftime("%Y-%m-%d"), neutral=False, status="scheduled",
                          first_seen_source="football_data_uk", external_ids={}))
    calls = []

    def limited(endpoint, params, ttl=None):
        calls.append(params["d"])
        raise ProviderError("rate limited (429) at x")

    tsdb = collect.provider("thesportsdb")
    monkeypatch.setattr(tsdb, "_events", limited)
    monkeypatch.setattr(collect, "provider", lambda k: tsdb)
    out = collect.collect_overdue_results()
    assert len(calls) == 1 and out["asked"] == 0 and out["errors"]
    assert calls[0] == (base - timedelta(days=1)).strftime("%Y-%m-%d")   # newest day first


def test_overdue_fallback_is_not_a_fixture_source():
    from fil.catalog import BY_CODE
    from fil.collect import OVERDUE_TSDB_LEAGUE

    for code in OVERDUE_TSDB_LEAGUE:  # keeps eventsnext/eventspast (fixture discovery) off for these leagues
        assert "tsdb" not in BY_CODE[code]["sources"], code
    from fil.jobs import _steps_results

    assert [n for n, *_ in _steps_results()][:2] == ["results", "overdue_results"]  # before settle


# ------------------------------------------------------------------ fallback v2 (cycle 2026-11-26 06:50)
def test_names_match_prefix_suffix_and_abbreviations():
    from fil.collect import names_match as m

    assert m("bradford city", "bradford") and m("leicester city", "leicester") and m("hellas verona", "verona")
    assert m("doncaster rovers", "doncaster") and m("huddersfield town", "huddersfield")
    assert m("sheffield wednesday", "sheffield weds") and m("bristol rovers", "bristol rvs")
    assert not m("sheffield utd", "sheffield wednesday")       # same first word, different club
    assert not m("bristol city", "bristol rovers")
    assert not m("ac", "ac milan")                              # < 4 letters never counts
    assert not m("", "bradford")


def test_overdue_matching_full_names_and_reverse_uniqueness():
    from fil.collect import overdue_events_to_results as m

    fx = [dict(id=9, date="2026-11-24", home_names={"bradford"}, away_names={"barnsley"})]
    ev = _ev(home="Bradford City", away="Barnsley", hg="3", ag="0", league="4396", day="2026-11-24")
    assert m([ev], "4396", fx) == [(9, 3, 0)]
    dup = dict(ev, intHomeScore="2")                            # a second event claiming the same fixture
    assert m([ev, dup], "4396", fx) == []


def test_overdue_fallback_searches_open_bet_first(db, monkeypatch):
    import sqlite3

    from fil import collect
    from fil.db import Competition, Fixture, Team, session_scope
    from fil.timeutil import utcnow
    from sqlalchemy import select

    ko = utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(hours=5)
    ids = {}
    with session_scope() as s:
        comp = s.scalar(select(Competition).where(Competition.code == "ENG3"))
        for key, hn, an, k in (("other", "Bradford", "Barnsley", ko - timedelta(days=1)), ("bet", "Doncaster", "Huddersfield", ko)):
            h, a = Team(name=hn, country="England"), Team(name=an, country="England")
            s.add_all([h, a]); s.flush()
            f = Fixture(competition_id=comp.id, season="2026", home_team_id=h.id, away_team_id=a.id, kickoff_utc=k,
                        match_date=k.strftime("%Y-%m-%d"), neutral=False, status="scheduled",
                        first_seen_source="football_data_uk", external_ids={})
            s.add(f); s.flush()
            ids[key] = f.id
    con = sqlite3.connect(db)  # a pending bet row (foreign keys off: the full prediction pipeline is not needed)
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("INSERT INTO virtual_bets (prediction_id, value_assessment_id, fixture_id, model_version_id, market, "
                "selection, price, bookmaker, stake, potential_return, model_prob, ev, kickoff_utc, status, created_at) "
                "VALUES (1, 1, ?, 1, '1X2', 'home', 4.5, 'b', 1, 4.5, 0.27, 0.2, ?, 'pending', ?)",
                (ids["bet"], ko.isoformat(sep=" "), (ko - timedelta(hours=20)).isoformat(sep=" ")))
    con.commit(); con.close()
    calls = []
    day = ko.strftime("%Y-%m-%d")

    def fake(endpoint, params, ttl=None):
        calls.append((endpoint, params.get("e")))
        tsdb.last_from_cache = False
        if endpoint == "searchevents.php" and params["e"] == "Doncaster":
            assert params["d"] == day
            return ([_ev(home="Doncaster Rovers", away="Huddersfield Town", hg="2", ag="1", league="4396", day=day)],
                    "u", utcnow())
        return ([], "u", utcnow())

    tsdb = collect.provider("thesportsdb")
    monkeypatch.setattr(tsdb, "_events", fake)
    monkeypatch.setattr(collect, "provider", lambda k: tsdb)
    out = collect.collect_overdue_results()
    assert calls[0] == ("searchevents.php", "Doncaster")              # the open bet is asked before anything else
    assert ("eventsday.php", None) in calls and ("searchevents.php", "Bradford") in calls
    assert out["results_found"] == 1 and out["still_overdue"] == 1
    with session_scope() as s:
        f = s.get(Fixture, ids["bet"])
        assert (f.status, f.home_goals, f.away_goals) == ("finished", 2, 1)


def test_overdue_fallback_budget_ignores_cached_answers(db, monkeypatch):
    from fil import collect
    from fil.timeutil import utcnow

    base = utcnow().replace(minute=0, second=0, microsecond=0)
    for d in range(1, 6):
        from fil.db import Competition, Fixture, Team, session_scope
        from sqlalchemy import select

        with session_scope() as s:
            comp = s.scalar(select(Competition).where(Competition.code == "ITA2"))
            h, a = Team(name=f"Casa{d}", country="Italy"), Team(name=f"Ospite{d}", country="Italy")
            s.add_all([h, a]); s.flush()
            k = base - timedelta(days=d)
            s.add(Fixture(competition_id=comp.id, season="2026", home_team_id=h.id, away_team_id=a.id, kickoff_utc=k,
                          match_date=k.strftime("%Y-%m-%d"), neutral=False, status="scheduled",
                          first_seen_source="football_data_uk", external_ids={}))
    net = []

    def fake(endpoint, params, ttl=None):
        cached = endpoint == "eventsday.php"          # every day list is a fresh cached answer
        tsdb.last_from_cache = cached
        if not cached:
            net.append(endpoint)
        return ([], "u", utcnow())

    tsdb = collect.provider("thesportsdb")
    monkeypatch.setattr(tsdb, "_events", fake)
    monkeypatch.setattr(collect, "provider", lambda k: tsdb)
    out = collect.collect_overdue_results()
    assert out["cached"] == 5 and out["asked"] == 5 == len(net)    # the searches still ran
    assert set(net) == {"searchevents.php"}
