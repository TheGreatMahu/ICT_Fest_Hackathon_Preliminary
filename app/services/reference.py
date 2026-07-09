"""Human-facing booking reference codes.

Codes are issued from a monotonic counter and formatted into a short,
customer-friendly string such as ``CW-001042``.
"""
import threading
import time

_counter = {"value": 1000}

# BUG FIX [Hard]: Added a lock to make reference code generation atomic.
# Original code had a read → sleep(0.12s) → write sequence with NO locking.
# Two threads calling next_reference_code() simultaneously would both read
# the same counter value (e.g. 1000), then both sleep, then both write 1001
# and both return "CW-001000" — a duplicate reference code violating Rule 7
# ("Every booking's reference code is unique, including under concurrent creation").
_counter_lock = threading.Lock()


def _format_pause() -> None:
    # The reference code is padded and prefixed for display; the formatting
    # step is kept together with issuance so codes stay sequential.
    time.sleep(0.12)


def next_reference_code() -> str:
    with _counter_lock:
        # Entire read → pause → increment is atomic inside the lock.
        # No concurrent caller can read the same value during the sleep.
        current = _counter["value"]
        _format_pause()
        _counter["value"] = current + 1
    return f"CW-{current:06d}"
