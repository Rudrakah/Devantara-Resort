from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import Booking, Room, RoomAvailability


def nightly_price(db: Session, room: Room, stay_date: date) -> Decimal:
    override = db.scalar(
        select(RoomAvailability.price_override).where(
            RoomAvailability.room_id == room.id,
            RoomAvailability.stay_date == stay_date,
        )
    )
    return override if override is not None else room.base_rate


def is_available(
    db: Session,
    room: Room,
    check_in: date,
    check_out: date,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.utcnow()
    closed_date = db.scalar(
        select(RoomAvailability.id).where(
            RoomAvailability.room_id == room.id,
            RoomAvailability.is_closed.is_(True),
            RoomAvailability.stay_date >= check_in,
            RoomAvailability.stay_date < check_out,
        ).limit(1)
    )
    if closed_date is not None:
        return False

    for offset in range((check_out - check_in).days):
        night = date.fromordinal(check_in.toordinal() + offset)
        occupied = db.scalar(
            select(func.count(Booking.id)).where(
                Booking.room_id == room.id,
                Booking.status.in_(("pending_payment", "confirmed")),
                Booking.check_in <= night,
                Booking.check_out > night,
                (
                    (Booking.status == "confirmed")
                    | ((Booking.expires_at.is_not(None)) & (Booking.expires_at > now))
                ),
            )
        ) or 0
        if occupied >= room.inventory:
            return False
    return True


def quote_total(db: Session, room: Room, check_in: date, check_out: date) -> Decimal:
    total = sum(
        (nightly_price(db, room, date.fromordinal(check_in.toordinal() + offset)) for offset in range((check_out - check_in).days)),
        Decimal("0.00"),
    )
    return total.quantize(Decimal("0.01"))
