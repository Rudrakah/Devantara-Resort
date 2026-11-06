import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.app.booking_service import is_available, quote_total
from backend.app.config import settings
from backend.app.database import get_db
from backend.app.email_service import booking_email, booking_status_email, send_email
from backend.app.models import Booking, BookingGuest, Room, User
from backend.app.schemas import BookingCreate, BookingOut


router = APIRouter(prefix="/api/bookings", tags=["bookings"])


def _out(booking: Booking) -> dict:
    return {
        "booking_ref": booking.booking_ref,
        "room_id": booking.room_id,
        "room_name": booking.room.name,
        "guest_name": booking.guest_name,
        "guest_email": booking.guest_email,
        "check_in": booking.check_in,
        "check_out": booking.check_out,
        "adults": booking.adults,
        "children": booking.children,
        "nights": booking.nights,
        "nightly_rate": booking.nightly_rate,
        "total_amount": booking.total_amount,
        "status": booking.status,
        "payment_status": booking.payment_status,
        "expires_at": booking.expires_at,
    }


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def create_booking(
    payload: BookingCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if payload.check_in < date.today():
        raise HTTPException(status_code=422, detail="Check-in cannot be in the past.")

    room = db.scalar(
        select(Room)
        .options(joinedload(Room.category))
        .where(Room.id == payload.room_id, Room.is_active.is_(True))
        .with_for_update()
    )
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    if payload.adults > room.capacity_adults or payload.children > room.capacity_children:
        raise HTTPException(status_code=422, detail="Guest count exceeds this room's capacity.")

    now = datetime.utcnow()
    if not is_available(db, room, payload.check_in, payload.check_out, now):
        raise HTTPException(status_code=409, detail="This room is no longer available for the selected dates.")

    nights = (payload.check_out - payload.check_in).days
    amount = quote_total(db, room, payload.check_in, payload.check_out)
    email = str(payload.guest_email).lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(name=payload.guest_name, email=email, phone=payload.guest_phone)
        db.add(user)
        db.flush()
    else:
        user.name = payload.guest_name
        user.phone = payload.guest_phone

    reference = uuid.uuid4().hex
    booking = Booking(
        booking_ref=reference,
        room_id=room.id,
        user_id=user.id,
        guest_name=payload.guest_name,
        guest_email=email,
        guest_phone=payload.guest_phone,
        check_in=payload.check_in,
        check_out=payload.check_out,
        adults=payload.adults,
        children=payload.children,
        nights=nights,
        nightly_rate=(amount / nights).quantize(Decimal("0.01")),
        total_amount=amount,
        status="pending_payment",
        payment_status="pending",
        expires_at=now + timedelta(minutes=settings.booking_hold_minutes),
    )
    booking.guests.append(BookingGuest(name=payload.guest_name, guest_type="adult"))
    db.add(booking)
    db.commit()
    db.refresh(booking)
    html_body, text_body = booking_email(
        booking.booking_ref,
        booking.guest_name,
        room.name,
        booking.check_in.isoformat(),
        booking.check_out.isoformat(),
        f"{booking.total_amount:.2f}",
    )
    background_tasks.add_task(
        send_email,
        booking.guest_email,
        f"Booking request received · {settings.resort_name}",
        html_body,
        text_body,
    )
    return _out(booking)


@router.get("/{booking_ref}", response_model=BookingOut)
def get_booking(
    booking_ref: str,
    email: str = Query(..., min_length=5, max_length=254),
    db: Session = Depends(get_db),
):
    booking = db.scalar(
        select(Booking)
        .options(joinedload(Booking.room))
        .where(Booking.booking_ref == booking_ref, Booking.guest_email == email.lower())
    )
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    return _out(booking)


@router.post("/{booking_ref}/cancel")
def cancel_booking(
    booking_ref: str,
    background_tasks: BackgroundTasks,
    email: str = Query(..., min_length=5, max_length=254),
    db: Session = Depends(get_db),
):
    booking = db.scalar(
        select(Booking)
        .options(joinedload(Booking.room))
        .where(Booking.booking_ref == booking_ref, Booking.guest_email == email.lower())
        .with_for_update()
    )
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if booking.status == "cancelled":
        return {"booking_ref": booking.booking_ref, "status": "cancelled"}
    if booking.status not in {"pending_payment", "confirmed"}:
        raise HTTPException(status_code=409, detail="This booking can no longer be cancelled.")
    booking.status = "cancelled"
    booking.cancellation_reason = "Cancelled by guest."
    booking.updated_at = datetime.utcnow()
    db.commit()
    html_body, text_body = booking_status_email(
        booking.guest_name,
        booking.booking_ref,
        "Your booking request was cancelled",
        "If a payment was captured, contact the resort to arrange a refund.",
    )
    background_tasks.add_task(
        send_email,
        booking.guest_email,
        f"Booking cancelled · {settings.resort_name}",
        html_body,
        text_body,
    )
    return {
        "booking_ref": booking.booking_ref,
        "status": booking.status,
        "payment_status": booking.payment_status,
        "message": "Booking cancelled. Any captured payment requires separate refund processing by the resort.",
    }
