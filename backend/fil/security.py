"""Secret handling: secrets come only from environment variables and are redacted everywhere.

* `secret_values()` — current non-empty values of every secret env var (never stored elsewhere).
* `redact(text)`  — replaces any secret value (and auth header values) with "***".
* `install_log_redaction()` — wraps the logging record factory so EVERY log record (ours, httpx,
  uvicorn, APScheduler) is redacted before any handler sees it.
"""
from __future__ import annotations

import logging
import os
import re

SECRET_ENV_VARS = ("FOOTBALL_DATA_ORG_KEY", "ODDS_API_KEY", "API_FOOTBALL_KEY", "FIL_ADMIN_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
_HEADER_RE = re.compile(r"(?i)(x-auth-token|x-apisports-key|authorization|x-admin-token)(['\"]?\s*[:=]\s*['\"]?)"
                        r"((?:bearer|token|basic)\s+)?([^\s'\",}]+)")
_QUERY_RE = re.compile(r"(?i)(apiKey|api_key|token)=([^&\s'\"]+)")


def secret_values() -> list[str]:
    vals = [os.environ.get(k, "").strip() for k in SECRET_ENV_VARS]
    from .config import settings

    vals += [settings.football_data_org_key, settings.odds_api_key, settings.api_football_key, settings.admin_token]
    return sorted({v for v in vals if v and len(v) >= 6}, key=len, reverse=True)


def redact(text) -> str:
    if text is None:
        return text
    s = str(text)
    for v in secret_values():
        s = s.replace(v, "***")
    s = _HEADER_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3) or ''}***", s)
    s = _QUERY_RE.sub(lambda m: f"{m.group(1)}=***", s)
    return s


_installed = False


def install_log_redaction() -> None:
    global _installed
    if _installed:
        return
    old = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        rec = old(*args, **kwargs)
        try:
            msg = rec.getMessage()
        except Exception:
            return rec
        red = redact(msg)
        if red != msg or rec.args:
            rec.msg, rec.args = red, ()
        if rec.exc_text:
            rec.exc_text = redact(rec.exc_text)
        return rec

    logging.setLogRecordFactory(factory)
    _installed = True


install_log_redaction()  # active as soon as the package is imported
