"""Data-quality scoring (0-100) for one fixture.

Each component has a fixed maximum; the breakdown is stored with every prediction so the score
is auditable. Repeating one underlying source across many books/sites does NOT add points: odds
availability counts distinct *markets*, and bookmaker count is capped.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np

WEIGHTS = {
    "source_reliability": 10, "history_sample": 20, "recency": 10, "odds_markets": 15,
    "odds_quality": 10, "odds_freshness": 10, "stats_depth": 10, "team_identity": 5, "team_news": 10,
}


def _lin(x, lo, hi):
    """0 at lo, 1 at hi (works for decreasing ranges too)."""
    if hi == lo:
        return 1.0
    return float(np.clip((x - lo) / (hi - lo), 0, 1))


def score(*, now: datetime, n_home: int, n_away: int, last_home: datetime | None, last_away: datetime | None,
          odds: dict, odds_age_h: float | None, ref_overround: float | None, book_dispersion: float | None,
          xg_share: float, stats_share: float, name_confidence: float, team_news_available: bool,
          source_reliability: str = "high") -> tuple[float, dict]:
    b = {}
    b["source_reliability"] = WEIGHTS["source_reliability"] * {"high": 1.0, "medium": 0.6, "low": 0.2}.get(source_reliability, 0.3)
    b["history_sample"] = WEIGHTS["history_sample"] * _lin(min(n_home, n_away), 8, 40)
    rec = []
    for last in (last_home, last_away):
        rec.append(0.0 if last is None else _lin((now - last).days, 60, 14))
    b["recency"] = WEIGHTS["recency"] * min(rec)
    mk = (0.6 if odds.get("1X2") else 0) + (0.2 if odds.get("OU25") else 0) + (0.2 if odds.get("AH") else 0)
    nb = min(odds.get("n_books", 0), 4) / 4
    b["odds_markets"] = WEIGHTS["odds_markets"] * mk * (0.5 + 0.5 * nb)
    q = 0.0
    if ref_overround is not None:
        q = 0.7 * _lin(ref_overround, 0.12, 0.04)
        q += 0.3 * (_lin(book_dispersion, 0.05, 0.01) if book_dispersion is not None else 0.5)
    b["odds_quality"] = WEIGHTS["odds_quality"] * q
    b["odds_freshness"] = WEIGHTS["odds_freshness"] * (0.0 if odds_age_h is None else _lin(odds_age_h, 120, 24))
    b["stats_depth"] = WEIGHTS["stats_depth"] * (0.5 * xg_share + 0.5 * stats_share)
    b["team_identity"] = WEIGHTS["team_identity"] * _lin(name_confidence, 0.8, 1.0)
    b["team_news"] = WEIGHTS["team_news"] * (1.0 if team_news_available else 0.0)
    b = {k: round(v, 2) for k, v in b.items()}
    return round(sum(b.values()), 1), b


def confidence(quality: float, components: dict, n_min: int) -> float:
    """Model confidence (0-100), separate from probability: how much we trust the estimate.

    Combines data quality, agreement between independent sub-models (DC vs Elo), and sample size.
    """
    dcp, elo = components["dixon_coles"], components["elo"]
    l1 = sum(abs(dcp[k] - elo[k]) for k in ("home", "draw", "away"))  # 0..2
    agreement = _lin(l1, 0.30, 0.04)
    sample = _lin(n_min, 8, 60)
    return round(100 * (0.4 * quality / 100 + 0.35 * agreement + 0.25 * sample), 1)
