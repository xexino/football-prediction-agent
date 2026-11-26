"""Provider adapter base: HTTP with caching, retries, rate limiting and status tracking."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from ..config import settings
from ..db import DataSource, log, session_scope
from ..timeutil import utcnow

USER_AGENT = "FootballIntelligenceLab/1.0 (research simulation; non-commercial)"


CIRCUIT_THRESHOLD = 3      # consecutive failed runs before the provider is skipped
CIRCUIT_COOLDOWN_H = 6
RATE_LIMIT_MAX_PAUSE_S = 130  # TheSportsDB locks out ~120 s after a 429
PROVIDER_DOWN_S = 300  # after a request failed all attempts on 5xx/network errors


class ProviderError(Exception):
    pass


class CircuitOpen(ProviderError):
    pass


class NotConfigured(ProviderError):
    pass


@dataclass
class FetchResult:
    text: str
    url: str
    retrieved_at: datetime
    from_cache: bool = False
    headers: dict = field(default_factory=dict)


def error_kind(message: str) -> str:
    """Classify a provider failure so the dashboard never presents an outage as 'no data'."""
    m = (message or "").lower()
    if "not configured" in m or "missing" in m and "key" in m:
        return "missing_credentials"
    if "429" in m or "rate limit" in m or "quota" in m:
        return "rate_limited"
    if "malformed" in m or "json" in m or "parse" in m or "unexpected" in m or "invalid response" in m:
        return "invalid_response"
    if "401" in m or "403" in m or "access denied" in m or "token" in m or "invalid key" in m:
        return "auth_failed"
    return "unavailable"


class Provider:
    _RATE: dict = {}  # provider key -> {"last": epoch of last request, "cooldown": epoch before which none is sent}

    @property
    def _last_request(self) -> float:
        return Provider._RATE.setdefault(self.key, {}).get("last", 0.0)

    @_last_request.setter
    def _last_request(self, v: float) -> None:
        Provider._RATE.setdefault(self.key, {})["last"] = v

    @property
    def _down_until(self) -> float:
        return Provider._RATE.setdefault(self.key, {}).get("down", 0.0)

    @_down_until.setter
    def _down_until(self, v: float) -> None:
        Provider._RATE.setdefault(self.key, {})["down"] = v

    def _stale(self, cpath, req, url: str, why: str) -> "FetchResult":
        self.stale_served = getattr(self, "stale_served", 0) + 1  # reported as DEGRADED, never as a clean success
        log("WARNING", f"provider.{self.key}", f"serving stale cache for {self.redact(url)}: {why}")
        return FetchResult(cpath.read_text(encoding="utf-8"), self.redact(str(req.url)),
                           datetime.fromtimestamp(cpath.stat().st_mtime, timezone.utc).replace(tzinfo=None), from_cache=True)

    @property
    def _cooldown_until(self) -> float:
        return Provider._RATE.setdefault(self.key, {}).get("cooldown", 0.0)

    @_cooldown_until.setter
    def _cooldown_until(self, v: float) -> None:
        Provider._RATE.setdefault(self.key, {})["cooldown"] = v

    key: str = "base"
    name: str = "Base"
    kind: str = ""
    base_url: str = ""
    license_note: str = ""
    requires_key: bool = False
    reliability: str = "medium"
    min_interval_s: float = 1.0  # polite spacing between requests
    cache_ttl_s: int = 3600

    def __init__(self):
        # request spacing / 429 cool-down are shared by every instance of the same provider (collect.provider()
        # builds a new instance per call; a fresh instance must not fire straight after another one's 429)
        self.cache_dir: Path = settings.cache_dir / self.key
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ config
    @property
    def configured(self) -> bool:
        return True

    def register(self) -> None:
        with session_scope() as s:
            ds = s.query(DataSource).filter_by(key=self.key).one_or_none()
            if ds is None:
                ds = DataSource(key=self.key)
                s.add(ds)
            ds.name, ds.kind, ds.base_url = self.name, self.kind, self.base_url
            ds.license_note, ds.requires_key, ds.reliability = self.license_note, self.requires_key, self.reliability
            if self.configured:
                ds.configured = True
            else:
                # processes without the secret (dashboard export, local tools) must not mark a provider that
                # synced successfully in the last 3 days as unconfigured
                recent = ds.last_success_at is not None and utcnow() - ds.last_success_at < timedelta(days=3)
                ds.configured = bool(recent and ds.configured)
                if not ds.configured:
                    ds.status = "not_configured"

    def _mark(self, ok: bool, error: str | None = None, quota: dict | None = None, records: int = 0, requests: int = 0):
        with session_scope() as s:
            ds = s.query(DataSource).filter_by(key=self.key).one_or_none()
            if ds is None:
                return
            now = utcnow()
            ds.last_attempt_at = now
            ds.requests_total = (ds.requests_total or 0) + requests
            ds.records_total = (ds.records_total or 0) + records
            info = dict(ds.quota_info or {})
            if quota:
                info.update(quota)
            circ = dict(info.get("circuit") or {"failures": 0, "open_until": None})
            if ok:
                ds.last_success_at = now
                circ = {"failures": 0, "open_until": None}
                stale = getattr(self, "stale_served", 0)
                if stale:  # data came (partly) from an old cache because the provider refused or failed
                    ds.status, ds.last_error_at = "degraded", now
                    ds.last_error = f"{stale} request(s) answered from stale cache (provider rate-limited or unavailable)"
                    info["last_error_kind"] = "rate_limited" if "429" in str(getattr(self, "_last_exc", "")) else "unavailable"
                    self.stale_served = 0
                else:
                    ds.status = "ok"
            else:
                from ..security import redact

                ds.status, ds.last_error_at, ds.last_error = "error", now, redact(error or "")[:1000]
                info["last_error_kind"] = error_kind(error or "")
                circ["failures"] = circ.get("failures", 0) + 1
                if circ["failures"] >= CIRCUIT_THRESHOLD:
                    circ["open_until"] = (now + timedelta(hours=CIRCUIT_COOLDOWN_H)).isoformat()
            info["circuit"] = circ
            ds.quota_info = info

    def circuit_open(self) -> bool:
        with session_scope() as s:
            ds = s.query(DataSource).filter_by(key=self.key).one_or_none()
            until = ((ds.quota_info or {}).get("circuit") or {}).get("open_until") if ds else None
        return bool(until and datetime.fromisoformat(until) > utcnow())

    def mark_success(self, records: int = 0, requests: int = 0, quota: dict | None = None):
        self._mark(True, records=records, requests=requests, quota=quota)

    def mark_error(self, error: str, requests: int = 0):
        self._mark(False, error=error, requests=requests)
        log("WARNING", f"provider.{self.key}", error)

    # ------------------------------------------------------------------ http
    def headers(self) -> dict:
        return {"User-Agent": USER_AGENT}

    def redact(self, url: str) -> str:
        return url

    def get(self, url: str, params: dict | None = None, ttl: int | None = None, retries: int = 3) -> FetchResult:
        ttl = self.cache_ttl_s if ttl is None else ttl
        req = httpx.Request("GET", url, params=params)
        cache_key = hashlib.sha1(str(req.url).encode()).hexdigest()
        cpath = self.cache_dir / cache_key
        if ttl > 0 and cpath.exists() and time.time() - cpath.stat().st_mtime < ttl:
            return FetchResult(cpath.read_text(encoding="utf-8"), self.redact(str(req.url)),
                               datetime.fromtimestamp(cpath.stat().st_mtime, timezone.utc).replace(tzinfo=None), from_cache=True)
        # A provider that is down or rate-limited is not hammered: council cycle 2026-11-26 18:50 measured
        # 16 x HTTP 522 retried URL after URL (6.5 min) and a fixed ~120 s 429 lock-out probed three times.
        # While blocked, an URL we already have is answered from the (stale, reported) cache at once.
        blocked = max(self._down_until, self._cooldown_until) - time.time()
        if blocked > 0 and cpath.exists():
            return self._stale(cpath, req, url, "provider down or rate-limited — request skipped")
        if self._down_until > time.time():
            raise ProviderError(f"{self.key} marked down after repeated server/network errors; request skipped")
        last_exc: Exception | None = None
        transient = False  # last failure was a 5xx / network error (not a 429)
        for attempt in range(retries):
            wait = max(self.min_interval_s - (time.time() - self._last_request),
                       self._cooldown_until - time.time())
            if wait > 0:
                time.sleep(wait)
            try:
                self._last_request = time.time()
                with httpx.Client(timeout=45, follow_redirects=True, headers=self.headers()) as c:
                    r = c.get(url, params=params)
                if r.status_code == 429:
                    self._last_exc = "429"
                    try:
                        retry_after = float(r.headers.get("Retry-After", "0") or 0)
                    except ValueError:  # an HTTP-date Retry-After: use our own back-off
                        retry_after = 0.0
                    # the lock-out is ~120 s (Retry-After counts down from it); never probe it repeatedly
                    self._cooldown_until = time.time() + min(max(retry_after, 2 ** attempt * 5), RATE_LIMIT_MAX_PAUSE_S)
                    last_exc, transient = ProviderError(f"rate limited (429) at {self.redact(str(r.url))}"), False
                    if cpath.exists():
                        break  # an old answer now beats a 2-minute wait
                    continue  # the next attempt waits out the cool-down (loop top)
                if r.status_code in (401, 403):
                    raise ProviderError(f"HTTP {r.status_code}: access denied for {self.redact(str(r.url))}")
                if r.status_code >= 500:
                    last_exc, transient = ProviderError(f"HTTP {r.status_code} at {self.redact(str(r.url))}"), True
                    if attempt < retries - 1:
                        time.sleep(2 ** attempt)
                    continue
                if r.status_code >= 400:
                    raise ProviderError(f"HTTP {r.status_code} at {self.redact(str(r.url))}")
                text = r.content.decode("utf-8-sig", errors="replace")
                cpath.write_text(text, encoding="utf-8")
                return FetchResult(text, self.redact(str(r.url)), utcnow(), headers=dict(r.headers))
            except httpx.HTTPError as exc:  # network failure: retry, then fall back to stale cache
                last_exc, transient = exc, True
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        if transient:  # all attempts failed on server/network errors: the provider is down for a while
            self._down_until = time.time() + PROVIDER_DOWN_S
        if cpath.exists():
            return self._stale(cpath, req, url, f"network failure: {last_exc}")
        raise ProviderError(f"request failed after {retries} attempts: {type(last_exc).__name__}: {last_exc}")
