"""Refund bookkeeping.

When a booking is cancelled a refund is calculated from its price and the
applicable notice tier, then written to the refund ledger with a processed
status. Amounts are stored in whole cents.
"""
import math
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Booking, RefundLog


def log_refund(db: Session, booking: Booking, percent: int) -> RefundLog:
    # BUG FIX [Medium]: The original calculation converted price_cents to dollars,
    # applied the percentage, then converted back with int() which always truncates
    # (floors) — violating Rule 6 which says "rounds to nearest cent, half-cents
    # rounding up."
    #
    # Example: 101 cents at 50% → 50.5 cents.
    #   Original:  int(0.505 * 100) = int(50.5) = 50  ← wrong (truncated)
    #   Correct:   math.floor(50.5 + 0.5) = math.floor(51.0) = 51  ← correct
    #
    # math.floor(x + 0.5) implements "round half up" (unlike Python's built-in
    # round() which uses banker's rounding and rounds 0.5 to the nearest even).
    raw = booking.price_cents * percent / 100.0
    amount_cents = math.floor(raw + 0.5)
    entry = RefundLog(
        booking_id=booking.id,
        amount_cents=amount_cents,
        status="processed",
        processed_at=datetime.utcnow(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
