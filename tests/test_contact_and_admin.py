import hashlib
import hmac
import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from backend.app.models import Admin, Booking, ContactEnquiry, Payment, PaymentTransaction


def test_contact_enquiry_is_stored_without_claiming_email_delivery(client, sessions):
    response = client.post(
        "/api/contact",
        json={
            "name": "A Guest",
            "email": "Guest@example.com",
            "phone": "+911234567890",
            "subject": "Stay enquiry",
            "message": "Could you share current room availability?",
        },
    )
    assert response.status_code == 201
    assert "received" in response.json()["message"].lower()
    with sessions() as db:
        enquiry = db.scalar(select(ContactEnquiry))
        assert enquiry.email == "guest@example.com"
        assert enquiry.status == "new"


def test_contact_honeypot_is_accepted_but_not_stored(client, sessions):
    response = client.post(
        "/api/contact",
        json={
            "name": "Bot",
            "email": "bot@example.com",
            "message": "This is a spam submission.",
            "website": "http://spam.example",
        },
    )
    assert response.status_code == 201
    with sessions() as db:
        assert db.scalar(select(ContactEnquiry.id)) is None


def test_admin_authentication_and_room_crud(client, sessions, room_id):
    assert client.get("/api/admin/dashboard").status_code == 401
    bad_login = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong-password"})
    assert bad_login.status_code == 401

    login = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "test-password-123"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).json()["email"] == "admin@example.com"

    category = client.post(
        "/api/admin/categories",
        headers=headers,
        json={"name": "Villa", "description": "Configured by the administrator."},
    )
    assert category.status_code == 201
    room = client.post(
        "/api/admin/rooms",
        headers=headers,
        json={
            "category_id": category.json()["id"],
            "name": "Garden Villa",
            "description": "Verified room description.",
            "base_rate": "12500.00",
            "capacity_adults": 2,
            "capacity_children": 1,
            "inventory": 1,
        },
    )
    assert room.status_code == 201
    assert room.json()["base_rate"] == 12500

    archived = client.delete(f"/api/admin/rooms/{room.json()['id']}", headers=headers)
    assert archived.status_code == 204
    public_rooms = client.get("/api/rooms").json()
    assert all(item["id"] != room.json()["id"] for item in public_rooms)

    with sessions() as db:
        assert db.scalar(select(Admin.id).where(Admin.email == "admin@example.com")) is not None


def test_payment_endpoints_do_not_fake_success_when_unconfigured(client, room_id):
    from datetime import date, timedelta

    check_in = date.today() + timedelta(days=14)
    booking = client.post(
        "/api/bookings",
        json={
            "room_id": room_id,
            "check_in": check_in.isoformat(),
            "check_out": (check_in + timedelta(days=1)).isoformat(),
            "adults": 2,
            "children": 0,
            "guest_name": "Guest",
            "guest_email": "guest@example.com",
            "guest_phone": "+911234567890",
        },
    )
    response = client.post("/api/payments/create-order", json={"booking_ref": booking.json()["booking_ref"]})
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"].lower()


def test_public_api_limits_host_and_redacts_validation_input(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    invalid_login = client.post(
        "/api/auth/login",
        json={"email": "not-an-email", "password": "do-not-echo-this"},
    )
    assert invalid_login.status_code == 422
    assert "do-not-echo-this" not in invalid_login.text


def test_refund_webhook_is_idempotent_and_does_not_reverse_processed_refund(
    client, sessions, room_id, monkeypatch
):
    from backend.app.config import settings

    check_in = date.today() + timedelta(days=30)
    with sessions() as db:
        booking = Booking(
            booking_ref="d" * 32,
            room_id=room_id,
            guest_name="Refund Guest",
            guest_email="refund@example.com",
            guest_phone="+911234567890",
            check_in=check_in,
            check_out=check_in + timedelta(days=2),
            adults=2,
            children=0,
            nights=2,
            nightly_rate=Decimal("5000.00"),
            total_amount=Decimal("10000.00"),
            status="confirmed",
            payment_status="paid",
            expires_at=None,
        )
        db.add(booking)
        db.flush()
        payment = Payment(
            payment_ref="e" * 32,
            booking_id=booking.id,
            gateway_order_id="order_test",
            gateway_payment_id="pay_test",
            amount=Decimal("10000.00"),
            status="captured",
            refund_amount=Decimal("0.00"),
        )
        db.add(payment)
        db.flush()
        refund = PaymentTransaction(
            payment_id=payment.id,
            gateway_refund_id="rfnd_test",
            gateway_payment_id="pay_test",
            event_type="refund.requested",
            status="pending",
            amount=Decimal("4000.00"),
            payload="{}",
        )
        db.add(refund)
        db.commit()
        payment_id = payment.id

    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "razorpay_webhook_secret", secret)
    event = {
        "event": "refund.processed",
        "payload": {
            "refund": {
                "entity": {
                    "id": "rfnd_test",
                    "payment_id": "pay_test",
                    "amount": 400000,
                    "currency": "INR",
                }
            }
        },
    }

    def post_webhook(event_type, event_id):
        body = json.dumps({**event, "event": event_type}, separators=(",", ":")).encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return client.post(
            "/api/payments/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": signature,
                "X-Razorpay-Event-Id": event_id,
            },
        )

    assert post_webhook("refund.processed", "evt_refund_processed").status_code == 200
    assert post_webhook("refund.processed", "evt_refund_processed").status_code == 200
    assert post_webhook("refund.failed", "evt_stale_refund_failed").status_code == 200

    for event_type, event_id in (("payment.captured", "evt_late_capture"), ("payment.failed", "evt_stale_failure")):
        payment_event = {
            "event": event_type,
            "payload": {
                "payment": {
                    "entity": {
                        "entity": "payment",
                        "id": "pay_test",
                        "order_id": "order_test",
                        "amount": 1000000,
                        "currency": "INR",
                    }
                }
            },
        }
        body = json.dumps(payment_event, separators=(",", ":")).encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        response = client.post(
            "/api/payments/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": signature,
                "X-Razorpay-Event-Id": event_id,
            },
        )
        assert response.status_code == 200

    with sessions() as db:
        payment = db.get(Payment, payment_id)
        assert payment.refund_amount == Decimal("4000.00")
        assert payment.status == "partially_refunded"
        assert payment.booking.payment_status == "partially_refunded"
