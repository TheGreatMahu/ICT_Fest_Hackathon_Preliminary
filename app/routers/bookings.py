"""Booking creation, listing, detail and cancellation."""
import threading
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import cache
from ..auth import get_current_user
from ..database import get_db
from ..errors import AppError
from ..models import Booking, Room, User
from ..schemas import BookingCreateRequest
from ..serializers import serialize_booking
from ..services import notifications, ratelimit, reference, stats
from ..services.refunds import log_refund
from ..timeutils import iso_utc, parse_input_datetime

router = APIRouter(tags=["bookings"])

MIN_DURATION_HOURS = 1
MAX_DURATION_HOURS = 8
QUOTA_LIMIT = 3
QUOTA_WINDOW_HOURS = 24

# BUG FIX [Hard]: Locks to serialize concurrent booking creation and cancellation.
# Without these, concurrent requests race through check→sleep→act windows and
# bypass conflict detection, quota limits, and duplicate-cancel guards.
_booking_lock = threading.Lock()
_cancel_lock = threading.Lock()


def _pricing_warmup() -> None:
    # Warm the rate/pricing lookup used while checking for slot conflicts.
    time.sleep(0.12)


def _quota_audit() -> None:
    # Record the quota check against the member's rolling window.
    time.sleep(0.1)


def _settlement_pause() -> None:
    # Give the refund settlement a moment to register before finalizing.
    time.sleep(0.12)


def _has_conflict(db: Session, room_id: int, start: datetime, end: datetime) -> bool:
    existing = (
        db.query(Booking)
        .filter(Booking.room_id == room_id, Booking.status == "confirmed")
        .all()
    )
    _pricing_warmup()
    for b in existing:
        # BUG FIX [Medium]: Original condition was b.start_time <= end and start <= b.end_time.
        # Using <= on both sides means a booking whose start equals an existing booking's end
        # (i.e. back-to-back) was incorrectly flagged as a conflict. Rule 3 states:
        # "Back-to-back bookings are allowed." The correct overlap condition uses strict <.
        if b.start_time < end and start < b.end_time:
            return True
    return False


def _check_quota(db: Session, user_id: int, now: datetime, start: datetime) -> None:
    window_end = now + timedelta(hours=QUOTA_WINDOW_HOURS)
    if not (now < start <= window_end):
        return
    count = (
        db.query(Booking)
        .filter(
            Booking.user_id == user_id,
            Booking.status == "confirmed",
            Booking.start_time > now,
            Booking.start_time <= window_end,
        )
        .count()
    )
    _quota_audit()
    if count >= QUOTA_LIMIT:
        raise AppError(409, "QUOTA_EXCEEDED", "Booking quota exceeded")


