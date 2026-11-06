from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.booking_service import is_available, quote_total
from backend.app.database import get_db
from backend.app.models import Amenity, Booking, GalleryImage, Package, Review, Room, RoomAvailability, RoomCategory
from backend.app.schemas import AvailableRoom, ReviewCreate, RoomOut


router = APIRouter(prefix="/api", tags=["rooms and availability"])


def _room_out(room: Room) -> dict:
    return {
        "id": room.id,
        "category_id": room.category_id,
        "category_name": room.category.name,
        "name": room.name,
        "description": room.description,
        "base_rate": room.base_rate,
        "capacity_adults": room.capacity_adults,
        "capacity_children": room.capacity_children,
        "inventory": room.inventory,
        "amenities": room.amenities,
        "image_url": room.image_url,
    }


@router.get("/rooms", response_model=list[RoomOut])
def list_rooms(db: Session = Depends(get_db)):
    rooms = db.scalars(
        select(Room)
        .options(joinedload(Room.category))
        .where(Room.is_active.is_(True))
        .order_by(Room.id)
    ).all()
    return [_room_out(room) for room in rooms]


@router.get("/rooms/{room_id}", response_model=RoomOut)
def get_room(room_id: int, db: Session = Depends(get_db)):
    room = db.scalar(
        select(Room)
        .options(joinedload(Room.category))
        .where(Room.id == room_id, Room.is_active.is_(True))
    )
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    return _room_out(room)


@router.get("/amenities")
def public_amenities(db: Session = Depends(get_db)):
    rows = db.scalars(select(Amenity).where(Amenity.is_active.is_(True)).order_by(Amenity.id)).all()
    return [{"id": row.id, "name": row.name, "description": row.description, "icon": row.icon} for row in rows]


@router.get("/packages")
def public_packages(db: Session = Depends(get_db)):
    today = date.today()
    rows = db.scalars(
        select(Package)
        .where(
            Package.is_active.is_(True),
            ((Package.starts_on.is_(None)) | (Package.starts_on <= today)),
            ((Package.ends_on.is_(None)) | (Package.ends_on >= today)),
        )
        .order_by(Package.id)
    ).all()
    return [
        {"id": row.id, "name": row.name, "description": row.description, "price": row.price}
        for row in rows
    ]


@router.get("/gallery")
def public_gallery(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(GalleryImage)
        .where(GalleryImage.is_published.is_(True))
        .order_by(GalleryImage.sort_order, GalleryImage.id)
    ).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "image_url": row.image_url,
            "category": row.category,
            "alt_text": row.alt_text,
        }
        for row in rows
    ]


@router.get("/reviews")
def public_reviews(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Review)
        .where(Review.is_published.is_(True))
        .order_by(Review.created_at.desc())
        .limit(50)
    ).all()
    return [
        {"guest_name": row.guest_name, "rating": row.rating, "comment": row.comment, "created_at": row.created_at}
        for row in rows
    ]


@router.post("/reviews", status_code=201)
def create_review(payload: ReviewCreate, db: Session = Depends(get_db)):
    booking = db.scalar(
        select(Booking).where(
            Booking.booking_ref == payload.booking_ref,
            Booking.guest_email == str(payload.email).lower(),
            Booking.status == "confirmed",
        )
    )
    if booking is None:
        raise HTTPException(status_code=404, detail="Confirmed booking not found.")
    if db.scalar(select(Review.id).where(Review.booking_id == booking.id)):
        raise HTTPException(status_code=409, detail="A review has already been submitted for this booking.")
    review = Review(
        user_id=booking.user_id,
        booking_id=booking.id,
        guest_name=booking.guest_name,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return {"id": review.id, "status": "pending_moderation"}


@router.get("/availability", response_model=list[AvailableRoom])
def get_availability(
    check_in: date = Query(...),
    check_out: date = Query(...),
    adults: int = Query(default=2, ge=1, le=50),
    children: int = Query(default=0, ge=0, le=50),
    db: Session = Depends(get_db),
):
    if check_out <= check_in:
        raise HTTPException(status_code=422, detail="Check-out must be after check-in.")
    if (check_out - check_in).days > 365:
        raise HTTPException(status_code=422, detail="A stay cannot be longer than 365 nights.")
    today = date.today()
    if check_in < today:
        raise HTTPException(status_code=422, detail="Check-in cannot be in the past.")

    rooms = db.scalars(
        select(Room)
        .options(joinedload(Room.category))
        .where(
            Room.is_active.is_(True),
            Room.capacity_adults >= adults,
            Room.capacity_children >= children,
        )
    ).all()
    matching = []
    for room in rooms:
        if not is_available(db, room, check_in, check_out):
            continue
        nights = (check_out - check_in).days
        total = quote_total(db, room, check_in, check_out)
        matching.append({**_room_out(room), "nights": nights, "total_amount": total})
    return matching
