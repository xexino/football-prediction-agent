"""Reliability, integrity, health and full-lifecycle tests."""
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from fil.db import BankrollTransaction, DataSource, Fixture, JobRun, Prediction, VirtualBet, session_scope
from fil.ingest import ingest_records, validate
from fil.timeutil import utcnow
from tests.test_system import _force_bet, _league_with_upcoming, rec


# ------------------------------------------------------------------ integrity & persistence guard
def test_integrity_detects_broken_bankroll_chain(db):
    from fil.integrity import check_database

    fid, ids = _force_bet(db)
    assert check_database()["ok"]
    import sqlite3

    con = sqlite3.connect(str(db))
    con.execute("DROP TRIGGER trg_bankroll_transactions_noupdate")
    con.execute("UPDATE bankroll_transactions SET balance_after = balance_after + 5 WHERE tx_type='stake'")
    con.commit()
    con.close()
    res = check_database()
    assert not res["ok"]
    assert any("bankroll chain" in p for p in res["problems"])
    assert any("missing immutability triggers" in p for p in res["problems"])


def test_guard_refuses_shrinking_ledger(db):
    from fil.integrity import guard_replace, manifest

    _force_bet(db)
    big = manifest()
    ok, why = guard_replace(str(db), json.dumps(big))
    assert ok, why
    bigger = dict(big, predictions=big["predictions"] + 5)
    ok, why = guard_replace(str(db), json.dumps(bigger))
    assert not ok and "shrink" in why


def test_backup_verification_catches_corruption(db, tmp_path):
    import gzip

    from fil.backup import verify_backup

    ingest_records([rec()], "football_data_uk")
    bad = tmp_path / "bad.db.gz"
    with gzip.open(bad, "wb") as g:
        g.write(b"this is not a sqlite database" * 100)
    with pytest.raises(Exception):
        res = verify_backup(bad)
        assert not res["ok"]
        raise AssertionError("corrupt")


# ------------------------------------------------------------------ data validation
@pytest.mark.parametrize("kw,problem", [
    (dict(status="finished", hg=-1, ag=0, ko=utcnow() - timedelta(days=1)), "invalid final score"),
    (dict(status="finished", hg=25, ag=0, ko=utcnow() - timedelta(days=1)), "invalid final score"),
    (dict(status="finished", hg=1, ag=0, ko=utcnow() + timedelta(days=3)), "has not started"),
    (dict(home="Same", away="same"), "identical team"),
    (dict(ko=utcnow() + timedelta(days=900)), "implausible kickoff"),
])
def test_invalid_records_rejected(db, kw, problem):
    r = rec(**{k: v for k, v in kw.items() if k in ("home", "away", "ko", "status", "hg", "ag")})
    assert problem in (validate(r) or "")
    out = ingest_records([r], "football_data_uk")
    assert out.get("invalid_records") == 1
    with session_scope() as s:
        assert s.scalars(select(Fixture)).all() == []


# ------------------------------------------------------------------ provider reliability
class _FakeResp:
    def __init__(self, code, text="", headers=None):
        self.status_code, self.content, self.headers = code, text.encode(), headers or {}
        self.url = "https://example.test/x"


def _client_returning(responses, calls):
    class C:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            calls.append(url)
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
    return C


def test_http_429_then_success(db, monkeypatch, tmp_path):
    from fil.providers import base

    calls = []
    monkeypatch.setattr(base.httpx, "Client", _client_returning([_FakeResp(429, headers={"Retry-After": "0"}),
                                                                 _FakeResp(200, "ok")], calls))
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    p = base.Provider()
    p.cache_dir = tmp_path
    assert p.get("https://example.test/x", ttl=0).text == "ok"
    assert len(calls) == 2


def test_timeout_falls_back_to_stale_cache(db, monkeypatch, tmp_path):
    from fil.providers import base

    calls = []
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    p = base.Provider()
    p.cache_dir = tmp_path
    monkeypatch.setattr(base.httpx, "Client", _client_returning([_FakeResp(200, "fresh")], calls))
    p.get("https://example.test/y", ttl=0)
    monkeypatch.setattr(base.httpx, "Client", _client_returning([httpx.ReadTimeout("t")] * 3, calls))
    res = p.get("https://example.test/y", ttl=0)
    assert res.text == "fresh" and res.from_cache  # labelled as cached, not presented as new


def test_unavailable_provider_without_cache_raises(db, monkeypatch, tmp_path):
    from fil.providers import base

    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    monkeypatch.setattr(base.httpx, "Client", _client_returning([httpx.ConnectError("down")] * 3, []))
    p = base.Provider()
    p.cache_dir = tmp_path
    with pytest.raises(base.ProviderError):
        p.get("https://example.test/z", ttl=0)


