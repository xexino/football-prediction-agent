import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

_tmp = tempfile.mkdtemp(prefix="fil-test-")
os.environ["FIL_DB_PATH"] = str(Path(_tmp) / "default.db")
os.environ["FIL_CACHE_DIR"] = str(Path(_tmp) / "cache")
os.environ["FIL_BACKUP_DIR"] = str(Path(_tmp) / "backups")
os.environ["FIL_SCHEDULER"] = "0"
os.environ["FIL_ADMIN_TOKEN"] = ""  # .env must not leak into tests (dotenv never overrides)
for _k in ("FOOTBALL_DATA_ORG_KEY", "ODDS_API_KEY", "API_FOOTBALL_KEY"):
    os.environ[_k] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fil import db as dbmod  # noqa: E402
from fil.config import settings  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "test.db"
    settings.db_path = path
    settings.backup_dir = tmp_path / "backups"
    dbmod.init_db(path)
    from fil.ingest import ensure_competitions

    ensure_competitions()
    from fil import pipeline

    pipeline._ENGINE.clear()
    yield path


def synthetic_league(n_teams=16, seasons=3, seed=7, comp="ENG1", end=None, with_odds=True):
    """Generate a realistic round-robin league with known team strengths (no real data)."""
    from fil.providers.footballdata_uk import MatchRecord

    rng = np.random.default_rng(seed)
    att = rng.normal(0, 0.3, n_teams)
    dfn = rng.normal(0, 0.3, n_teams)
    att -= att.mean()
    dfn -= dfn.mean()
    end = end or datetime(2026, 11, 1)
    start = end - timedelta(days=365 * seasons)
    recs = []
    d = start
    pairs = [(i, j) for i in range(n_teams) for j in range(n_teams) if i != j]
    per_round = n_teams // 2
    k = 0
    while d < end:
        for _ in range(per_round):
            i, j = pairs[k % len(pairs)]
            k += 1
            lam = np.exp(0.15 + 0.25 + att[i] + dfn[j])
            mu = np.exp(0.15 + att[j] + dfn[i])
            hg, ag = int(rng.poisson(lam)), int(rng.poisson(mu))
            odds = []
            if with_odds:
                from fil.models.dixon_coles import score_matrix
                from fil.models.markets import markets_from_matrix

                mk = markets_from_matrix(score_matrix(lam, mu))
                for bk, margin in (("B365", 1.05), ("BFE", 1.01), ("Avg", 1.06)):
                    odds.append((bk, "pre_match", {
                        "home": round(1 / (mk["1X2"]["home"] * margin), 2), "draw": round(1 / (mk["1X2"]["draw"] * margin), 2),
                        "away": round(1 / (mk["1X2"]["away"] * margin), 2), "over25": round(1 / (mk["OU25"]["over"] * margin), 2),
                        "under25": round(1 / (mk["OU25"]["under"] * margin), 2)}))
            recs.append(MatchRecord(comp_code=comp, season=str(d.year), home=f"Team {i}", away=f"Team {j}",
                                    kickoff_utc=d.replace(hour=15), country="England", status="finished",
                                    home_goals=hg, away_goals=ag, stats={"home_shots": 10, "away_shots": 9},
                                    odds=odds, retrieved_at=d, source_url="synthetic://test"))
        d += timedelta(days=7)
    return recs, att, dfn


@pytest.fixture(autouse=True)
def _reset_provider_rate_state():
    """Provider rate/down state is shared per provider key (class level); tests must not leak it."""
    from fil.providers.base import Provider

    Provider._RATE.clear()
    yield
    Provider._RATE.clear()
