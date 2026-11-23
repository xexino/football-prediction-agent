"""Engine B (AI Match Insights) tests + Engine A regression protection."""
import json
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import func, select

from fil.db import (BankrollTransaction, EBBankrollTransaction, EBBet, EBLiveEvent, EBLiveSnapshot, EBPrediction, Fixture,
                    Prediction, VirtualBet, session_scope)
from fil.ingest import ingest_records
from fil.timeutil import utcnow
from tests.conftest import synthetic_league
from tests.test_system import IMMUTABLE_ERR, _league_with_upcoming, after_kickoff, rec


# ------------------------------------------------------------------ Engine A regression (golden values)
def test_engine_a_outputs_unchanged(db):
    """Engine A must produce exactly the same numbers as before Engine B existed."""
    from fil.models.engine import Engine, load_matches

    recs, _, _ = synthetic_league(n_teams=12, seasons=3, end=datetime(2026, 10, 1))
    ingest_records(recs, "football_data_uk")
    e = Engine().build(load_matches(), datetime(2026, 10, 2))
    p = e.predict("ENG1", *sorted({m["home_id"] for m in load_matches()})[:2])
    ens = p["components"]["ensemble"]
    assert ens["home"] == pytest.approx(0.335368, abs=1e-5)
    assert ens["draw"] == pytest.approx(0.235821, abs=1e-5)
    assert ens["away"] == pytest.approx(0.42881, abs=1e-5)
    assert p["exp_home_goals"] == pytest.approx(1.427701, abs=1e-5)
    assert p["markets"]["OU25"]["over"] == pytest.approx(0.577269, abs=1e-5)


def test_engine_b_never_touches_engine_a_records(db):
    from fil import pipeline
    from fil.engine_b import pipeline as pb

    _league_with_upcoming(db)
    pipeline.predict_upcoming(pipeline.get_engine(force=True))
    with session_scope() as s:
        before = (s.scalar(select(func.count(Prediction.id))), s.scalar(select(func.count(VirtualBet.id))),
                  [t.balance_after for t in s.scalars(select(BankrollTransaction))],
                  json.dumps([p.probs for p in s.scalars(select(Prediction))], sort_keys=True))
    pb._CACHE.clear()
    out = pb.predict_upcoming()
    assert out["predicted"] == 1
    with session_scope() as s:
        after = (s.scalar(select(func.count(Prediction.id))), s.scalar(select(func.count(VirtualBet.id))),
                 [t.balance_after for t in s.scalars(select(BankrollTransaction))],
                 json.dumps([p.probs for p in s.scalars(select(Prediction))], sort_keys=True))
        assert before == after
        assert s.scalars(select(EBBankrollTransaction)).first().balance_after == 100.0  # own bankroll


# ------------------------------------------------------------------ features: no leakage
def test_features_are_strictly_pre_match():
    from fil.engine_b.features import build_rows

    base = [dict(id=i, comp="ENG1", home=i % 4, away=(i + 1) % 4, kickoff=datetime(2026, 1, 1) + timedelta(days=i),
                 h_goals=1, a_goals=0, h_corners=5, a_corners=4, h_yellows=1, a_yellows=2) for i in range(40)]
    rows1, _ = build_rows(base)
    changed = [dict(m) for m in base]
    changed[20]["h_goals"], changed[20]["h_corners"] = 7, 15
    rows2, _ = build_rows(changed)
    for k in rows1[20]:
        if not k.startswith("y_"):
            assert rows1[20][k] == rows2[20][k], k  # a match's own result never leaks into its features
    assert rows1[25]["h_goals_att"] != rows2[25]["h_goals_att"] or rows1[25]["a_goals_att"] != rows2[25]["a_goals_att"]


# ------------------------------------------------------------------ model & markets
def _trained():
    from fil.engine_b.features import build_rows
    from fil.engine_b.model import EngineBModel

    recs, _, _ = synthetic_league(n_teams=14, seasons=3, end=datetime(2026, 10, 1), with_odds=False)
    rng = np.random.default_rng(3)
    hist = [dict(id=i, comp="ENG1", home=int(r.home.split()[1]), away=int(r.away.split()[1]), kickoff=r.kickoff_utc,
                 h_goals=r.home_goals, a_goals=r.away_goals, h_corners=int(rng.poisson(5.5)), a_corners=int(rng.poisson(4.5)),
                 h_yellows=int(rng.poisson(1.8)), a_yellows=int(rng.poisson(2.1)), h_sot=int(rng.poisson(4.5)),
                 a_sot=int(rng.poisson(3.8)), h_shots=int(rng.poisson(13)), a_shots=int(rng.poisson(11)),
                 h_fouls=int(rng.poisson(11)), a_fouls=int(rng.poisson(12)), h_red=int(rng.random() < 0.1), a_red=0)
            for i, r in enumerate(recs)]
    rows, st = build_rows(hist)
    return EngineBModel().fit(rows, datetime(2026, 10, 2)), st, rows


