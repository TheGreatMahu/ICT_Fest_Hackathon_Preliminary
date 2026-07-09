"""Helpers for parsing input datetimes and rendering UTC responses."""
from datetime import datetime, timezone


def parse_input_datetime(value: str) -> datetime:
    """Parse an ISO 8601 datetime into a naive UTC datetime for storage.

    Inputs that carry a UTC offset are normalized to UTC; naive inputs are
    treated as UTC as-is.
    """
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        # BUG FIX [Easy]: The original code used dt.replace(tzinfo=None) which
        # strips the timezone info WITHOUT converting the time value to UTC.
        # For example, "14:00+05:30" would be stored as 14:00 UTC instead of
        # the correct 08:30 UTC — a 5.5-hour error.
        # Fix: call .astimezone(timezone.utc) first to shift the clock to UTC,
        # THEN strip tzinfo so the stored datetime is naive UTC.
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def iso_utc(dt: datetime) -> str:
    """Render a stored (naive UTC) datetime with an explicit UTC designator."""
    return dt.replace(tzinfo=timezone.utc).isoformat()
