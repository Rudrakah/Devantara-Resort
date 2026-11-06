from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from backend.app.models import Booking, Room, RoomAvailability


def stay_dates(days=10):
    start = date.today() + timedelta(days=days)
    return start.isoformat(), (start + timedelta(days=2)).isoformat()


def booking_payload(room_id, check_in, check_out, **overrides):
    return {
        "room_id": room_id,
        "check_in": check_in,
        "check_out": check_out,
        "adults": 2,
        "children": 0,
        "guest_name": "Test Guest",
        "guest_email": "guest@example.com",
        "guest_phone": "+911234567890",
        **overrides,
    }


def test_availability_uses_database_rates_and_capacity(client, sessions, room_id):
    check_in, check_out = stay_dates()
    override_date = date.fromisoformat(check_in)
    with sessions() as db:
        db.add(RoomAvailability(room_id=room_id, stay_date=override_date, price_override=Decimal("7200")))
        db.commit()

    response = client.get(
        "/api/availability",
        params={"check_in": check_in, "check_out": check_out, "adults": 2, "children": 1},
    )
    assert response.status_code == 200
    rooms = response.json()
    assert len(rooms) == 1
    assert Decimal(rooms[0]["total_amount"]) == Decimal("12200")
    assert rooms[0]["nights"] == 2
    too_many = client.get(
        "/api/availability",
        params={"check_in": check_in, "check_out": check_out, "adults": 5, "children": 0},
    )
    assert too_many.status_code == 200
    assert too_many.json() == []


def test_booking_price_is_server_calculated_and_double_booking_prevented(client, sessions, room_id):
    check_in, check_out = stay_dates()
    with sessions() as db:
        db.add(RoomAvailability(room_id=room_id, stay_date=date.fromisoformat(check_in), price_override=Decimal("7200")))
        db.commit()
    payload = booking_payload(room_id, check_in, check_out, total_amount=1, nightly_rate=1)
    first = client.post("/api/bookings", json=payload)
    assert first.status_code == 201
    booking = first.json()
    assert Decimal(booking["total_amount"]) == Decimal("12200")
    assert Decimal(booking["nightly_rate"]) == Decimal("6100")
    assert booking["status"] == "pending_payment"
    assert booking["payment_status"] == "pending"
    assert len(booking["booking_ref"]) == 32

    duplicate = client.post("/api/bookings", json=payload)
    assert duplicate.status_code == 409
    with sessions() as db:
        records = db.scalars(select(Booking)).all()
        assert len(records) == 1
        assert records[0].guest_email == "guest@example.com"


def test_inventory_checked_for_each_night(sessions, room_id, client):
    check_in = date.today() + timedelta(days=20)
    with sessions() as db:
        room = db.get(Room, room_id)
        room.inventory = 2
        db.add_all(
            [
                Booking(
                    booking_ref="a" * 32,
                    room_id=room_id,
                    guest_name="Guest One",
                    guest_email="one@example.com",
                    guest_phone="123456789",
                    check_in=check_in,
                    check_out=check_in + timedelta(days=1),
                    adults=1,
                    children=0,
                    nights=1,
                    nightly_rate=5000,
                    total_amount=5000,
                    status="confirmed",
                    payment_status="paid",
                    expires_at=None,
                ),
                Booking(
                    booking_ref="b" * 32,
                    room_id=room_id,
                    guest_name="Guest Two",
                    guest_email="two@example.com",
                    guest_phone="123456789",
                    check_in=check_in + timedelta(days=1),
                    check_out=check_in + timedelta(days=2),
                    adults=1,
                    children=0,
                    nights=1,
                    nightly_rate=5000,
                    total_amount=5000,
                    status="confirmed",
                    payment_status="paid",
                    expires_at=None,
                ),
            ]
        )
        db.commit()
    check_out = check_in + timedelta(days=2)
    response = client.get(
        "/api/availability",
        params={"check_in": check_in.isoformat(), "check_out": check_out.isoformat(), "adults": 1},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_expired_payment_holds_do_not_consume_inventory(client, sessions, room_id):
    check_in, check_out = stay_dates()
    with sessions() as db:
        db.add(
            Booking(
                booking_ref="c" * 32,
                room_id=room_id,
                guest_name="Expired Guest",
                guest_email="expired@example.com",
                guest_phone="123456789",
                check_in=date.fromisoformat(check_in),
                check_out=date.fromisoformat(check_out),
                adults=1,
                children=0,
                nights=2,
                nightly_rate=5000,
                total_amount=10000,
                status="pending_payment",
                payment_status="pending",
                expires_at=datetime.utcnow() - timedelta(minutes=1),
            )
        )
        db.commit()
    response = client.get("/api/availability", params={"check_in": check_in, "check_out": check_out})
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_invalid_dates_and_closed_nights_are_rejected(client, sessions, room_id):
    check_in, check_out = stay_dates()
    invalid = client.get("/api/availability", params={"check_in": check_out, "check_out": check_in})
    assert invalid.status_code == 422
    past = client.get(
        "/api/availability",
        params={"check_in": "2020-01-01", "check_out": "2020-01-02"},
    )
    assert past.status_code == 422
    with sessions() as db:
        db.add(RoomAvailability(room_id=room_id, stay_date=date.fromisoformat(check_in), is_closed=True))
        db.commit()
    assert client.get("/api/availability", params={"check_in": check_in, "check_out": check_out}).json() == []


def test_guest_can_view_and_cancel_booking(client, room_id):
    check_in, check_out = stay_dates()
    created = client.post("/api/bookings", json=booking_payload(room_id, check_in, check_out))
    reference = created.json()["booking_ref"]
    wrong_email = client.get(f"/api/bookings/{reference}", params={"email": "other@example.com"})
    assert wrong_email.status_code == 404
    fetched = client.get(f"/api/bookings/{reference}", params={"email": "guest@example.com"})
    assert fetched.status_code == 200
    canceled = client.post(
        f"/api/bookings/{reference}/cancel",
        params={"email": "guest@example.com"},
    )
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "cancelled"


def test_concurrent_requests_cannot_double_book_one_unit(client, room_id):
    check_in, check_out = stay_dates(days=40)
    payloads = [
        booking_payload(room_id, check_in, check_out, guest_name=f"Guest {index}", guest_email=f"guest{index}@example.com")
        for index in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda value: client.post("/api/bookings", json=value), payloads))
    assert sorted(response.status_code for response in responses) == [201, 409]
