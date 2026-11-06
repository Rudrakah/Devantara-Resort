from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)


class LoginRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class AdminOut(APIModel):
    id: int
    name: str
    email: EmailStr


class TokenOut(APIModel):
    access_token: str
    token_type: str = "bearer"
    admin: AdminOut


class RoomCreate(APIModel):
    category_id: int = Field(gt=0)
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=4000)
    base_rate: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    capacity_adults: int = Field(default=2, ge=1, le=50)
    capacity_children: int = Field(default=0, ge=0, le=50)
    inventory: int = Field(default=1, ge=1, le=500)
    amenities: str = Field(default="", max_length=2000)
    image_url: str = Field(default="", max_length=500)


class RoomUpdate(APIModel):
    category_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    base_rate: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    capacity_adults: int | None = Field(default=None, ge=1, le=50)
    capacity_children: int | None = Field(default=None, ge=0, le=50)
    inventory: int | None = Field(default=None, ge=1, le=500)
    amenities: str | None = Field(default=None, max_length=2000)
    image_url: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class RoomOut(APIModel):
    id: int
    category_id: int
    category_name: str
    name: str
    description: str
    base_rate: Decimal
    capacity_adults: int
    capacity_children: int
    inventory: int
    amenities: str
    image_url: str


class AvailabilityRequest(APIModel):
    check_in: date
    check_out: date
    adults: int = Field(default=2, ge=1, le=50)
    children: int = Field(default=0, ge=0, le=50)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.check_out <= self.check_in:
            raise ValueError("Check-out must be after check-in.")
        if (self.check_out - self.check_in).days > 365:
            raise ValueError("A stay cannot be longer than 365 nights.")
        return self


class AvailableRoom(RoomOut):
    nights: int
    total_amount: Decimal


class BookingCreate(AvailabilityRequest):
    room_id: int = Field(gt=0)
    guest_name: str = Field(min_length=2, max_length=120)
    guest_email: EmailStr
    guest_phone: str = Field(min_length=7, max_length=32)


class BookingOut(APIModel):
    booking_ref: str
    room_id: int
    room_name: str
    guest_name: str
    guest_email: EmailStr
    check_in: date
    check_out: date
    adults: int
    children: int
    nights: int
    nightly_rate: Decimal
    total_amount: Decimal
    status: str
    payment_status: str
    expires_at: datetime | None


class ContactCreate(APIModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(default="", max_length=32)
    subject: str = Field(default="Website enquiry", max_length=160)
    message: str = Field(min_length=5, max_length=5000)
    website: str = Field(default="", max_length=200)


class ContactOut(APIModel):
    id: int
    name: str
    email: EmailStr
    status: str
    created_at: datetime


class EnquiryStatusUpdate(APIModel):
    status: str = Field(pattern="^(new|in_progress|responded|archived)$")


class BookingCancellation(APIModel):
    reason: str = Field(default="", max_length=500)


class AvailabilityUpdate(APIModel):
    room_id: int = Field(gt=0)
    start_date: date
    end_date: date
    is_closed: bool
    price_override: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date.")
        if (self.end_date - self.start_date).days > 730:
            raise ValueError("Availability updates are limited to two years at a time.")
        return self


class CreateCategory(APIModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)


class ContentCreate(APIModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=2000)
    icon: str = Field(default="", max_length=80)
    is_active: bool = True


class AmenityUpdate(APIModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=80)
    is_active: bool | None = None


class PackageCreate(APIModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=2000)
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    is_active: bool = True
    starts_on: date | None = None
    ends_on: date | None = None

    @model_validator(mode="after")
    def validate_package_dates(self):
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("Package end date must be on or after its start date.")
        return self


class PackageUpdate(APIModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    is_active: bool | None = None
    starts_on: date | None = None
    ends_on: date | None = None


class GalleryCreate(APIModel):
    title: str = Field(min_length=2, max_length=120)
    image_url: str = Field(min_length=1, max_length=500)
    category: str = Field(default="stay", max_length=64)
    alt_text: str = Field(default="", max_length=250)
    sort_order: int = Field(default=0, ge=0)
    is_published: bool = False


class GalleryUpdate(APIModel):
    title: str | None = Field(default=None, min_length=2, max_length=120)
    image_url: str | None = Field(default=None, min_length=1, max_length=500)
    category: str | None = Field(default=None, max_length=64)
    alt_text: str | None = Field(default=None, max_length=250)
    sort_order: int | None = Field(default=None, ge=0)
    is_published: bool | None = None


class PaymentOrderRequest(APIModel):
    booking_ref: str = Field(min_length=16, max_length=32)


class PaymentVerifyRequest(APIModel):
    booking_ref: str = Field(min_length=16, max_length=32)
    razorpay_order_id: str = Field(min_length=4, max_length=120)
    razorpay_payment_id: str = Field(min_length=4, max_length=120)
    razorpay_signature: str = Field(min_length=16, max_length=256)


class RefundRequest(APIModel):
    amount: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    reason: str = Field(default="", max_length=255)


class ReviewCreate(APIModel):
    booking_ref: str = Field(min_length=16, max_length=32)
    email: EmailStr
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=3000)
