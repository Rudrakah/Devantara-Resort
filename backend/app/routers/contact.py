import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import get_db
from backend.app.email_service import enquiry_email, send_email
from backend.app.limiter import limiter
from backend.app.models import ContactEnquiry
from backend.app.schemas import ContactCreate


router = APIRouter(prefix="/api/contact", tags=["contact"])
logger = logging.getLogger(__name__)


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def create_enquiry(
    request: Request,
    payload: ContactCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if payload.website:
        logger.info("Ignored contact submission that triggered the honeypot.")
        return {"message": "Thank you. Your enquiry has been received."}

    enquiry = ContactEnquiry(
        name=payload.name,
        email=str(payload.email).lower(),
        phone=payload.phone,
        subject=payload.subject,
        message=payload.message,
    )
    db.add(enquiry)
    db.commit()
    db.refresh(enquiry)

    if settings.admin_contact_email:
        html_body, text_body = enquiry_email(
            enquiry.name,
            enquiry.email,
            enquiry.phone,
            enquiry.subject,
            enquiry.message,
        )
        background_tasks.add_task(
            send_email,
            settings.admin_contact_email,
            f"Website enquiry · {settings.resort_name}",
            html_body,
            text_body,
        )
    else:
        logger.info("Contact enquiry %s was stored; no notification recipient is configured.", enquiry.id)
    return {"message": "Thank you. Your enquiry has been received.", "enquiry_id": enquiry.id}