def test_malformed_responses_raise_provider_error(db, monkeypatch):
    from fil.providers.base import FetchResult, ProviderError
    from fil.providers.footballdata_uk import FootballDataUK
    from fil.providers.others import TheSportsDB

    monkeypatch.setattr(TheSportsDB, "get", lambda self, url, params=None, ttl=None: FetchResult("<html>oops", url, utcnow()))
    with pytest.raises(ProviderError):
        TheSportsDB().league_events("ENG1")
    monkeypatch.setattr(FootballDataUK, "get", lambda self, url, params=None, ttl=None: FetchResult("<!DOCTYPE html><p>maintenance", url, utcnow()))
    with pytest.raises(ProviderError):
        FootballDataUK().main_league_results("E0", "2627")


def test_circuit_breaker_opens_and_resets(db):
    from fil.collect import provider

    p = provider("thesportsdb")
    for _ in range(3):
        p.mark_error("boom")
    assert p.circuit_open()
    p.mark_success()
    assert not p.circuit_open()


def test_collect_fixtures_skips_open_circuit(db, monkeypatch):
    from fil import collect
    from fil.providers.footballdata_uk import FootballDataUK
    from fil.providers.others import TheSportsDB

    monkeypatch.setattr(FootballDataUK, "upcoming_fixtures", lambda self, ttl=1800: [])
    called = []
    monkeypatch.setattr(TheSportsDB, "league_events", lambda self, c: called.append(c) or [])
    t = collect.provider("thesportsdb")
    for _ in range(3):
        t.mark_error("x")
    out = collect.collect_fixtures()
    assert out["thesportsdb"] == {"skipped": "circuit open"} and called == []


# ------------------------------------------------------------------ health model
def test_health_states(db, monkeypatch):
    from fil import health, jobs

    h = health.compute()
    assert h["components"]["predictions"]["state"] == "UNKNOWN"
    monkeypatch.setitem(jobs.JOBS, "fixtures_odds", lambda: [("predict", lambda: {}, True), ("settle", lambda: {}, True)])
    jobs.run_job("fixtures_odds")
    h = health.compute()
    assert h["components"]["predictions"]["state"] == "HEALTHY"
    assert h["components"]["database"]["state"] == "HEALTHY"
    later = utcnow() + timedelta(hours=40)
    h = health.compute(now=later)
    assert h["components"]["predictions"]["state"] == "STALE"
    assert h["overall"] in ("STALE", "FAILED")
    monkeypatch.setitem(jobs.JOBS, "bad", lambda: [("settle", lambda: 1 / 0, True)])
    jobs.run_job("bad")
    assert health.compute()["components"]["last_run"]["state"] == "FAILED"


def test_health_collection_failed_when_provider_erroring(db):
    from fil import health
    from fil.collect import provider

    p = provider("football_data_uk")
    p.mark_error("down")
    assert health.compute()["components"]["collection"]["state"] == "FAILED"


# ------------------------------------------------------------------ explanations
def test_explanation_built_from_model_factors(db):
    from fil import pipeline

    _league_with_upcoming(db)
    pipeline.predict_upcoming(pipeline.get_engine(force=True))
    with session_scope() as s:
        p = s.scalars(select(Prediction)).one()
        ex = p.inputs["explanation"]
        assert ex["summary"].startswith("Most likely outcome")
        assert len(ex["main_factors"]) == 3
        names = {f["factor"] for f in ex["all_factors"]}
        assert "Home advantage" in names and any("attack rating" in n for n in names)
        assert any("team news" in m for m in ex["missing"])
        assert "NOT treated as a signal" in " ".join(ex["missing"])


# ------------------------------------------------------------------ full lifecycle (no mocks of core components)
def test_full_lifecycle_to_dashboard_export(db, tmp_path, monkeypatch):
    """fixture discovery -> prediction -> virtual bet -> result -> settlement -> analytics -> export."""
    from fil import cli, pipeline
    from fil.betting import settle_pending
    from fil.integrity import check_database
    from fil.stats import summary

    fid, ids = _force_bet(db)
    with session_scope() as s:
        ko = s.get(Fixture, fid).kickoff_utc
    from tests.test_system import after_kickoff

    after_kickoff(monkeypatch, ko)
    ingest_records([rec("Team 0", "Team 1", ko, status="finished", hg=3, ag=0)], "football_data_uk")
    from fil import betting

    out = settle_pending()
    assert out["settled"] == len(ids)
    pipeline.evaluate_predictions()
    sm = summary()
    assert sm["settled"] == len(ids) and sm["bets"] == len(ids)
    assert sm["prediction_metrics"]["evaluated"] == 1
    assert check_database()["ok"]
    # second settlement pass is a no-op (idempotent)
    assert settle_pending()["settled"] == 0
    site = tmp_path / "site"
    cli.export_static(site)
    data = json.loads((site / "data" / "bets.json").read_text())
    b = data["items"][0]
    assert b["bankroll_before"] is not None and b["bankroll_after_settlement"] is not None
    assert json.loads((site / "data" / "health_detail.json").read_text())["components"]["database"]["state"] == "HEALTHY"
    for f in (site / "data").glob("*.json"):
        txt = f.read_text()
        assert "FIL_ADMIN_TOKEN" not in txt and "apiKey=" not in txt  # no secrets in exports
