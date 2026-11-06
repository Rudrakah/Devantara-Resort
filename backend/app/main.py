import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler
from sqlalchemy import text

from backend.app import models
from backend.app.config import settings
from backend.app.database import Base, engine, get_db
from backend.app.limiter import limiter
from backend.app.routers import admin, auth, bookings, contact, payments, rooms


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
    if not settings.jwt_secret or len(settings.jwt_secret) < 32:
        logger.warning("Admin login is disabled until JWT_SECRET is configured (minimum 32 characters).")
    yield


app = FastAPI(
    title="Devantara Resort API",
    description="Resort availability, booking, payments and administration API.",
    version="1.0.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Razorpay-Signature", "X-Razorpay-Event-Id"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    # Do not echo submitted values such as passwords or contact details in API errors.
    errors = [
        {"loc": error.get("loc"), "msg": error.get("msg"), "type": error.get("type")}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


for route in (auth.router, rooms.router, bookings.router, payments.router, payments.admin_router, contact.router, admin.router):
    app.include_router(route)


@app.get("/api/health", tags=["health"])
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/site-info", tags=["site information"])
def site_info():
    return {
        "name": settings.resort_name,
        "phone": settings.resort_phone,
        "email": settings.admin_contact_email,
        "address": settings.resort_address,
    }


@app.get("/", include_in_schema=False)
def website_home():
    return FileResponse(PROJECT_ROOT / "index.html")


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(PROJECT_ROOT / "admin.html")


@app.get("/styles.css", include_in_schema=False)
def website_styles():
    return FileResponse(PROJECT_ROOT / "styles.css", media_type="text/css")


@app.get("/script.js", include_in_schema=False)
def website_script():
    return FileResponse(PROJECT_ROOT / "script.js", media_type="text/javascript")


@app.get("/admin.css", include_in_schema=False)
def admin_styles():
    return FileResponse(PROJECT_ROOT / "admin.css", media_type="text/css")


@app.get("/admin.js", include_in_schema=False)
def admin_script():
    return FileResponse(PROJECT_ROOT / "admin.js", media_type="text/javascript")


@app.get("/devantara-resort.jpg", include_in_schema=False)
def resort_image():
    return FileResponse(PROJECT_ROOT / "devantara-resort.jpg", media_type="image/jpeg")


@app.get("/file_00000000efec820b99f93b6e6968371f.png", include_in_schema=False)
def resort_logo():
    return FileResponse(PROJECT_ROOT / "file_00000000efec820b99f93b6e6968371f.png", media_type="image/png")