@router.post("/bookings", status_code=201)
def create_booking(
    payload: BookingCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ratelimit.record_and_check(user.id)

    start = parse_input_datetime(payload.start_time)
    end = parse_input_datetime(payload.end_time)
    now = datetime.utcnow()

    # BUG FIX [Easy]: end must be strictly after start (Rule 2).
    if end <= start:
        raise AppError(400, "INVALID_BOOKING_WINDOW", "end_time must be after start_time")

    # BUG FIX [Easy]: Original code allowed start times up to 5 minutes in the past
    # by subtracting timedelta(seconds=300) from now. Rule 2 says "start_time must be
    # strictly in the future at request time — no grace window."
    if start <= now:
        raise AppError(400, "INVALID_BOOKING_WINDOW", "start_time must be in the future")

    duration_hours = (end - start).total_seconds() / 3600
    if duration_hours != int(duration_hours):
        raise AppError(400, "INVALID_BOOKING_WINDOW", "duration must be a whole number of hours")
    duration_hours = int(duration_hours)
    # BUG FIX [Easy]: Original code only checked the upper bound (> MAX_DURATION_HOURS).
    # Rule 2 specifies minimum 1 hour. A 0-hour booking (or negative) was accepted.
    if duration_hours < MIN_DURATION_HOURS or duration_hours > MAX_DURATION_HOURS:
        raise AppError(400, "INVALID_BOOKING_WINDOW", "duration out of range")

    room = db.query(Room).filter(Room.id == payload.room_id, Room.org_id == user.org_id).first()
    if room is None:
        raise AppError(404, "ROOM_NOT_FOUND", "Room not found")

    # BUG FIX [Hard]: The conflict check, quota check, and INSERT must be atomic.
    # Without a lock, two concurrent requests both pass the conflict check during
    # the _pricing_warmup() sleep (0.12 s window), then both insert — creating a
    # double-booked room or over-quota bookings (Rules 3, 4).
    with _booking_lock:
        if _has_conflict(db, room.id, start, end):
            raise AppError(409, "ROOM_CONFLICT", "Room already booked for this interval")

        _check_quota(db, user.id, now, start)

        price_cents = room.hourly_rate_cents * duration_hours
        booking = Booking(
            room_id=room.id,
            user_id=user.id,
            start_time=start,
            end_time=end,
            status="confirmed",
            reference_code=reference.next_reference_code(),
            price_cents=price_cents,
            created_at=now,
        )
        db.add(booking)
        db.commit()
        db.refresh(booking)

    stats.record_create(room.id, price_cents)
    cache.invalidate_availability(room.id, start.date().isoformat())
    notifications.notify_created(booking)

    return serialize_booking(booking)


@router.get("/bookings")
def list_bookings(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    base = db.query(Booking).filter(Booking.user_id == user.id)
    total = base.count()
    items = (
        # BUG FIX [Easy] x3: Three bugs in this query:
        # 1. order_by used .desc() — spec (Rule 11) requires ascending by start_time.
        # 2. .offset(page * limit) — page 1 skipped the first `limit` rows. Correct
        #    formula is (page - 1) * limit so page=1 starts at offset 0.
        # 3. .limit(10) — hardcoded, ignoring the caller-supplied `limit` parameter.
        base.order_by(Booking.start_time.asc(), Booking.id.asc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return {
        "items": [serialize_booking(b) for b in items],
        "page": page,
        "limit": limit,
        "total": total,
    }


@router.get("/bookings/{booking_id}")
def get_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    booking = (
        db.query(Booking)
        .join(Room, Booking.room_id == Room.id)
        .filter(Booking.id == booking_id, Room.org_id == user.org_id)
        .first()
    )
    if booking is None:
        raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found")
    # BUG FIX [Easy]: Members may only read their own bookings (Rule 10).
    # The join already scopes to the user's org, but a member could still read
    # another member's booking id. Return 404 (not 403) to avoid leaking existence.
    if user.role != "admin" and booking.user_id != user.id:
        raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found")

    response = serialize_booking(booking)
    # BUG FIX [Easy]: Original code overwrote response["start_time"] with
    # iso_utc(booking.created_at), replacing the correct start_time value that
    # serialize_booking() had already set correctly.  Line removed entirely.
    response["refunds"] = [
        {
            "amount_cents": r.amount_cents,
            "status": r.status,
            "processed_at": iso_utc(r.processed_at),
        }
        for r in booking.refunds
    ]
    return response


@router.post("/bookings/{booking_id}/cancel")
def cancel_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    booking = (
        db.query(Booking)
        .join(Room, Booking.room_id == Room.id)
        .filter(Booking.id == booking_id, Room.org_id == user.org_id)
        .first()
    )
    if booking is None:
        raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found")
    if user.role != "admin" and booking.user_id != user.id:
        raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found")

    # BUG FIX [Hard]: Without a lock, two concurrent cancel requests for the same
    # booking both read status=="confirmed", both pass the ALREADY_CANCELLED check,
    # both write a RefundLog, and both set status="cancelled" — leaving two refund
    # entries for one booking (Rule 6: "exactly one RefundLog entry").
    # db.refresh() inside the lock re-reads from DB to get the latest committed status.
    with _cancel_lock:
        db.refresh(booking)
        if booking.status == "cancelled":
            raise AppError(409, "ALREADY_CANCELLED", "Booking already cancelled")

        now = datetime.utcnow()
        notice = booking.start_time - now
        # BUG FIX [Medium]: Original code used integer-truncated hours and strict >.
        # Two problems:
        # (a) int(notice.total_seconds() // 3600) truncates — exactly 48 h would
        #     give notice_hours=48 but notice_hours > 48 is False → wrong 50% tier.
        # (b) The final else branch returned refund_percent = 50, not 0.
        # Rule 6: >=48h→100%, >=24h→50%, <24h→0%.
        if notice >= timedelta(hours=48):
            refund_percent = 100
        elif notice >= timedelta(hours=24):
            refund_percent = 50
        else:
            # BUG FIX [Medium]: Was 50 — must be 0 for notice < 24 hours (Rule 6).
            refund_percent = 0

        refund_amount_cents = round(booking.price_cents * (refund_percent / 100.0))

        log_refund(db, booking, refund_percent)

        _settlement_pause()
        booking.status = "cancelled"
        db.commit()

    stats.record_cancel(booking.room_id, booking.price_cents)
    cache.invalidate_report(user.org_id)
    notifications.notify_cancelled(booking)

    return {
        "id": booking.id,
        "status": "cancelled",
        "refund_percent": refund_percent,
        "refund_amount_cents": refund_amount_cents,
    }
