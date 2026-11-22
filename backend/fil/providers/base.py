"""Provider adapter base: HTTP with caching, retries, rate limiting and status tracking."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

from ..config import settings
from ..db import DataSource, log, session_scope
from ..timeutil import utcnow

USER_AGENT = "FootballIntelligenceLab/1.0 (research simulation; non-commercial)"


class ProviderError(Exception):
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


class Provider:
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
        self._last_request = 0.0
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
            ds.configured = self.configured
            if not self.configured:
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
            if quota:
                ds.quota_info = quota
            if ok:
                ds.status, ds.last_success_at = "ok", now
            else:
                ds.status, ds.last_error_at, ds.last_error = "error", now, (error or "")[:1000]

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
                               datetime.utcfromtimestamp(cpath.stat().st_mtime), from_cache=True)
        last_exc: Exception | None = None
        for attempt in range(retries):
            wait = self.min_interval_s - (time.time() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                self._last_request = time.time()
                with httpx.Client(timeout=45, follow_redirects=True, headers=self.headers()) as c:
                    r = c.get(url, params=params)
                if r.status_code == 429:
                    retry_after = float(r.headers.get("Retry-After", "0") or 0)
                    time.sleep(min(max(retry_after, 2 ** attempt * 2), 60))
                    last_exc = ProviderError(f"rate limited (429) at {self.redact(str(r.url))}")
                    continue
                if r.status_code in (401, 403):
                    raise ProviderError(f"HTTP {r.status_code}: access denied for {self.redact(str(r.url))}")
                if r.status_code >= 500:
                    last_exc = ProviderError(f"HTTP {r.status_code} at {self.redact(str(r.url))}")
                    time.sleep(2 ** attempt)
                    continue
                if r.status_code >= 400:
                    raise ProviderError(f"HTTP {r.status_code} at {self.redact(str(r.url))}")
                text = r.content.decode("utf-8-sig", errors="replace")
                cpath.write_text(text, encoding="utf-8")
                return FetchResult(text, self.redact(str(r.url)), utcnow(), headers=dict(r.headers))
            except httpx.HTTPError as exc:  # network failure: retry, then fall back to stale cache
                last_exc = exc
                time.sleep(2 ** attempt)
        if cpath.exists():
            log("WARNING", f"provider.{self.key}", f"network failure, serving stale cache for {self.redact(url)}: {last_exc}")
            return FetchResult(cpath.read_text(encoding="utf-8"), self.redact(str(req.url)),
                               datetime.utcfromtimestamp(cpath.stat().st_mtime), from_cache=True)
        raise ProviderError(f"request failed after {retries} attempts: {type(last_exc).__name__}: {last_exc}")
