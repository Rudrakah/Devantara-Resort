from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./devantara.db"
    jwt_secret: str = ""
    jwt_expire_minutes: int = 60
    cors_origins: list[str] = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8765",
        "http://127.0.0.1:8765",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    booking_hold_minutes: int = 15
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_test_mode: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    resort_name: str = "Devantara Resort"
    resort_phone: str = ""
    resort_address: str = ""
    admin_contact_email: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
