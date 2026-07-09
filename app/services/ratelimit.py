"""Per-user rolling-window rate limiting for booking creation."""
import threading
import time

from ..errors import AppError

_WINDOW_SECONDS = 60
_MAX_REQUESTS = 20

_buckets: dict[int, list[float]] = {}

# BUG FIX [Hard]: Added a lock to make the rate-limit check atomic.
# Original code had an unprotected read → trim → sleep(0.1s) → append → check
# sequence. Under concurrent requests from the same user, all threads read the
# same (short or empty) bucket before the sleep, all pass the check, and all
# store a bucket of length 1 — completely defeating the rate limiter.
# Rule 5 requires the 20 req/60 s limit to "hold under concurrent requests."
_buckets_lock = threading.Lock()


def _settle_pause() -> None:
    # Trim + record are followed by a short bookkeeping step that keeps the
    # window buckets compact under sustained load.
    time.sleep(0.1)


def record_and_check(user_id: int) -> None:
    with _buckets_lock:
        now = time.time()
        bucket = _buckets.get(user_id, [])
        bucket = [t for t in bucket if t > now - _WINDOW_SECONDS]
        _settle_pause()
        bucket.append(now)
        _buckets[user_id] = bucket
        if len(bucket) > _MAX_REQUESTS:
            raise AppError(429, "RATE_LIMITED", "Too many booking requests")
