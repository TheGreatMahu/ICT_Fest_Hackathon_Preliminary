"""In-memory response caches for read-heavy reporting endpoints.

Usage reports and per-room availability are relatively expensive to compute and
are read far more often than the underlying data changes, so results are cached
and invalidated when the data they depend on is modified.
"""

_report_cache: dict[tuple, dict] = {}
_availability_cache: dict[tuple, dict] = {}


def get_report(org_id: int, frm: str, to: str):
    # BUG FIX [Medium]: Returning stale cached data violated Rules 12 and 13 which
    # both require results to "reflect the current state immediately."
    # Example: admin cancels a booking, then immediately calls GET /admin/usage-report —
    # the cached response still showed the booking as confirmed.
    # The cancellation path calls invalidate_report() but only after the commit, and
    # the cache could have been populated between two requests in the same window.
    # Simplest correct fix: never serve from cache (always return None = cache miss),
    # so every read goes to the database.
    return None


def set_report(org_id: int, frm: str, to: str, value: dict) -> None:
    # No-op: caching disabled to satisfy Rule 12 (must reflect current state immediately).
    pass


def invalidate_report(org_id: int) -> None:
    for key in [k for k in _report_cache if k[0] == org_id]:
        _report_cache.pop(key, None)


def get_availability(room_id: int, date: str):
    # BUG FIX [Medium]: Same reasoning as get_report — Rule 13 requires availability
    # to reflect the current state immediately. A confirmed booking that was just
    # cancelled would still appear as busy in the cached response.
    return None


def set_availability(room_id: int, date: str, value: dict) -> None:
    # No-op: caching disabled to satisfy Rule 13.
    pass


def invalidate_availability(room_id: int, date: str) -> None:
    _availability_cache.pop((room_id, date), None)
