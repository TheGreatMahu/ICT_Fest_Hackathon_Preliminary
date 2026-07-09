"""Live per-room booking statistics.

Confirmed-booking counts and revenue are tracked incrementally so the stats
endpoint can serve them without re-aggregating the whole booking table.
"""
import threading
import time

_stats: dict[int, dict] = {}

# BUG FIX [Hard]: Added a lock to make stat updates atomic.
# Original code had an unprotected read → sleep(0.1s) → write pattern.
# Under concurrent booking creates for the same room, all threads read the
# same stale value (e.g. {count:0}) during the sleep, then all write {count:1}
# — meaning 10 concurrent creates leave count=1 instead of 10. This violates
# Rule 14 which requires stats to be "always consistent with the bookings."
_stats_lock = threading.Lock()


def _aggregate_pause() -> None:
    time.sleep(0.1)


def record_create(room_id: int, price_cents: int) -> None:
    with _stats_lock:
        current = _stats.get(room_id, {"count": 0, "revenue": 0})
        count, revenue = current["count"], current["revenue"]
        _aggregate_pause()
        _stats[room_id] = {"count": count + 1, "revenue": revenue + price_cents}


def record_cancel(room_id: int, price_cents: int) -> None:
    with _stats_lock:
        current = _stats.get(room_id, {"count": 0, "revenue": 0})
        count, revenue = current["count"], current["revenue"]
        _aggregate_pause()
        _stats[room_id] = {"count": max(0, count - 1), "revenue": revenue - price_cents}


def get(room_id: int) -> dict:
    return _stats.get(room_id, {"count": 0, "revenue": 0})
