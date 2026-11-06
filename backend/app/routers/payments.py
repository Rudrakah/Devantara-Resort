import json
import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.config import settings
from backend.app.database import get_db
from backend.app.email_service import booking_email, booking_status_email, send_email
from backend.app.models import Admin, AdminActivityLog, Booking, Payment, PaymentTransaction
from backend.app.payment_service import (
    compact_json,
    ensure_razorpay_configured,
    razorpay_request,
    to_paise,
    verify_checkout_signature,
    verify_webhook_signature,
)
from backend.app.schemas import PaymentOrderRequest, PaymentVerifyRequest, RefundRequest
from backend.app.security import require_admin


router = APIRouter(prefix="/api/payments", tags=["payments"])
admin_router = APIRouter(prefix="/api/admin/payments", tags=["admin payments"])


def _payment_for_booking(db: Session, booking: Booking) -> Payment:
    payment = db.scalar(select(Payment).where(Payment.booking_id == booking.id).with_for_update())
    if payment is None:
        payment = Payment(
            payment_ref=uuid.uuid4().hex,
            booking_id=booking.id,
            amount=booking.total_amount,
            currency="INR",
            status="pending",
        )
        db.add(payment)
        db.flush()
    return payment


def _confirm_payment(db: Session, payment: Payment, gateway_payment_id: str, payload: dict, event_id: str | None = None):
    booking = db.scalar(select(Booking).where(Booking.id == payment.booking_id).with_for_update())
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if payment.gateway_payment_id and payment.gateway_payment_id != gateway_payment_id:
        raise HTTPException(status_code=409, detail="A different payment is already linked to this booking.")
    if payment.gateway_payment_id == gateway_payment_id:
        return booking
    payment.gateway_payment_id = gateway_payment_id
    payment.status = "captured"
    booking.payment_status = "paid"
    can_confirm = booking.status == "pending_payment" and (
        booking.expires_at is None or booking.expires_at > datetime.utcnow()
    )
    if can_confirm:
        booking.status = "confirmed"
        booking.expires_at = None
    booking.updated_at = datetime.utcnow()
    db.add(
        PaymentTransaction(
            payment_id=payment.id,
            gateway_event_id=event_id,
            gateway_payment_id=gateway_payment_id,
            event_type="payment.captured",
            status="captured",
            amount=payment.amount,
            payload=compact_json(payload),
        )
    )
    db.flush()
    return booking


@router.post("/create-order")
def create_order(payload: PaymentOrderRequest, db: Session = Depends(get_db)):
    ensure_razorpay_configured()
    booking = db.scalar(
        select(Booking)
        .options(joinedload(Booking.room))
        .where(Booking.booking_ref == payload.booking_ref)
        .with_for_update()
    )
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if booking.status != "pending_payment" or booking.payment_status != "pending":
        raise HTTPException(status_code=409, detail="This booking is not awaiting payment.")
    if booking.expires_at is None or booking.expires_at <= datetime.utcnow():
        booking.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="This booking hold has expired. Check availability again.")

    payment = _payment_for_booking(db, booking)
    if payment.gateway_order_id:
        return {
            "key_id": settings.razorpay_key_id,
            "order_id": payment.gateway_order_id,
            "payment_ref": payment.payment_ref,
            "amount": to_paise(payment.amount),
            "currency": payment.currency,
            "name": settings.resort_name,
            "description": f"{booking.room.name} · {booking.nights} nights",
            "prefill": {"name": booking.guest_name, "email": booking.guest_email, "contact": booking.guest_phone},
        }

    order = razorpay_request(
        "POST",
        "/orders",
        json={
            "amount": to_paise(booking.total_amount),
            "currency": "INR",
            "receipt": booking.booking_ref[:40],
            "notes": {"booking_ref": booking.booking_ref},
        },
    )
    if not order.get("id") or order.get("amount") != to_paise(booking.total_amount):
        raise HTTPException(status_code=502, detail="Payment provider returned an invalid order.")
    payment.gateway_order_id = order["id"]
    payment.status = "created"
    db.add(
        PaymentTransaction(
            payment_id=payment.id,
            event_type="order.created",
            status="created",
            amount=payment.amount,
            payload=compact_json({"order_id": order["id"]}),
        )
    )
    db.commit()
    return {
        "key_id": settings.razorpay_key_id,
        "order_id": order["id"],
        "payment_ref": payment.payment_ref,
        "amount": to_paise(payment.amount),
        "currency": payment.currency,
        "name": settings.resort_name,
        "description": f"{booking.room.name} · {booking.nights} nights",
        "prefill": {"name": booking.guest_name, "email": booking.guest_email, "contact": booking.guest_phone},
    }


