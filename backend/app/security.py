from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import get_db
from backend.app.models import Admin


password_hash = PasswordHash.recommended()
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_access_token(admin: Admin) -> str:
    if not settings.jwt_secret or len(settings.jwt_secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured. Set JWT_SECRET to a random value of at least 32 characters.",
        )
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(admin.id),
        "role": "admin",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Admin:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not settings.jwt_secret or len(settings.jwt_secret) < 32:
        raise unauthorized
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("role") != "admin" or not payload.get("sub"):
            raise unauthorized
        admin_id = int(payload["sub"])
    except (jwt.PyJWTError, ValueError, TypeError):
        raise unauthorized from None
    admin = db.scalar(select(Admin).where(Admin.id == admin_id, Admin.is_active.is_(True)))
    if admin is None:
        raise unauthorized
    return admin


def require_admin(admin: Admin = Depends(get_current_admin)) -> Admin:
    return admin
