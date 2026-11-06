from getpass import getpass

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select

from backend.app.database import Base, SessionLocal, engine
from backend.app.models import Admin
from backend.app.security import hash_password


def main() -> None:
    Base.metadata.create_all(bind=engine)
    email_input = input("Admin email: ").strip().lower()
    try:
        email = str(TypeAdapter(EmailStr).validate_python(email_input))
    except ValidationError:
        raise SystemExit("Enter a valid email address.") from None
    name = input("Admin display name: ").strip()
    if not name or len(name) > 120:
        raise SystemExit("Display name must be between 1 and 120 characters.")
    password = getpass("Password (at least 12 characters): ")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters.")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    with SessionLocal() as db:
        existing = db.scalar(select(Admin.id).where(Admin.email == email))
        if existing is not None:
            raise SystemExit("An administrator with that email already exists.")
        admin = Admin(name=name, email=email, password_hash=hash_password(password))
        db.add(admin)
        db.commit()
    print(f"Administrator account created for {email}.")


if __name__ == "__main__":
    main()