@router.post("/verify")
def verify_payment(
    payload: PaymentVerifyRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    ensure_razorpay_configured()
    booking = db.scalar(
        select(Booking)
        .options(joinedload(Booking.room))
        .where(Booking.booking_ref == payload.booking_ref)
        .with_for_update()
    )
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    payment = db.scalar(select(Payment).where(Payment.booking_id == booking.id).with_for_update())
    if payment is None or payment.gateway_order_id != payload.razorpay_order_id:
        raise HTTPException(status_code=400, detail="Payment order does not match this booking.")
    if not verify_checkout_signature(
        payload.razorpay_order_id,
        payload.razorpay_payment_id,
        payload.razorpay_signature,
    ):
        raise HTTPException(status_code=400, detail="Payment signature verification failed.")
    if payment.status == "captured":
        return {
            "booking_ref": booking.booking_ref,
            "booking_status": booking.status,
            "payment_status": payment.status,
            "message": (
                "Payment was received after the booking hold ended. Contact the resort to arrange a refund."
                if booking.status != "confirmed"
                else "Booking confirmed."
            ),
        }

    gateway_payment = razorpay_request("GET", f"/payments/{payload.razorpay_payment_id}")
    if gateway_payment.get("order_id") != payment.gateway_order_id:
        raise HTTPException(status_code=400, detail="Payment belongs to a different gateway order.")
    if gateway_payment.get("amount") != to_paise(payment.amount) or gateway_payment.get("currency") != payment.currency:
        raise HTTPException(status_code=400, detail="Payment amount or currency does not match the booking.")
    if gateway_payment.get("status") == "authorized":
        gateway_payment = razorpay_request(
            "POST",
            f"/payments/{payload.razorpay_payment_id}/capture",
            json={"amount": to_paise(payment.amount), "currency": payment.currency},
        )
    if gateway_payment.get("status") != "captured":
        payment.status = "failed" if gateway_payment.get("status") == "failed" else "pending"
        db.add(
            PaymentTransaction(
                payment_id=payment.id,
                gateway_payment_id=payload.razorpay_payment_id,
                event_type="payment.verification",
                status=str(gateway_payment.get("status", "unknown")),
                amount=payment.amount,
                payload=compact_json({"gateway_status": gateway_payment.get("status", "unknown")}),
            )
        )
        db.commit()
        if gateway_payment.get("status") == "failed":
            html_body, text_body = booking_status_email(
                booking.guest_name,
                booking.booking_ref,
                "Payment was not completed",
                "No booking has been confirmed. You can try again while the room hold remains active.",
            )
            background_tasks.add_task(
                send_email,
                booking.guest_email,
                f"Payment not completed · {settings.resort_name}",
                html_body,
                text_body,
            )
        raise HTTPException(status_code=409, detail="The gateway has not confirmed a captured payment.")

    booking = _confirm_payment(db, payment, payload.razorpay_payment_id, {"status": "captured"})
    db.commit()
    if booking.status != "confirmed":
        return {
            "booking_ref": booking.booking_ref,
            "booking_status": booking.status,
            "payment_status": payment.status,
            "message": "Payment was received after the booking hold ended. Contact the resort to arrange a refund.",
        }
    html_body, text_body = booking_email(
        booking.booking_ref,
        booking.guest_name,
        booking.room.name,
        booking.check_in.isoformat(),
        booking.check_out.isoformat(),
        f"{booking.total_amount:.2f}",
    )
    background_tasks.add_task(
        send_email,
        booking.guest_email,
        f"Booking confirmed · {settings.resort_name}",
        html_body.replace("We received your booking request", "Your booking is confirmed")
        .replace("This is a pending request, not a confirmed reservation. Your stay is confirmed only after verified payment.", "Your payment was verified and your stay is confirmed."),
        text_body.replace("We received booking request", "Your booking is confirmed")
        .replace("This is a pending request, not a confirmed reservation. Confirmation follows verified payment.", "Your payment was verified and your stay is confirmed."),
    )
    return {"booking_ref": booking.booking_ref, "booking_status": booking.status, "payment_status": payment.status}


@router.get("/{payment_ref}/status")
def payment_status(payment_ref: str, db: Session = Depends(get_db)):
    payment = db.scalar(
        select(Payment)
        .options(joinedload(Payment.booking))
        .where(Payment.payment_ref == payment_ref)
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return {
        "payment_ref": payment.payment_ref,
        "status": payment.status,
        "booking_ref": payment.booking.booking_ref,
        "booking_status": payment.booking.status,
    }


@router.post("/webhook")
async def payment_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_razorpay_signature: str | None = Header(default=None),
    x_razorpay_event_id: str | None = Header(default=None),
):
    body = await request.body()
    if not verify_webhook_signature(body, x_razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")
    try:
        event = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid webhook payload.") from None
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")

    event_type = event.get("event", "")
    if event_type in {"refund.processed", "refund.failed"}:
        payload = event.get("payload")
        refund_data = payload.get("refund") if isinstance(payload, dict) else None
        refund_entity = refund_data.get("entity") if isinstance(refund_data, dict) else None
        refund_entity = refund_entity if isinstance(refund_entity, dict) else {}
        refund_id = refund_entity.get("id")
        gateway_payment_id = refund_entity.get("payment_id")
        if not refund_id or not gateway_payment_id:
            raise HTTPException(status_code=400, detail="Refund webhook is missing its payment details.")
        refund_transaction = db.scalar(
            select(PaymentTransaction).where(PaymentTransaction.gateway_refund_id == refund_id).with_for_update()
        )
        if refund_transaction is None:
            raise HTTPException(status_code=404, detail="Refund request not found.")
        if x_razorpay_event_id and db.scalar(
            select(PaymentTransaction.id).where(PaymentTransaction.gateway_event_id == x_razorpay_event_id)
        ):
            return {"received": True, "processed": True}
        payment = db.scalar(select(Payment).where(Payment.id == refund_transaction.payment_id).with_for_update())
        if payment is None or payment.gateway_payment_id != gateway_payment_id:
            raise HTTPException(status_code=400, detail="Refund does not match the recorded payment.")
        if (
            refund_entity.get("amount") != to_paise(refund_transaction.amount)
            or refund_entity.get("currency") != payment.currency
        ):
            raise HTTPException(status_code=400, detail="Refund amount does not match the recorded request.")
        if event_type == "refund.processed" and refund_transaction.status != "processed":
            payment.refund_amount += refund_transaction.amount
            payment.status = "refunded" if payment.refund_amount == payment.amount else "partially_refunded"
            payment.booking.payment_status = "refunded" if payment.refund_amount == payment.amount else "partially_refunded"
            refund_transaction.status = "processed"
        elif event_type == "refund.failed" and refund_transaction.status != "processed":
            refund_transaction.status = "failed"
            payment.status = "captured" if payment.refund_amount == 0 else "partially_refunded"
            payment.booking.payment_status = "paid" if payment.refund_amount == 0 else "partially_refunded"
        refund_transaction.gateway_event_id = x_razorpay_event_id
        refund_transaction.payload = compact_json(event)
        db.commit()
        html_body, text_body = booking_status_email(
            payment.booking.guest_name,
            payment.booking.booking_ref,
            "Refund update" if event_type == "refund.processed" else "Refund could not be completed",
            (
                f"Refund of INR {refund_transaction.amount:.2f} was processed."
                if event_type == "refund.processed"
                else "Please contact the resort to resolve the refund."
            ),
        )
        background_tasks.add_task(
            send_email,
            payment.booking.guest_email,
            f"Refund update · {settings.resort_name}",
            html_body,
            text_body,
        )
        return {"received": True, "processed": True}
    if event_type not in {"payment.captured", "order.paid", "payment.failed"}:
        return {"received": True, "processed": False}
    payload = event.get("payload")
    payment_data = payload.get("payment") if isinstance(payload, dict) else None
    payment_entity = payment_data.get("entity") if isinstance(payment_data, dict) else None
    order_data = payload.get("order") if isinstance(payload, dict) else None
    order_entity = order_data.get("entity") if isinstance(order_data, dict) else None
    entity = payment_entity or order_entity or {}
    if not isinstance(entity, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")
    if event_type == "order.paid" and entity.get("entity") != "payment":
        return {"received": True, "processed": False}
    order_id = entity.get("order_id") or entity.get("id")
    payment_id = entity.get("id") if entity.get("entity") == "payment" else None
    if not order_id or not payment_id:
        raise HTTPException(status_code=400, detail="Webhook is missing its payment details.")
    if x_razorpay_event_id and db.scalar(
        select(PaymentTransaction.id).where(PaymentTransaction.gateway_event_id == x_razorpay_event_id)
    ):
        return {"received": True, "processed": True}
    payment = db.scalar(
        select(Payment)
        .options(joinedload(Payment.booking).joinedload(Booking.room))
        .where(Payment.gateway_order_id == order_id)
        .with_for_update()
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment order not found.")
    amount = entity.get("amount")
    if amount != to_paise(payment.amount) or entity.get("currency") != payment.currency:
        raise HTTPException(status_code=400, detail="Webhook payment amount or currency does not match.")
    if event_type == "payment.failed":
        if payment.status in {"captured", "partially_refunded", "refunded", "refund_pending"}:
            return {"received": True, "processed": True}
        payment.status = "failed"
        db.add(
            PaymentTransaction(
                payment_id=payment.id,
                gateway_event_id=x_razorpay_event_id,
                gateway_payment_id=payment_id,
                event_type="payment.failed",
                status="failed",
                amount=payment.amount,
                payload=compact_json(event),
            )
        )
        db.commit()
        html_body, text_body = booking_status_email(
            payment.booking.guest_name,
            payment.booking.booking_ref,
            "Payment was not completed",
            "No booking has been confirmed. You can try again while the room hold remains active.",
        )
        background_tasks.add_task(
            send_email,
            payment.booking.guest_email,
            f"Payment not completed · {settings.resort_name}",
            html_body,
            text_body,
        )
        return {"received": True, "processed": True}
    booking = _confirm_payment(db, payment, payment_id, event, x_razorpay_event_id)
    db.commit()
    if booking.status == "confirmed":
        html_body, text_body = booking_email(
            booking.booking_ref,
            booking.guest_name,
            booking.room.name,
            booking.check_in.isoformat(),
            booking.check_out.isoformat(),
            f"{booking.total_amount:.2f}",
        )
        background_tasks.add_task(
            send_email,
            booking.guest_email,
            f"Booking confirmed · {settings.resort_name}",
            html_body.replace("We received your booking request", "Your booking is confirmed")
            .replace(
                "This is a pending request, not a confirmed reservation. Your stay is confirmed only after verified payment.",
                "Your payment was verified and your stay is confirmed.",
            ),
            text_body.replace("We received booking request", "Your booking is confirmed")
            .replace(
                "This is a pending request, not a confirmed reservation. Confirmation follows verified payment.",
                "Your payment was verified and your stay is confirmed.",
            ),
        )
    return {"received": True, "processed": True}


@admin_router.get("")
def list_payments(
    limit: int = 100,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(require_admin),
):
    limit = min(max(limit, 1), 250)
    rows = db.scalars(select(Payment).options(joinedload(Payment.booking)).order_by(Payment.created_at.desc()).limit(limit)).all()
    return [
        {
            "payment_ref": row.payment_ref,
            "booking_ref": row.booking.booking_ref,
            "guest_name": row.booking.guest_name,
            "amount": row.amount,
            "status": row.status,
            "refund_amount": row.refund_amount,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@admin_router.post("/{payment_ref}/refund")
def refund_payment(
    payment_ref: str,
    payload: RefundRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_admin),
):
    ensure_razorpay_configured()
    payment = db.scalar(select(Payment).where(Payment.payment_ref == payment_ref).with_for_update())
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    if payment.status not in {"captured", "partially_refunded"} or not payment.gateway_payment_id:
        raise HTTPException(status_code=409, detail="Only captured payments can be refunded.")
    amount = payload.amount or payment.amount
    pending_refunds = db.scalar(
        select(func.coalesce(func.sum(PaymentTransaction.amount), 0)).where(
            PaymentTransaction.payment_id == payment.id,
            PaymentTransaction.event_type == "refund.requested",
            PaymentTransaction.status.in_(("pending", "created")),
        )
    ) or Decimal("0.00")
    if amount + payment.refund_amount + pending_refunds > payment.amount:
        raise HTTPException(status_code=422, detail="Refund exceeds the captured amount.")
    refund = razorpay_request(
        "POST",
        f"/payments/{payment.gateway_payment_id}/refund",
        json={"amount": to_paise(amount), "notes": {"reason": payload.reason[:255]}},
    )
    refund_status = str(refund.get("status", "pending"))
    if not refund.get("id"):
        raise HTTPException(status_code=502, detail="Payment provider did not return a refund reference.")
    if refund_status == "processed":
        payment.refund_amount += amount
        payment.status = "partially_refunded" if payment.refund_amount < payment.amount else "refunded"
        payment.booking.payment_status = "refunded" if payment.refund_amount == payment.amount else "partially_refunded"
    elif refund_status == "failed":
        payment.status = "captured" if payment.refund_amount == 0 else "partially_refunded"
        payment.booking.payment_status = "paid" if payment.refund_amount == 0 else "partially_refunded"
    else:
        payment.status = "refund_pending"
        payment.booking.payment_status = "refund_pending"
    db.add(
        PaymentTransaction(
            payment_id=payment.id,
            gateway_refund_id=refund.get("id"),
            event_type="refund.requested",
            status=refund_status,
            amount=amount,
            payload=compact_json({"refund_id": refund.get("id"), "reason": payload.reason}),
        )
    )
    db.add(
        AdminActivityLog(
            admin_id=admin.id,
            action="payment.refund",
            entity_type="payment",
            entity_id=payment.payment_ref,
            details=f"Refund request {refund.get('id', '')}",
        )
    )
    db.commit()
    return {"refund_id": refund.get("id"), "status": refund_status, "amount": amount}
