"""Database schema (SQLite via SQLAlchemy 2.0).

Design principles
-----------------
* Every timestamp is stored as naive UTC ISO-8601.
* Odds, results and stats are append-only *observations* that carry source + retrieval time.
* Predictions, value assessments, virtual bets, settlements and bankroll transactions are
  immutable: SQLite triggers abort any UPDATE of their core columns and any DELETE.
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import settings
from .timeutil import utcnow


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


# --------------------------------------------------------------------------- reference data
class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(64))  # results/odds/fixtures/...
    base_url: Mapped[str] = mapped_column(String(256))
    license_note: Mapped[str] = mapped_column(Text, default="")
    requires_key: Mapped[bool] = mapped_column(Boolean, default=False)
    configured: Mapped[bool] = mapped_column(Boolean, default=False)
    reliability: Mapped[str] = mapped_column(String(16), default="medium")  # high/medium/low
    status: Mapped[str] = mapped_column(String(32), default="unknown")  # ok/error/not_configured
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    quota_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    requests_total: Mapped[int] = mapped_column(Integer, default=0)
    records_total: Mapped[int] = mapped_column(Integer, default=0)


class Competition(Base):
    __tablename__ = "competitions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # internal code e.g. ENG1
    name: Mapped[str] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(64), default="")
    region: Mapped[str] = mapped_column(String(32), default="")  # Europe/Africa/Americas/Asia/International
    kind: Mapped[str] = mapped_column(String(16), default="league")  # league/cup/international
    priority: Mapped[int] = mapped_column(Integer, default=3)
    sources: Mapped[dict] = mapped_column(JSON, default=dict)  # provider -> provider code
    eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    coverage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    coverage_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(64), default="")
    is_national: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("name", "country", name="uq_team_name_country"),)


class TeamAlias(Base):
    __tablename__ = "team_aliases"
    id: Mapped[int] = mapped_column(primary_key=True)
    alias_norm: Mapped[str] = mapped_column(String(128))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    source: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    __table_args__ = (UniqueConstraint("alias_norm", "source", "team_id", name="uq_alias"),)


class Player(Base):
    __tablename__ = "players"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    position: Mapped[str] = mapped_column(String(32), default="")
    source: Mapped[str] = mapped_column(String(64), default="")


# --------------------------------------------------------------------------- matches
class Fixture(Base):
    __tablename__ = "fixtures"
    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), index=True)
    season: Mapped[str] = mapped_column(String(16), default="")
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    kickoff_utc: Mapped[datetime] = mapped_column(DateTime, index=True)
    match_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD (UTC) used for dedupe
    neutral: Mapped[bool] = mapped_column(Boolean, default=False)
    # scheduled / finished / postponed / cancelled / abandoned / unknown
    status: Mapped[str] = mapped_column(String(16), default="scheduled", index=True)
    home_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ht_home_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ht_away_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    external_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen_source: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (
        UniqueConstraint("competition_id", "home_team_id", "away_team_id", "match_date", name="uq_fixture"),
    )


class ResultObservation(Base):
    """Every result reported by every source — used to verify and detect conflicts."""

    __tablename__ = "result_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    source: Mapped[str] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(16))
    home_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ht_home_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ht_away_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint("fixture_id", "source", "status", "home_goals", "away_goals", name="uq_resobs"),)


class MatchStats(Base):
    __tablename__ = "match_stats"
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    source: Mapped[str] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    home_xg: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_xg: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_shots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_shots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_sot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_sot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_corners: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_corners: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_fouls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_fouls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_yellow: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_yellow: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_red: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_red: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint("fixture_id", "source", name="uq_stats"),)


class StandingSnapshot(Base):
    """One row per team per competition per day (append-only history of league tables)."""

    __tablename__ = "standings"
    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), index=True)
    season: Mapped[str] = mapped_column(String(16))
    snapshot_date: Mapped[str] = mapped_column(String(10))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    team_name: Mapped[str] = mapped_column(String(128))
    position: Mapped[int] = mapped_column(Integer)
    played: Mapped[int] = mapped_column(Integer)
    won: Mapped[int] = mapped_column(Integer)
    draw: Mapped[int] = mapped_column(Integer)
    lost: Mapped[int] = mapped_column(Integer)
    goals_for: Mapped[int] = mapped_column(Integer)
    goals_against: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer)
    form: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("competition_id", "season", "team_name", "snapshot_date", "source", name="uq_standing"),)


class TeamNews(Base):
    __tablename__ = "team_news"
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int | None] = mapped_column(ForeignKey("fixtures.id"), nullable=True, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    player_name: Mapped[str] = mapped_column(String(128), default="")
    news_type: Mapped[str] = mapped_column(String(32))  # injury/suspension/lineup/manager/other
    certainty: Mapped[str] = mapped_column(String(16))  # confirmed/expected/rumour
    detail: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(String(512), default="")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OddsObservation(Base):
    """One snapshot of one bookmaker's prices for one fixture at one point in time.

    kind: 'pre_match' (price published before kickoff) or 'closing' (last price before kickoff).
    """

    __tablename__ = "odds_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    source: Mapped[str] = mapped_column(String(64))
    bookmaker: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source_url: Mapped[str] = mapped_column(String(256), default="")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    home: Mapped[float | None] = mapped_column(Float, nullable=True)
    draw: Mapped[float | None] = mapped_column(Float, nullable=True)
    away: Mapped[float | None] = mapped_column(Float, nullable=True)
    over25: Mapped[float | None] = mapped_column(Float, nullable=True)
    under25: Mapped[float | None] = mapped_column(Float, nullable=True)
    ah_line: Mapped[float | None] = mapped_column(Float, nullable=True)  # home handicap
    ah_home: Mapped[float | None] = mapped_column(Float, nullable=True)
    ah_away: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(40))
    __table_args__ = (
        UniqueConstraint("fixture_id", "source", "bookmaker", "kind", "content_hash", name="uq_odds_snapshot"),
        Index("ix_odds_fixture_kind", "fixture_id", "kind"),
    )


# --------------------------------------------------------------------------- modelling
class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_version"),)


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    kickoff_utc: Mapped[datetime] = mapped_column(DateTime)
    revision: Mapped[int] = mapped_column(Integer, default=0)  # 0 = original
    revision_of: Mapped[int | None] = mapped_column(ForeignKey("predictions.id"), nullable=True)
    revision_reason: Mapped[str] = mapped_column(Text, default="")
    probs: Mapped[dict] = mapped_column(JSON)  # market -> selection -> prob
    component_probs: Mapped[dict] = mapped_column(JSON, default=dict)  # per sub-model 1X2
    exp_home_goals: Mapped[float] = mapped_column(Float)
    exp_away_goals: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    data_quality: Mapped[float] = mapped_column(Float)
    quality_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    decision: Mapped[str] = mapped_column(String(16))  # BET / NO_BET / INELIGIBLE
    explanation: Mapped[str] = mapped_column(Text, default="")
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)  # odds observation ids, form, etc.
    inputs_hash: Mapped[str] = mapped_column(String(40))
    sources: Mapped[list] = mapped_column(JSON, default=list)
    # evaluation fields filled after the match (not part of the immutable prediction)
    evaluated: Mapped[bool] = mapped_column(Boolean, default=False)
    eval_brier: Mapped[float | None] = mapped_column(Float, nullable=True)
    eval_logloss: Mapped[float | None] = mapped_column(Float, nullable=True)
    eval_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class ValueAssessment(Base):
    __tablename__ = "value_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), index=True)
    market: Mapped[str] = mapped_column(String(16))
    selection: Mapped[str] = mapped_column(String(16))
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    bookmaker: Mapped[str] = mapped_column(String(32), default="")
    odds_observation_id: Mapped[int | None] = mapped_column(ForeignKey("odds_observations.id"), nullable=True)
    implied_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_prob: Mapped[float | None] = mapped_column(Float, nullable=True)  # de-vigged
    model_prob: Mapped[float] = mapped_column(Float)
    conservative_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    overround: Mapped[float | None] = mapped_column(Float, nullable=True)
    ev: Mapped[float | None] = mapped_column(Float, nullable=True)
    ev_conservative: Mapped[float | None] = mapped_column(Float, nullable=True)
    qualifies: Mapped[bool] = mapped_column(Boolean, default=False)
    reject_reasons: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class VirtualBet(Base):
    __tablename__ = "virtual_bets"
    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"))
    value_assessment_id: Mapped[int] = mapped_column(ForeignKey("value_assessments.id"), unique=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    market: Mapped[str] = mapped_column(String(16))
    selection: Mapped[str] = mapped_column(String(16))
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float] = mapped_column(Float)
    bookmaker: Mapped[str] = mapped_column(String(32))
    stake: Mapped[float] = mapped_column(Float)
    potential_return: Mapped[float] = mapped_column(Float)
    model_prob: Mapped[float] = mapped_column(Float)
    ev: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    kickoff_utc: Mapped[datetime] = mapped_column(DateTime)
    # mutable settlement fields
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    payout: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    closing_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    clv: Mapped[float | None] = mapped_column(Float, nullable=True)


class Settlement(Base):
    __tablename__ = "settlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    bet_id: Mapped[int] = mapped_column(ForeignKey("virtual_bets.id"), unique=True)
    settled_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    home_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_source: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16))
    payout: Mapped[float] = mapped_column(Float)
    rule: Mapped[str] = mapped_column(Text)


class BankrollTransaction(Base):
    __tablename__ = "bankroll_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    tx_type: Mapped[str] = mapped_column(String(16))  # initial/stake/payout/refund
    amount: Mapped[float] = mapped_column(Float)
    balance_after: Mapped[float] = mapped_column(Float)
    bet_id: Mapped[int | None] = mapped_column(ForeignKey("virtual_bets.id"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


# --------------------------------------------------------------------------- ENGINE B (AI Match Insights)
# Fully separate from Engine A: own models, predictions, live snapshots, ledger and bankroll.
class EBModelVersion(Base):
    __tablename__ = "eb_model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    features: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("name", "version", name="uq_eb_model_version"),)


class EBPrediction(Base):
    """Immutable pre-match prediction of Engine B (revisions are new rows)."""

    __tablename__ = "eb_predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("eb_model_versions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    kickoff_utc: Mapped[datetime] = mapped_column(DateTime)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    markets: Mapped[dict] = mapped_column(JSON)          # market -> selection -> prob / expectations
    score_matrix: Mapped[list] = mapped_column(JSON)     # 0..9 x 0..9 probabilities
    features: Mapped[dict] = mapped_column(JSON)         # feature snapshot (reproducibility)
    confidence: Mapped[float] = mapped_column(Float)
    data_quality: Mapped[float] = mapped_column(Float)
    unavailable: Mapped[dict] = mapped_column(JSON, default=dict)  # market -> reason
    report: Mapped[dict] = mapped_column(JSON, default=dict)       # AI Match Analyst report
    inputs_hash: Mapped[str] = mapped_column(String(40))


class EBLiveSnapshot(Base):
    """Timestamped in-play state + live prediction. Never overwrites pre-match predictions."""

    __tablename__ = "eb_live_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    provider: Mapped[str] = mapped_column(String(64))
    provider_event_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minute_source: Mapped[str] = mapped_column(String(16))  # provider / estimated / unknown
    home_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)   # only fields the provider actually supplied
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    freshness_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_label: Mapped[str] = mapped_column(String(24))       # LIVE / DELAYED / STALE
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("eb_model_versions.id"), nullable=True)
    probs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_hash: Mapped[str] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint("fixture_id", "input_hash", name="uq_eb_live_input"),)


class EBLiveEvent(Base):
    __tablename__ = "eb_live_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    event_key: Mapped[str] = mapped_column(String(128))
    minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(32))
    side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    player: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(256), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("provider", "event_key", name="uq_eb_live_event"),)


class EBBet(Base):
    __tablename__ = "eb_bets"
    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("eb_predictions.id"))
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("eb_model_versions.id"))
    mode: Mapped[str] = mapped_column(String(8), default="prematch")
    market: Mapped[str] = mapped_column(String(16))
    selection: Mapped[str] = mapped_column(String(16))
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float] = mapped_column(Float)
    bookmaker: Mapped[str] = mapped_column(String(32))
    odds_observation_id: Mapped[int | None] = mapped_column(ForeignKey("odds_observations.id"), nullable=True)
    stake: Mapped[float] = mapped_column(Float)
    model_prob: Mapped[float] = mapped_column(Float)
    market_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    ev: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, default="")
    data_quality: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    kickoff_utc: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    payout: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    closing_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    clv: Mapped[float | None] = mapped_column(Float, nullable=True)


class EBSettlement(Base):
    __tablename__ = "eb_settlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    bet_id: Mapped[int] = mapped_column(ForeignKey("eb_bets.id"), unique=True)
    settled_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    home_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_source: Mapped[str] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(16))
    payout: Mapped[float] = mapped_column(Float)
    rule: Mapped[str] = mapped_column(Text)


class EBBankrollTransaction(Base):
    __tablename__ = "eb_bankroll_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    tx_type: Mapped[str] = mapped_column(String(16))
    amount: Mapped[float] = mapped_column(Float)
    balance_after: Mapped[float] = mapped_column(Float)
    bet_id: Mapped[int | None] = mapped_column(ForeignKey("eb_bets.id"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class EBEvaluation(Base):
    """Post-match scoring of an Engine B prediction (kept apart so predictions stay fully immutable)."""

    __tablename__ = "eb_evaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("eb_predictions.id"), unique=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    metrics: Mapped[dict] = mapped_column(JSON)


class EBValidationRun(Base):
    __tablename__ = "eb_validation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    model: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON)
    results: Mapped[dict] = mapped_column(JSON)


# --------------------------------------------------------------------------- operations
class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    period_start: Mapped[datetime] = mapped_column(DateTime)
    period_end: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    content: Mapped[dict] = mapped_column(JSON)
    markdown: Mapped[str] = mapped_column(Text)


class SystemLog(Base):
    __tablename__ = "system_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(8))
    component: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    params: Mapped[dict] = mapped_column(JSON)
    results: Mapped[dict] = mapped_column(JSON)


# --------------------------------------------------------------------------- immutability triggers
IMMUTABLE = {
    "predictions": [
        "fixture_id", "model_version_id", "created_at", "kickoff_utc", "revision", "revision_of",
        "probs", "component_probs", "exp_home_goals", "exp_away_goals", "confidence", "data_quality",
        "quality_breakdown", "decision", "explanation", "inputs", "inputs_hash", "sources",
    ],
    "value_assessments": None,  # fully immutable
    "virtual_bets": [
        "prediction_id", "value_assessment_id", "fixture_id", "model_version_id", "market", "selection",
        "line", "price", "bookmaker", "stake", "potential_return", "model_prob", "ev", "created_at", "kickoff_utc",
    ],
    "settlements": None,
    "bankroll_transactions": None,
    "eb_predictions": None,
    "eb_live_snapshots": None,
    "eb_live_events": None,
    "eb_settlements": None,
    "eb_bankroll_transactions": None,
    "eb_evaluations": None,
    "eb_bets": [
        "prediction_id", "fixture_id", "model_version_id", "mode", "market", "selection", "line", "price",
        "bookmaker", "odds_observation_id", "stake", "model_prob", "market_prob", "ev", "reason", "data_quality",
        "created_at", "kickoff_utc",
    ],
    "odds_observations": [
        "fixture_id", "source", "bookmaker", "kind", "retrieved_at", "home", "draw", "away",
        "over25", "under25", "ah_line", "ah_home", "ah_away", "content_hash",
    ],
}


def _install_triggers(conn) -> None:
    for table, cols in IMMUTABLE.items():
        conn.execute(text(
            f"CREATE TRIGGER IF NOT EXISTS trg_{table}_nodelete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} records are immutable (delete blocked)'); END;"
        ))
        of = f" OF {', '.join(cols)}" if cols else ""
        conn.execute(text(
            f"CREATE TRIGGER IF NOT EXISTS trg_{table}_noupdate BEFORE UPDATE{of} ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} core fields are immutable'); END;"
        ))
    # settled bets may not be re-settled
    conn.execute(text(
        "CREATE TRIGGER IF NOT EXISTS trg_bets_no_resettle BEFORE UPDATE OF status ON virtual_bets "
        "WHEN OLD.status != 'pending' "
        "BEGIN SELECT RAISE(ABORT, 'settled bets cannot be changed'); END;"
    ))
    conn.execute(text(
        "CREATE TRIGGER IF NOT EXISTS trg_eb_bets_no_resettle BEFORE UPDATE OF status ON eb_bets "
        "WHEN OLD.status != 'pending' BEGIN SELECT RAISE(ABORT, 'settled bets cannot be changed'); END;"
    ))
    # Settled-bet results are frozen (council QA-1). Closing price / CLV may be filled exactly once after
    # settlement (late closing odds); any later change is blocked.
    for tbl, short in (("virtual_bets", "bets"), ("eb_bets", "eb_bets")):
        conn.execute(text(
            f"CREATE TRIGGER IF NOT EXISTS trg_{short}_settled_frozen BEFORE UPDATE OF settled_at, payout, profit ON {tbl} "
            f"WHEN OLD.status != 'pending' BEGIN SELECT RAISE(ABORT, 'settled bet results are immutable'); END;"
        ))
        conn.execute(text(
            f"CREATE TRIGGER IF NOT EXISTS trg_{short}_clv_once BEFORE UPDATE OF closing_price, clv ON {tbl} "
            f"WHEN OLD.status != 'pending' AND (OLD.closing_price IS NOT NULL OR OLD.clv IS NOT NULL) "
            f"BEGIN SELECT RAISE(ABORT, 'closing price / CLV of a settled bet can only be filled once'); END;"
        ))
    conn.execute(text(
        "CREATE TRIGGER IF NOT EXISTS trg_eb_bets_prekickoff BEFORE INSERT ON eb_bets "
        "WHEN NEW.mode = 'prematch' AND NEW.created_at >= NEW.kickoff_utc "
        "BEGIN SELECT RAISE(ABORT, 'pre-match bets must be created before kickoff'); END;"
    ))
    # a bet can only be created before kickoff
    conn.execute(text(
        "CREATE TRIGGER IF NOT EXISTS trg_bets_prekickoff BEFORE INSERT ON virtual_bets "
        "WHEN NEW.created_at >= NEW.kickoff_utc "
        "BEGIN SELECT RAISE(ABORT, 'bets must be created before kickoff'); END;"
    ))


# --------------------------------------------------------------------------- engine/session
_engine = None
_Session: sessionmaker | None = None


def _json_ser(o):
    return json.dumps(o, default=str)


def get_engine(db_path=None):
    global _engine, _Session
    if _engine is None or db_path is not None:
        path = db_path or settings.db_path
        if str(path) != ":memory:":
            from pathlib import Path

            Path(path).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{path}", json_serializer=_json_ser, future=True,
                                connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(_engine, "connect")
        def _pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def init_db(db_path=None):
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        _install_triggers(conn)
    return engine


# log() called while a session_scope is open used to open a SECOND session. If the outer one already held SQLite's
# write lock, the inner write waited the full 30 s timeout and the error was swallowed: the line was lost and the
# job stalled (council cycle 2026-11-26 12:50: 30 s per overdue result, 0 'collect' log rows ever). Log lines
# written inside an open scope are now buffered and persisted right after the outermost scope closes (with their
# event time). Known limit: buffered lines are lost if the process dies while the scope is open.
_scope_state = threading.local()


def _depth() -> int:
    return getattr(_scope_state, "depth", 0)


@contextmanager
def session_scope() -> Iterator[Session]:
    if _Session is None:
        init_db()
    s = _Session()
    _scope_state.depth = _depth() + 1
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
        _scope_state.depth = _depth() - 1
        if _scope_state.depth == 0 and getattr(_scope_state, "pending", None):
            _flush_logs()


def _flush_logs() -> None:
    pending, _scope_state.pending = _scope_state.pending, []
    try:
        s = _Session()
        try:
            s.add_all([SystemLog(level=lv, component=c, message=m, ts=ts) for lv, c, m, ts in pending])
            s.commit()
        finally:
            s.close()
    except Exception:  # logging must never break the pipeline
        pass


def log(level: str, component: str, message: str) -> None:
    """Persist a log line (never include secrets in `message`)."""
    import logging

    from .security import redact

    message = redact(message)
    logging.getLogger(f"fil.{component}").log(getattr(logging, level.upper(), 20), message)
    if _depth() > 0:  # inside an open scope: persist after it closes (never wait on our own write lock)
        if not hasattr(_scope_state, "pending") or _scope_state.pending is None:
            _scope_state.pending = []
        _scope_state.pending.append((level.upper(), component, message[:4000], utcnow()))  # event time, not flush time
        return
    try:
        with session_scope() as s:
            s.add(SystemLog(level=level.upper(), component=component, message=message[:4000]))
    except Exception:  # logging must never break the pipeline
        pass
