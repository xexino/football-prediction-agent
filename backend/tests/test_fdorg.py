"""football-data.org integration tests (mocked HTTP; never uses a real token)."""
import gzip
import json
import logging
from datetime import timedelta

import pytest
from sqlalchemy import select

from fil.config import settings
from fil.db import DataSource, Fixture, JobRun, ResultObservation, StandingSnapshot, SystemLog, session_scope
from fil.timeutil import utcnow

FAKE = "fake-token-0123456789abcdef-SECRET"


class Resp:
    def __init__(self, code, body=None, headers=None, text=None):
        self.status_code = code
        self._body = body
        self.text = text if text is not None else json.dumps(body)
        self.headers = {"x-requests-available-minute": "9", "x-requestcounter-reset": "50", **(headers or {})}

    def json(self):
        if self._body is None:
            return json.loads(self.text)
        return self._body


@pytest.fixture()
def token(monkeypatch):
    monkeypatch.setattr(settings, "football_data_org_key", FAKE)
    monkeypatch.setenv("FOOTBALL_DATA_ORG_KEY", FAKE)
    yield FAKE


def fake_http(monkeypatch, responses, seen):
    import fil.providers.football_data_org as mod

    class Client:
        def __init__(self, *a, headers=None, **k):
            self.h = headers or {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            seen.append({"url": url, "headers": dict(self.h)})
            r = responses.pop(0) if responses else Resp(200, {"matches": []})
            if isinstance(r, Exception):
                raise r
            return r

    monkeypatch.setattr(mod.httpx, "Client", Client)


def provider(tmp_path):
    from fil.providers.football_data_org import FootballDataOrg

    p = FootballDataOrg()
    p.cache_dir = tmp_path
    p.sleeps = []
    p.sleep = lambda s: p.sleeps.append(s)
    p.min_interval_s = 0
    return p


def match(mid, home, away, days, status="SCHEDULED", ft=(None, None), comp="PL", duration="REGULAR", reg=None):
    score = {"duration": duration, "fullTime": {"home": ft[0], "away": ft[1]}, "halfTime": {"home": None, "away": None}}
    if reg:
        score["regularTime"] = {"home": reg[0], "away": reg[1]}
    return {"id": mid, "utcDate": (utcnow() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"), "status": status,
            "competition": {"code": comp}, "season": {"startDate": "2026-08-15"},
            "homeTeam": {"name": home + " FC", "shortName": home, "tla": home[:3].upper()},
            "awayTeam": {"name": away + " FC", "shortName": away, "tla": away[:3].upper()}, "score": score}


# ------------------------------------------------------------------ configuration & authentication
def test_missing_env_var_is_clear_config_error(db, monkeypatch, tmp_path):
    from fil import collect
    from fil.providers.base import NotConfigured

    monkeypatch.setattr(settings, "football_data_org_key", "")
    p = provider(tmp_path)
    assert not p.configured
    with pytest.raises(NotConfigured, match="FOOTBALL_DATA_ORG_KEY is not set"):
        p.request("/competitions")
    assert collect.collect_fdorg("quick") == {"skipped": "not configured (FOOTBALL_DATA_ORG_KEY not set)"}
    collect.register_all()
    with session_scope() as s:
        assert s.scalars(select(DataSource).where(DataSource.key == "football_data_org")).one().status == "not_configured"


def test_auth_success_sends_header_not_url(db, token, monkeypatch, tmp_path):
    seen = []
    fake_http(monkeypatch, [Resp(200, {"competitions": [{"code": "PL", "name": "Premier League", "plan": "TIER_ONE"}]})], seen)
    p = provider(tmp_path)
    comps = p.competitions()
    assert comps[0]["code"] == "PL"
    assert seen[0]["headers"]["X-Auth-Token"] == FAKE
    assert FAKE not in seen[0]["url"]
    assert all(FAKE.encode() not in f.read_bytes() and FAKE not in f.name for f in tmp_path.iterdir() if f.is_file())


def test_invalid_token_is_auth_error_without_leak(db, token, monkeypatch, tmp_path):
    from fil import collect
    from fil.providers.football_data_org import AuthError

    fake_http(monkeypatch, [Resp(400, {"message": "Your API token is invalid.", "errorCode": 400})], [])
    p = provider(tmp_path)
    with pytest.raises(AuthError) as ei:
        p.request("/matches")
    assert FAKE not in str(ei.value) and "FOOTBALL_DATA_ORG_KEY" in str(ei.value)
    fake_http(monkeypatch, [Resp(400, {"message": "Your API token is invalid.", "errorCode": 400})], [])
    out = collect.collect_fdorg("quick")
    assert out["errors"] and FAKE not in json.dumps(out)
    with session_scope() as s:
        ds = s.scalars(select(DataSource).where(DataSource.key == "football_data_org")).one()
        assert ds.status == "error" and FAKE not in (ds.last_error or "")


def test_restricted_endpoint_recorded_as_plan_limit(db, token, monkeypatch, tmp_path):
    from fil.providers.football_data_org import Restricted

    fake_http(monkeypatch, [Resp(403, {"message": "The resource you are looking for is restricted", "errorCode": 403})], [])
    p = provider(tmp_path)
    with pytest.raises(Restricted):
        p.request("/competitions/PL/matches", {"season": 2020})
    assert "/competitions/PL/matches" in p.quota()["restricted"]


# ------------------------------------------------------------------ rate limiting
def test_429_waits_for_counter_reset_then_succeeds(db, token, monkeypatch, tmp_path):
    seen = []
    fake_http(monkeypatch, [Resp(429, {"message": "Too many requests"}, {"X-RequestCounter-Reset": "17", "x-requests-available-minute": "0"}),
                            Resp(200, {"matches": []})], seen)
    p = provider(tmp_path)
    body, _, _ = p.request("/matches", ttl=0)
    assert body == {"matches": []} and len(seen) == 2
    assert any(s >= 17 for s in p.sleeps)


def test_adaptive_throttle_uses_rate_headers(db, token, monkeypatch, tmp_path):
    fake_http(monkeypatch, [Resp(200, {"a": 1}, {"x-requests-available-minute": "1", "x-requestcounter-reset": "33"}),
                            Resp(200, {"b": 2})], [])
    p = provider(tmp_path)
    p.request("/x", ttl=0)
    assert p.available == 1 and p.reset_s == 33
    p.request("/y", ttl=0)
    assert any(abs(s - 34) < 0.01 for s in p.sleeps)  # waited reset+1 before spending the last request


def test_throttle_respects_10_per_minute(db, token, monkeypatch, tmp_path):
    from fil.providers.football_data_org import FootballDataOrg

    assert FootballDataOrg.min_interval_s >= 6.0


# ------------------------------------------------------------------ downtime & malformed
def test_downtime_retries_then_stale_cache(db, token, monkeypatch, tmp_path):
    import httpx

    p = provider(tmp_path)
    fake_http(monkeypatch, [Resp(200, {"matches": [1]})], [])
    p.request("/matches", ttl=0)
    fake_http(monkeypatch, [httpx.ConnectError("down")] * 2 + [Resp(503, {"message": "x"})] * 2, [])
    body, _, ts = p.request("/matches", ttl=0)
    assert body == {"matches": [1]}


def test_downtime_without_cache_raises_provider_error(db, token, monkeypatch, tmp_path):
    import httpx

    from fil.providers.base import ProviderError

    fake_http(monkeypatch, [httpx.ReadTimeout("t")] * 4, [])
    with pytest.raises(ProviderError) as ei:
        provider(tmp_path).request("/matches", ttl=0)
    assert FAKE not in str(ei.value)


def test_malformed_json_raises(db, token, monkeypatch, tmp_path):
    from fil.providers.base import ProviderError

    fake_http(monkeypatch, [Resp(200, text="<html>gateway</html>")], [])
    with pytest.raises(ProviderError, match="malformed"):
        provider(tmp_path).request("/matches", ttl=0)
    fake_http(monkeypatch, [Resp(200, ["not", "an", "object"])], [])
    with pytest.raises(ProviderError, match="malformed"):
        provider(tmp_path).request("/matches2", ttl=0)


def test_malformed_match_entries_skipped(db, token, monkeypatch, tmp_path):
    bad = [{"id": 1}, {"id": 2, "utcDate": "not-a-date", "homeTeam": {"name": "A"}, "awayTeam": {"name": "B"}},
           match(3, "Alpha", "Beta", 2)]
    fake_http(monkeypatch, [Resp(200, {"matches": bad})], [])
    recs = provider(tmp_path).matches()
    assert [r.external_id for r in recs] == ["3"]


# ------------------------------------------------------------------ duplicates & integration
def test_no_duplicate_fixtures_across_providers_and_reruns(db, token, monkeypatch, tmp_path):
    from fil import collect
    from fil.ingest import ingest_records
    from tests.test_system import rec

    ko = utcnow() + timedelta(days=2)
    for i in range(10):  # primary source owns the league
        ingest_records([rec(f"Club {i}", f"Club {i + 10}", ko + timedelta(days=7 * i))], "football_data_uk")
    m = match(77, "Club 0", "Club 10", 2)
    m["utcDate"] = ko.strftime("%Y-%m-%dT%H:%M:%SZ")
    unknown = match(78, "Paris", "Nowhere United", 3)  # names the primary source does not know
    for _ in range(2):  # re-running the sync must not duplicate anything
        fake_http(monkeypatch, [Resp(200, {"matches": [m, unknown]})], [])
        monkeypatch.setattr("fil.providers.football_data_org.FootballDataOrg.cache_ttl_s", 0)
        collect.collect_fdorg("quick")
    with session_scope() as s:
        fx = s.scalars(select(Fixture)).all()
        assert len(fx) == 10  # no duplicate, and no invented teams/fixtures in a primary-owned league
        linked = [f for f in fx if (f.external_ids or {}).get("football_data_org") == "77"]
        assert len(linked) == 1


def test_extra_time_uses_90_minute_score_without_conflict(db, token, monkeypatch, tmp_path):
    from fil.ingest import ingest_records
    from tests.test_system import rec

    ko = utcnow() - timedelta(days=3)
    m = match(90, "England", "Slovakia", -3, status="FINISHED", ft=(2, 1), comp="EC", duration="EXTRA_TIME", reg=(1, 1))
    ingest_records([rec("England", "Slovakia", ko, status="finished", hg=2, ag=1, comp="UNL")], "intl_results")
    fake_http(monkeypatch, [Resp(200, {"matches": [m]})], [])
    recs = provider(tmp_path).matches()
    assert recs[0].status == "finished_aet" and (recs[0].home_goals, recs[0].away_goals) == (1, 1)
    ingest_records(recs, "football_data_org")
    with session_scope() as s:
        f = s.scalars(select(Fixture)).one()
        assert (f.home_goals, f.away_goals, f.result_conflict) == (1, 1, False)
        assert "extra time" in f.result_source


def test_in_play_delayed_scores_not_stored_as_results(db, token, monkeypatch, tmp_path):
    from fil.ingest import ingest_records

    m = match(5, "Alpha", "Beta", 0, status="IN_PLAY", ft=(1, 0))
    fake_http(monkeypatch, [Resp(200, {"matches": [m]})], [])
    p = provider(tmp_path)
    recs = p.matches()
    assert p.in_play_seen == 1 and recs[0].status == "scheduled" and recs[0].home_goals is None
    ingest_records(recs, "football_data_org")
    with session_scope() as s:
        assert s.scalars(select(ResultObservation)).all() == []


def test_standings_stored_append_only_per_day(db, token, monkeypatch, tmp_path):
    from fil import collect
    from fil.ingest import ingest_records
    from tests.test_system import rec

    ingest_records([rec("Alpha", "Beta")], "football_data_uk")
    table = {"season": {"startDate": "2026-08-15"}, "standings": [{"type": "TOTAL", "table": [
        {"position": 1, "team": {"name": "Alpha FC", "shortName": "Alpha"}, "playedGames": 12, "won": 9, "draw": 2,
         "lost": 1, "goalsFor": 25, "goalsAgainst": 8, "points": 29, "form": "W,W,D"},
        {"position": 2, "team": {"name": "Beta FC", "shortName": "Beta"}, "playedGames": 12, "won": 8, "draw": 2,
         "lost": 2, "goalsFor": 20, "goalsAgainst": 10, "points": 26, "form": None}]},
        {"type": "HOME", "table": []}]}
    rows, season, url, ts = None, None, None, None
    fake_http(monkeypatch, [Resp(200, table)], [])
    rows, season, url, ts = provider(tmp_path).standings("PL")
    assert season == "2026" and len(rows) == 2
    rows[0]["group"] = "Matchday"  # league tables carry a non-group label: must not be appended to names
    assert collect._store_standings("PL", rows, season, ts) == 2
    assert collect._store_standings("PL", rows, season, ts) == 2  # same day re-run replaces, never duplicates
    with session_scope() as s:
        st = s.scalars(select(StandingSnapshot).order_by(StandingSnapshot.position)).all()
        assert [x.team_id is not None for x in st] == [True, True]
        assert [x.team_name for x in st] == ["Alpha", "Beta"]


# ------------------------------------------------------------------ secret leakage
def test_log_redaction_covers_all_loggers(token, caplog):
    caplog.set_level(logging.DEBUG)
    logging.getLogger("httpx").info("GET https://api.football-data.org/v4/matches headers={'X-Auth-Token': '%s'}", FAKE)
    logging.getLogger("fil.anything").error("failure with token %s inside", FAKE)
    logging.getLogger("x").warning("Authorization: Bearer abcdef123456 and apiKey=zzzz9999")
    text = caplog.text
    assert FAKE not in text and "abcdef123456" not in text and "zzzz9999" not in text
    assert "***" in text


def test_secret_never_reaches_db_logs_jobs_exports_or_backups(db, token, monkeypatch, tmp_path):
    from fil import cli, jobs
    from fil.backup import backup
    from fil.db import log

    log("ERROR", "test", f"provider said token={FAKE} is bad; header X-Auth-Token: {FAKE}")
    monkeypatch.setitem(jobs.JOBS, "leaky", lambda: [("step", lambda: (_ for _ in ()).throw(RuntimeError(f"boom {FAKE}")), False),
                                                     ("ok", lambda: {"echo": FAKE}, False)])
    jobs.run_job("leaky")
    with session_scope() as s:
        assert all(FAKE not in (r.message or "") for r in s.scalars(select(SystemLog)))
        run = s.scalars(select(JobRun).where(JobRun.job == "leaky")).one()
        assert FAKE not in (run.error or "") and FAKE not in json.dumps(run.summary)
    site = tmp_path / "site"
    cli.export_static(site)
    for f in site.rglob("*"):
        if f.is_file():
            assert FAKE.encode() not in f.read_bytes(), f
    bk = backup(tmp_path / "bk", verify=True)
    with gzip.open(bk, "rb") as g:
        assert FAKE.encode() not in g.read()


def test_frontend_bundle_has_no_secret_references():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    for f in root.rglob("*.ts*"):
        t = f.read_text()
        assert "FOOTBALL_DATA_ORG_KEY" not in t and "X-Auth-Token" not in t


def test_workflow_passes_secret_only_to_run_step():
    """The secret must be scoped to the job-running step, never job-wide (frontend build, export, summary)."""
    from pathlib import Path

    lines = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "autopilot.yml").read_text().splitlines()
    uses = [i for i, l in enumerate(lines) if "secrets.FOOTBALL_DATA_ORG_KEY" in l]
    assert len(uses) == 1
    step = next(l for l in reversed(lines[:uses[0]]) if l.strip().startswith("- name:"))
    assert step.strip() == "- name: Run"
    ci = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml").read_text()
    assert "secrets." not in ci


def test_alias_from_other_league_does_not_capture_namesake(db):
    from fil.db import Team
    from fil.ingest import ingest_records
    from fil.teamnames import TeamResolver
    from tests.test_system import rec

    ingest_records([rec("Guimaraes", "Benfica", comp="POR1")], "football_data_uk")
    ingest_records([rec("Vitoria", "Bahia", comp="BRA1")], "football_data_uk")
    with session_scope() as s:
        gui = s.scalars(select(Team).where(Team.name == "Guimaraes")).one().id
        bra = s.scalars(select(Team).where(Team.name == "Vitoria")).one().id
        bahia = s.scalars(select(Team).where(Team.name == "Bahia")).one().id
        r = TeamResolver(s)
        r._add_alias("vitoria", "football_data_org", gui, 0.85)  # learnt in Portugal
        tid, _ = r.resolve("Vitoria", "football_data_org", "", [bra, bahia], create=False)
        assert tid == bra


def test_export_process_without_key_keeps_recent_provider_status(db, token):
    from fil.collect import provider

    p = provider("football_data_org")
    p.mark_success(records=5, requests=1)
    settings.football_data_org_key = ""  # e.g. the dashboard-export step, which never receives the secret
    provider("football_data_org")
    with session_scope() as s:
        ds = s.scalars(select(DataSource).where(DataSource.key == "football_data_org")).one()
        assert ds.configured and ds.status == "ok"