def test_engine_b_markets_are_coherent():
    model, st, rows = _trained()
    f = st.features("ENG1", 0, 1, datetime(2026, 10, 5))
    p = model.predict(f)
    mk = p["markets"]
    assert abs(sum(mk["1X2"].values()) - 1) < 1e-9
    assert abs(np.sum(p["matrix"]) - 1) < 1e-9
    for k in ("OU05", "OU15", "OU25", "OU35", "OU45"):
        assert abs(mk[k]["over"] + mk[k]["under"] - 1) < 1e-9
    assert mk["OU05"]["over"] > mk["OU15"]["over"] > mk["OU25"]["over"] > mk["OU35"]["over"]
    assert abs(mk["BTTS"]["yes"] + mk["BTTS"]["no"] - 1) < 1e-9
    fts = mk["FIRST_TO_SCORE"]
    assert abs(fts["home"] + fts["away"] + fts["none"] - 1) < 1e-9
    assert len(mk["CORRECT_SCORE_TOP"]) == 8
    c = mk["CORNERS"]
    assert c["OU7.5"]["over"] > c["OU9.5"]["over"] > c["OU10.5"]["over"]
    assert 8 < c["expected"]["total"] < 12 and c["interval_80"][0] < c["expected"]["total"] < c["interval_80"][1]
    assert "OU3.5" in mk["YELLOWS"] and 0 < mk["RED"]["any_red_card"] < 1
    assert "player_goals" in p["unavailable"]  # honestly unavailable, never invented


def test_missing_statistics_make_market_unavailable_not_zero():
    model, st, rows = _trained()
    f = st.features("ENG1", 0, 1, datetime(2026, 10, 5))
    for k in list(f):
        if "corners" in k and ("att" in k or "def" in k):
            f[k] = None
    p = model.predict(f)
    assert "CORNERS" not in p["markets"] and "corners" in p["unavailable"]


def test_insufficient_history_gives_no_prediction():
    model, st, rows = _trained()
    f = st.features("ENG1", 9999, 1, datetime(2026, 10, 5))  # unknown team
    assert model.predict(f)["markets"] == {}


# ------------------------------------------------------------------ pipeline, immutability, revisions, report
def test_engine_b_prediction_immutable_and_reproducible(db):
    from fil.engine_b import pipeline as pb

    _league_with_upcoming(db)
    pb._CACHE.clear()
    pb.predict_upcoming()
    with session_scope() as s:
        p = s.scalars(select(EBPrediction)).one()
        assert p.features["_trained_at"] and p.data_cutoff < p.kickoff_utc and p.inputs_hash
        assert p.report["sections"]["assessment"] and p.report["missing"]
        assert "no LLM" in p.report["generator"]
        p.markets = {}
        with pytest.raises(IMMUTABLE_ERR):
            s.flush()
        s.rollback()
    assert pb.predict_upcoming()["unchanged"] == 1  # unchanged inputs -> no duplicate prediction


def test_report_never_asserts_unavailable_facts(db):
    from fil.engine_b import pipeline as pb

    _league_with_upcoming(db)
    pb._CACHE.clear()
    pb.predict_upcoming()
    with session_scope() as s:
        rep = s.scalars(select(EBPrediction)).one().report
        text = json.dumps(rep["sections"]).lower()
        assert "injur" not in text and "lineup" not in text  # only mentioned under 'missing'
        assert any("lineups, injuries" in m for m in rep["missing"])


# ------------------------------------------------------------------ Engine B bankroll
def test_engine_b_rejects_corrupt_reference_odds():
    from fil.engine_b.betting import RiskB, candidates

    class O:
        def __init__(self, bk, **kw):
            self.bookmaker, self.id = bk, 1
            for k in ("home", "draw", "away", "over25", "under25"):
                setattr(self, k, kw.get(k))
    markets = {"1X2": {"home": 0.4, "draw": 0.3, "away": 0.3}, "OU25": {"over": 0.62, "under": 0.38}}
    snaps = {"B365": O("B365", over25=2.0, under25=1.8), "BFE": O("BFE", over25=1.2, under25=1.3)}  # corrupt ref
    c = candidates(markets, snaps, 90, 90, RiskB(markets=("OU25",)))
    assert not any(x["qualifies"] for x in c)
    assert any("data error" in r for x in c for r in x["reasons"])


def test_engine_b_1x2_disabled_by_evidence():
    from fil.engine_b.betting import RISK

    assert RISK.markets == ("OU25",)


