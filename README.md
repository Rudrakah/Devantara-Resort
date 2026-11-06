# Devantara Resort

The website is served by a FastAPI application with a SQLAlchemy database. Resort rooms, rates, amenities, packages, gallery images, contact details, and reviews are managed as data; add only verified resort information through the admin tools.

## Requirements

- Python 3.11 or newer
- SQLite for local development, or PostgreSQL for a hosted deployment
- Razorpay test credentials and SMTP credentials only if you want to test online payments and email delivery

## Local setup (Windows PowerShell)

From the project directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set a unique JWT signing secret in `.env`. Generate one with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the generated value into `JWT_SECRET`. Do not commit `.env` or share its values. Keep the default local SQLite URL for development.

Create/update the database schema and create an administrator:

```powershell
python -m alembic upgrade head
python -m backend.app.create_admin
```

Start the application:

```powershell
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) for the website, [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin) for administration, and [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) for the API reference.

The database starts without assumed room inventory or pricing. Sign in to the admin page to add room categories and rooms, then configure availability, rates, contact details, amenities, packages, and gallery items. The public site reflects those database values.

## Configuration

Environment variables are documented in `.env.example`. Important settings:

- `DATABASE_URL`: SQLite locally; use a PostgreSQL SQLAlchemy URL in production.
- `JWT_SECRET`: required for admin login and must be at least 32 characters.
- `CORS_ORIGINS` and `ALLOWED_HOSTS`: restrict these to the exact production origins and hostnames.
- `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`: payment credentials. Keep `RAZORPAY_TEST_MODE=true` while testing and use only Razorpay test keys in that mode.
- `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, and `ADMIN_CONTACT_EMAIL`: optional email notifications. Without SMTP, bookings and enquiries are still stored; email is not sent.
- `RESORT_PHONE`, `RESORT_ADDRESS`, and `ADMIN_CONTACT_EMAIL`: verified public contact information.

Configure the Razorpay webhook URL as `https://<your-domain>/api/payments/webhook` and set the matching webhook secret. Payment success is recorded only after a verified gateway response or signed webhook. Never collect or store card details in this application.

Before going live, use HTTPS, a strong unique JWT secret, a production PostgreSQL database with backups, restricted CORS/host settings, live Razorpay keys with test mode disabled, and operationally monitored email delivery. Verify inventory, prices, cancellation/refund policies, contact information, and all other resort content before publishing them.

## Database migrations

Apply migrations with `python -m alembic upgrade head`. After changing SQLAlchemy models, create a reviewed migration using `python -m alembic revision --autogenerate -m "describe the schema change"` and apply it with `python -m alembic upgrade head`. Review generated migrations before deployment.

## Tests

Run the API tests with:

```powershell
python -m pytest -q
```

The tests use temporary SQLite databases and do not call Razorpay or send external email.
