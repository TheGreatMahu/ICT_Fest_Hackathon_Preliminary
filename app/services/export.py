"""CSV export of bookings for administrators."""
import csv
import io

from sqlalchemy.orm import Session

from ..models import Booking, Room
from ..timeutils import iso_utc

EXPORT_HEADER = [
    "id",
    "reference_code",
    "room_id",
    "user_id",
    "start_time",
    "end_time",
    "status",
    "price_cents",
]


def _fetch_scoped(db: Session, org_id: int, user_id: int | None, room_id: int | None) -> list[Booking]:
    query = db.query(Booking).join(Room).filter(Room.org_id == org_id)
    if user_id is not None:
        query = query.filter(Booking.user_id == user_id)
    if room_id is not None:
        query = query.filter(Booking.room_id == room_id)
    return query.order_by(Booking.id.asc()).all()


def generate_export(
    db: Session,
    org_id: int,
    user_id: int,
    room_id: int | None,
    include_all: bool,
) -> str:
    # BUG FIX [Medium]: Original code called fetch_bookings_raw(db, room_id) when
    # include_all=True AND room_id was provided. fetch_bookings_raw queries by
    # room_id ONLY — no org_id filter. An admin could request:
    #   GET /admin/export?include_all=true&room_id=<room_from_another_org>
    # and receive bookings belonging to a different organisation, violating the
    # multi-tenancy rule (Rule 9: "may only ever read … data belonging to their
    # own organization … Cross-org resource IDs behave as non-existent → 404").
    #
    # Fix: remove fetch_bookings_raw entirely. All paths go through _fetch_scoped
    # which always filters by org_id, enforcing tenant isolation.
    if include_all:
        rows = _fetch_scoped(db, org_id, None, room_id)
    else:
        rows = _fetch_scoped(db, org_id, user_id, room_id)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_HEADER)
    for b in rows:
        writer.writerow(
            [
                b.id,
                b.reference_code,
                b.room_id,
                b.user_id,
                iso_utc(b.start_time),
                iso_utc(b.end_time),
                b.status,
                b.price_cents,
            ]
        )
    return buffer.getvalue()