def test_engine_b_ledger_settlement_independent(db, monkeypatch):
    from fil.engine_b import betting
    from fil.engine_b import pipeline as pb

    fid = _league_with_upcoming(db)
    pb._CACHE.clear()
    pb.predict_upcoming()
    with session_scope() as s:
        p = s.scalars(select(EBPrediction)).one()
        fx = s.get(Fixture, fid)
        cand = {"market": "OU25", "selection": "over", "line": 2.5, "price": 2.0, "bookmaker": "B365",
                "odds_observation_id": None, "model_prob": 0.6, "market_prob": 0.5, "ev": 0.05}
        b = betting.place(s, prediction=p, fixture=fx, cand=cand, quality=80)
        assert b is not None and betting.balance(s) == 99.0
        ko = fx.kickoff_utc
    after_kickoff(monkeypatch, ko)
    ingest_records([rec("Team 0", "Team 1", ko, status="finished", hg=2, ag=1)], "football_data_uk")
    assert betting.settle_pending()["settled"] == 1
    assert betting.settle_pending()["settled"] == 0  # idempotent
    with session_scope() as s:
        assert s.scalars(select(EBBet)).one().status == "won"
        assert s.scalars(select(EBBankrollTransaction).order_by(EBBankrollTransaction.id.desc())).first().balance_after == 101.0
        assert s.scalar(select(func.count(BankrollTransaction.id))) <= 1  # Engine A ledger untouched
        b = s.scalars(select(EBBet)).one()
        b.status = "lost"
        with pytest.raises(IMMUTABLE_ERR):
            s.flush()
        s.rollback()
    from fil.integrity import check_database
    assert check_database()["ok"]


# ------------------------------------------------------------------ live mode
def test_live_probabilities_coherent():
    from fil.engine_b.live import live_probabilities

    p = live_probabilities(1.5, 1.1, 60, 1, 0)
    assert abs(sum(p["1X2"].values()) - 1) < 1e-9 and p["1X2"]["home"] > 0.6
    late = live_probabilities(1.5, 1.1, 93, 0, 0)
    assert late["1X2"]["draw"] > 0.9
    red = live_probabilities(1.5, 1.1, 30, 0, 0, reds_home=1)
    assert red["1X2"]["home"] < live_probabilities(1.5, 1.1, 30, 0, 0)["1X2"]["home"]
    assert p["OU05"]["over"] == pytest.approx(1.0)


class _LiveFake:
    name, priority = "api_football", 1
    capabilities = {"minute": True}
    configured = True

    def __init__(self, matches):
        self.m = matches

    def live_matches(self):
        return self.m


def test_live_poll_snapshots_events_and_dedup(db, monkeypatch):
    from fil.engine_b import live
    from fil.engine_b import pipeline as pb

    fid = _league_with_upcoming(db)
    pb._CACHE.clear()
    pb.predict_upcoming()
    with session_scope() as s:
        f = s.get(Fixture, fid)
        pre = json.dumps(s.scalars(select(EBPrediction)).one().markets, sort_keys=True)
    now = utcnow()
    ev = [{"key": "x1", "minute": 12, "type": "goal", "side": "home", "player": "A", "detail": "Normal Goal"},
          {"key": "x2", "minute": 40, "type": "card", "side": "away", "player": "B", "detail": "Red Card"}]
    lm = live.LiveMatch("api_football", "999", "ENG1", "Team 0", "Team 1", now - timedelta(minutes=50), "live", 50, "provider",
                        1, 0, stats={"corners": {"home": 4, "away": 2}}, events=ev, provider_updated_at=now, retrieved_at=now,
                        fixture_id=fid)
    monkeypatch.setattr(live, "providers", lambda: [_LiveFake([lm])])
    out = live.poll()
    assert out["snapshots"] == 1 and out["events"] == 2 and out["live_predictions"] == 1
    assert live.poll()["snapshots"] == 0  # identical state -> no duplicate snapshot / events
    with session_scope() as s:
        snap = s.scalars(select(EBLiveSnapshot)).one()
        assert snap.data_label == "LIVE" and snap.probs["1X2"]["home"] > 0.5 and snap.stats == {"corners": {"home": 4, "away": 2}}
        assert s.scalar(select(func.count(EBLiveEvent.id))) == 2
        assert json.dumps(s.scalars(select(EBPrediction)).one().markets, sort_keys=True) == pre  # pre-match untouched


