"""Time helpers. Internally everything is naive UTC; display is Europe/Rome."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
ROME = ZoneInfo("Europe/Rome")
LONDON = ZoneInfo("Europe/London")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def to_utc_naive(dt: datetime, assume_tz=UTC) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=assume_tz)
    return dt.astimezone(UTC).replace(tzinfo=None)


def local_to_utc(date_str: str, time_str: str | None, tz=LONDON, date_fmt: str = "%d/%m/%Y") -> datetime:
    """Convert a provider's local date/time (default UK time, as used by football-data.co.uk) to naive UTC."""
    time_str = (time_str.strip() if isinstance(time_str, str) else "") or "15:00"  # NaN/None -> default
    fmt = date_fmt + " %H:%M"
    try:
        dt = datetime.strptime(f"{date_str.strip()} {time_str}", fmt)
    except ValueError:
        # two-digit years appear in older files
        dt = datetime.strptime(f"{date_str.strip()} {time_str}", fmt.replace("%Y", "%y"))
    return to_utc_naive(dt.replace(tzinfo=tz))


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def rome(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC).astimezone(ROME).strftime("%Y-%m-%d %H:%M")
