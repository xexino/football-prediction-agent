"""Central configuration. All values can be overridden through environment variables / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

ROOT = Path(__file__).resolve().parents[2]
if load_dotenv:
    load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _path(name: str, default: str) -> Path:
    p = Path(_env(name, default))
    return p if p.is_absolute() else ROOT / p


@dataclass
class RiskRules:
    """Virtual-betting risk rules. Conservative by design."""

    # Owner decision 2026-11-25: virtual bankroll €500 and flat €10 stakes from now on (was €100 / €1). Existing
    # records are untouched: the difference is booked once as a visible "top_up" ledger entry (betting.ensure_bankroll).
    initial_bankroll: float = 500.0
    stake: float = 10.0  # flat stake (€)
    max_stake: float = 10.0
    max_bets_per_match: int = 3
    max_bets_per_day: int = 15
    staking_method: str = "flat"  # only 'flat' is enabled until validated


@dataclass
class ValueRules:
    """Thresholds a selection must pass to become a simulated bet."""

    min_data_quality: float = 70.0
    min_confidence: float = 55.0
    min_ev_conservative: float = 0.02  # +2% EV under the blended (best-estimate) probability
    # conservative prob = w*model + (1-w)*market. w=0.10 is the out-of-sample log-loss-optimal blend
    # found by the walk-forward backtest (see docs/DECISIONS.md) — the model adds little beyond the market.
    market_shrink: float = 0.10
    min_odds: float = 1.50
    max_odds: float = 5.00
    max_overround: float = 0.09  # reject books with >9% margin
    max_model_market_gap: float = 0.15  # >15pp disagreement => probable model error, reject
    min_team_matches: int = 20  # matches per team in training window
    max_odds_age_hours: float = 96.0
    require_team_news: bool = False  # no free team-news source exists; penalised in quality instead
    bettable_markets: tuple = ("1X2", "OU25", "AH")


@dataclass
class Settings:
    db_path: Path = field(default_factory=lambda: _path("FIL_DB_PATH", "data/fil.db"))
    backup_dir: Path = field(default_factory=lambda: _path("FIL_BACKUP_DIR", "data/backups"))
    cache_dir: Path = field(default_factory=lambda: _path("FIL_CACHE_DIR", "data/cache"))
    host: str = field(default_factory=lambda: _env("FIL_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("FIL_PORT", "8000") or 8000))
    admin_token: str = field(default_factory=lambda: _env("FIL_ADMIN_TOKEN"))
    scheduler_enabled: bool = field(default_factory=lambda: _env("FIL_SCHEDULER", "1") != "0")
    display_tz: str = "Europe/Rome"

    football_data_org_key: str = field(default_factory=lambda: _env("FOOTBALL_DATA_ORG_KEY"))
    odds_api_key: str = field(default_factory=lambda: _env("ODDS_API_KEY"))
    api_football_key: str = field(default_factory=lambda: _env("API_FOOTBALL_KEY"))
    thesportsdb_key: str = field(default_factory=lambda: _env("THESPORTSDB_KEY", "123") or "123")

    # How many seasons of history to import from football-data.co.uk
    history_seasons: int = 4

    risk: RiskRules = field(default_factory=RiskRules)
    value: ValueRules = field(default_factory=ValueRules)


settings = Settings()