def test_stale_or_minuteless_live_data_gets_no_live_prediction(db, monkeypatch):
    from fil.engine_b import live
    from fil.engine_b import pipeline as pb

    fid = _league_with_upcoming(db)
    pb._CACHE.clear()
    pb.predict_upcoming()
    now = utcnow()
    stale = live.LiveMatch("football_data_org", "5", "ENG1", "Team 0", "Team 1", now - timedelta(hours=22), "live", None,
                           "unknown", 0, 0, provider_updated_at=now - timedelta(hours=20), retrieved_at=now, fixture_id=fid)
    monkeypatch.setattr(live, "providers", lambda: [_LiveFake([stale])])
    live.poll()
    with session_scope() as s:
        snap = s.scalars(select(EBLiveSnapshot)).one()
        assert snap.data_label == "STALE" and snap.probs is None


def test_apif_statistics_parsing_keeps_missing_missing():
    from fil.engine_b.live import parse_apif_statistics

    body = {"response": [{"statistics": [{"type": "Corner Kicks", "value": 5}, {"type": "Ball Possession", "value": "61%"},
                                         {"type": "Offsides", "value": None}]},
                         {"statistics": [{"type": "Corner Kicks", "value": 2}, {"type": "Ball Possession", "value": "39%"},
                                         {"type": "Offsides", "value": None}]}]}
    st = parse_apif_statistics(body)
    assert st == {"corners": {"home": 5.0, "away": 2.0}, "possession": {"home": 61.0, "away": 39.0}}


def test_apif_live_normalization(monkeypatch):
    from fil.config import settings
    from fil.engine_b import live

    monkeypatch.setattr(settings, "api_football_key", "k" * 20)
    payload = {"errors": [], "response": [{
        "fixture": {"id": 77, "date": "2026-11-23T15:00:00+00:00", "status": {"short": "2H", "elapsed": 67}},
        "league": {"id": 39, "name": "Premier League"}, "teams": {"home": {"id": 1, "name": "Arsenal"}, "away": {"id": 2, "name": "Chelsea"}},
        "goals": {"home": 2, "away": 1},
        "events": [{"time": {"elapsed": 23, "extra": None}, "team": {"id": 1}, "player": {"id": 9, "name": "Saka"}, "type": "Goal", "detail": "Normal Goal"}]}]}
    p = live.APIFootballLive()
    monkeypatch.setattr(p, "_get", lambda path, params: payload if path == "/fixtures" else {"response": []})
    m = p.live_matches()[0]
    assert (m.comp_code, m.minute, m.minute_source, m.home_goals, m.status) == ("ENG1", 67, "provider", 2, "live")
    assert m.events[0]["type"] == "goal" and m.events[0]["side"] == "home"
    assert m.stats == {}  # statistics call returned nothing -> nothing invented


def test_apif_missing_key_is_config_error(monkeypatch):
    from fil.config import settings
    from fil.engine_b import live
    from fil.providers.base import NotConfigured

    monkeypatch.setattr(settings, "api_football_key", "")
    assert not live.APIFootballLive().configured
    with pytest.raises(NotConfigured):
        live.APIFootballLive()._get("/fixtures", {})


# ------------------------------------------------------------------ migration, API, export
def test_migration_adds_engine_b_tables_without_touching_data(tmp_path):
    from fil import db as dbmod
    from fil.integrity import check_database

    path = tmp_path / "old.db"
    dbmod.init_db(path)
    con = sqlite3.connect(path)
    for t in [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'eb_%'")]:
        con.execute(f"DROP TABLE {t}")
    con.execute("INSERT INTO bankroll_transactions (created_at, tx_type, amount, balance_after, note) VALUES ('2026-01-01', 'initial', 100, 100, 'x')")
    con.commit()
    con.close()
    dbmod.init_db(path)  # upgrade = create missing tables + triggers only
    con = sqlite3.connect(path)
    assert con.execute("SELECT balance_after FROM bankroll_transactions").fetchone()[0] == 100
    assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='eb_predictions'").fetchone()[0] == 1
    con.close()
    assert check_database(path)["ok"]


def test_engine_b_api_and_static_export(db, tmp_path):
    from fastapi.testclient import TestClient

    from fil import cli
    from fil.api import app
    from fil.engine_b import pipeline as pb

    fid = _league_with_upcoming(db)
    pb._CACHE.clear()
    pb.predict_upcoming()
    with TestClient(app) as c:
        for ep in ("insights", f"insights/{fid}", "engine_b/performance", "engine_compare", "coverage_matrix"):
            assert c.get(f"/api/{ep}").status_code == 200, ep
        d = c.get(f"/api/insights/{fid}").json()
        assert d["prediction"]["markets"]["1X2"] and len(d["prediction"]["score_matrix"]) == 8
        assert c.get("/api/insights/999999").status_code == 404
    cli.export_static(tmp_path / "site")
    assert (tmp_path / "site" / "data" / "insights" / f"{fid}.json").exists()
    assert (tmp_path / "site" / "data" / "engine_b" / "performance.json").exists()
