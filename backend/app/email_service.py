import html
import logging
import smtplib
from email.message import EmailMessage

from backend.app.config import settings


logger = logging.getLogger(__name__)


def send_email(recipient: str, subject: str, body_html: str, body_text: str) -> bool:
    if not all((settings.smtp_host, settings.smtp_from_email)):
        logger.info("SMTP is not configured; email notification was not sent.")
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message.set_content(body_text)
    message.add_alternative(body_html, subtype="html")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.exception("Email delivery failed.")
        return False
    return True


def enquiry_email(name: str, email: str, phone: str, subject: str, message: str) -> tuple[str, str]:
    safe = [html.escape(value) for value in (name, email, phone, subject, message)]
    body_html = (
        "<h2>New website enquiry</h2>"
        f"<p><strong>Name:</strong> {safe[0]}</p><p><strong>Email:</strong> {safe[1]}</p>"
        f"<p><strong>Phone:</strong> {safe[2] or 'Not provided'}</p><p><strong>Subject:</strong> {safe[3]}</p>"
        f"<p>{safe[4].replace(chr(10), '<br>')}</p>"
    )
    body_text = f"New enquiry from {name} ({email})\nPhone: {phone or 'Not provided'}\nSubject: {subject}\n\n{message}"
    return body_html, body_text


def booking_email(booking_ref: str, name: str, room: str, check_in: str, check_out: str, amount: str) -> tuple[str, str]:
    safe = [html.escape(value) for value in (booking_ref, name, room, check_in, check_out, amount)]
    body_html = (
        f"<h2>We received your booking request</h2><p>Hello {safe[1]},</p>"
        f"<p>Reference: <strong>{safe[0]}</strong></p><p>Stay: {safe[2]} · {safe[3]} to {safe[4]}</p>"
        f"<p>Estimated total: ₹{safe[5]}</p><p>This is a pending request, not a confirmed reservation. "
        "Your stay is confirmed only after verified payment.</p>"
    )
    body_text = (
        f"Hello {name},\n\nWe received booking request {booking_ref} for {room}, "
        f"{check_in} to {check_out}. Estimated total: INR {amount}.\n"
        "This is a pending request, not a confirmed reservation. Confirmation follows verified payment."
    )
    return body_html, body_text


def booking_status_email(name: str, booking_ref: str, status_text: str, details: str) -> tuple[str, str]:
    safe = [html.escape(value) for value in (name, booking_ref, status_text, details)]
    body_html = (
        f"<h2>{safe[2]}</h2><p>Hello {safe[0]},</p>"
        f"<p>Booking reference: <strong>{safe[1]}</strong></p><p>{safe[3]}</p>"
    )
    body_text = f"Hello {name},\n\n{status_text}\nBooking reference: {booking_ref}\n{details}"
    return body_html, body_text
