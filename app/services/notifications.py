"""Side effects that accompany booking lifecycle events.

Each booking change sends a (simulated) notification email and appends an
audit-log entry. Both operations are guarded by a single shared lock to
prevent the deadlock that the original two-lock design produced.
"""
import threading
import time

# BUG FIX [Hard]: The original code used two separate locks (_email_lock and
# _audit_lock) that were acquired in OPPOSITE ORDER in the two functions:
#
#   notify_created()   → acquires _email_lock THEN _audit_lock  (A → B)
#   notify_cancelled() → acquires _audit_lock THEN _email_lock  (B → A)
#
# This is a classic AB/BA deadlock. When one thread calls notify_created() and
# another simultaneously calls notify_cancelled(), thread 1 holds A and waits
# for B while thread 2 holds B and waits for A — both block forever, hanging
# the service (violates Rule 16: "no combination of concurrent valid requests
# may hang the service").
#
# Fix: replace the two locks with a single _notification_lock. Since there is
# now only one lock, there is no ordering to invert and deadlock is impossible.
_notification_lock = threading.Lock()


def _send_email(kind: str, booking) -> None:
    # Simulated SMTP round-trip.
    time.sleep(0.12)


def _write_audit(kind: str, booking) -> None:
    # Simulated audit-log formatting/flush.
    time.sleep(0.1)


def notify_created(booking) -> None:
    with _notification_lock:
        _send_email("created", booking)
        _write_audit("created", booking)


def notify_cancelled(booking) -> None:
    with _notification_lock:
        _write_audit("cancelled", booking)
        _send_email("cancelled", booking)
