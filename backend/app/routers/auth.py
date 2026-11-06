from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.limiter import limiter
from backend.app.models import Admin
from backend.app.schemas import LoginRequest, TokenOut
from backend.app.security import create_access_token, get_current_admin, verify_password


router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    admin = db.scalar(select(Admin).where(Admin.email == payload.email.lower()))
    if admin is None or not admin.is_active or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    token = create_access_token(admin)
    return {"access_token": token, "admin": admin}


@router.get("/me")
def me(admin: Admin = Depends(get_current_admin)):
    return {"id": admin.id, "name": admin.name, "email": admin.email}
