# Smart Student Expense Tracker

A lightweight personal expense tracker aimed at students. Tracks expenses, budgets, savings goals and includes receipt OCR, analytics, and a small web UI.

This repository contains a vanilla-JS frontend (`index.html`, `app.js`) and a FastAPI backend in `backend/`.

## Quick Start (development)

1. Create and activate a Python virtual environment and install backend dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

2. Configure environment variables. Copy the example and update values:

```bash
cp backend/.env.example backend/.env
# then edit backend/.env to set DATABASE_URL, SECRET_KEY, SMTP settings, etc.
```

3. Run database migrations (Alembic is configured under `backend/alembic`):

```bash
alembic -c backend/alembic.ini upgrade head
```

If you previously used the app without migrations and the database schema was created automatically, you may need to run `alembic stamp head` to mark the first migration as applied:

```bash
alembic -c backend/alembic.ini stamp head
```

4. Start the backend API (from project root):

```bash
uvicorn backend.main:app --reload --port 8003
```

Open the frontend at `http://localhost:8003` (the simple index.html is served by the backend).

## Important Commands

- Install deps:

```bash
pip install -r backend/requirements.txt
```
- Run migrations:

```bash
alembic -c backend/alembic.ini upgrade head
```
- Mark migrations as applied (if schema was created already):

```bash
alembic -c backend/alembic.ini stamp head
```
- Start server:

```bash
uvicorn backend.main:app --reload --port 8003
```
- Health check:

```bash
curl http://127.0.0.1:8003/health
```

## New / Notable Features

- Refresh token support: the backend uses short-lived JWT access tokens and opaque, rotating refresh tokens stored (hashed) in the database. Refresh tokens are issued as an `HttpOnly` cookie (path `/api/auth/refresh`) to allow silent token rotation.
- Refresh-token reuse detection: if a revoked/previously-used refresh token is presented, the backend revokes all refresh tokens for that user and logs a security event.
- Soft-delete / Recycle Bin for expenses: deleted expenses are marked with `deleted` and `deleted_at` and moved to a recycle view in the frontend.
	- Endpoints:
		- `PATCH /api/expenses/{expense_id}/delete` — soft-delete (moves to recycle bin)
		- `POST /api/expenses/{expense_id}/restore` — restore a soft-deleted expense
		- `GET /api/expenses/recycle` — list deleted expenses
		- `DELETE /api/expenses/{expense_id}` — permanently delete (only for already soft-deleted items)
- Alembic migrations are included under `backend/alembic/versions`.

## API (selected)

- `GET /health` — health check
- `POST /api/auth/signup` — create account
- `POST /api/auth/login` — login (returns access token)
- `POST /api/auth/refresh` — rotate refresh token (expects refresh cookie)
- `POST /api/auth/logout` — revoke tokens and clear refresh cookie
- `GET /api/state` — user state, settings, and recent expenses
- `GET /api/expenses` — list expenses (excludes soft-deleted items)
- `POST /api/expenses` — create expense
- `PATCH /api/expenses/{id}/delete` — soft-delete expense

For a full list of endpoints consult `backend/main.py`.

## Environment / Security Notes

- `SECRET_KEY` must be provided in `backend/.env` for signing access tokens.
- In development, SMTP may be left empty — verification codes are printed to the server console. For production, configure SMTP settings in `backend/.env`.
- Cookies: refresh tokens are set with `HttpOnly` and `SameSite='strict'`. In production enable `COOKIE_SECURE=true` (send only over HTTPS).

## Troubleshooting

- Port already in use: if `uvicorn` fails with "Address already in use", find and stop the process or change `--port`.

```bash
lsof -i :8003
kill <pid>
```

- Missing DB driver: if you see `ModuleNotFoundError: No module named 'psycopg'` install requirements (`pip install -r backend/requirements.txt`).
- Alembic duplicate-table errors: if the database already has tables (created by `metadata.create_all`), run `alembic -c backend/alembic.ini stamp head` to record the migration state.

## Development Notes

- Frontend files are `index.html`, `app.js`, and `styles.css` in the project root.
- The app uses `fetch(..., credentials: 'include')` so the refresh cookie is sent automatically when calling `/api/auth/refresh`.
- Tests: add unit/integration tests under `backend/tests` and update the CI workflow at `.github/workflows/ci.yml`.

### Dev script

There is a helper script at `scripts/dev.sh` that bootstraps a virtualenv, installs dependencies, runs migrations, and starts the server. Usage:

```bash
./scripts/dev.sh
```

## API Examples (curl)

Below are example requests to exercise the main auth and expense flows. Replace `API_BASE` and values as appropriate.

```bash
API_BASE=http://127.0.0.1:8003

# Signup
curl -X POST $API_BASE/api/auth/signup \
	-H "Content-Type: application/json" \
	-d '{"email":"alice@example.com","password":"Password123!","name":"Alice"}'

# Verify email (replace code from email/console)
curl -X POST $API_BASE/api/auth/verify-email \
	-H "Content-Type: application/json" \
	-d '{"email":"alice@example.com","code":"123456"}'

# Login (returns access token in JSON and sets refresh cookie)
curl -i -X POST $API_BASE/api/auth/login \
	-H "Content-Type: application/json" \
	-d '{"email":"alice@example.com","password":"Password123!"}'

# Use the access token in Authorization header
ACCESS_TOKEN=<token-from-login>
curl -H "Authorization: Bearer $ACCESS_TOKEN" $API_BASE/api/state

# Refresh access token (sends refresh cookie automatically if using a browser; with curl you'll need the cookie)
curl -i -X POST $API_BASE/api/auth/refresh --cookie "your_refresh_cookie_here"

# Create expense
curl -X POST $API_BASE/api/expenses \
	-H "Content-Type: application/json" \
	-H "Authorization: Bearer $ACCESS_TOKEN" \
	-d '{"name":"Lunch","amount":8.50,"category":"Food","date":"2026-05-28"}'

# Soft-delete expense
curl -X PATCH $API_BASE/api/expenses/1/delete \
	-H "Authorization: Bearer $ACCESS_TOKEN"

# Restore expense
curl -X POST $API_BASE/api/expenses/1/restore \
	-H "Authorization: Bearer $ACCESS_TOKEN"

# Permanently delete (only allowed if already soft-deleted)
curl -X DELETE $API_BASE/api/expenses/1 \
	-H "Authorization: Bearer $ACCESS_TOKEN"
```

## .env example

The repository already includes `backend/.env.example` with common settings (SQLite default, SMTP placeholders, secret key placeholder). Copy it to `backend/.env` and update values before running in production.

## ER Diagram (simple)

I added a small SVG diagram describing the main tables under `docs/er_diagram.svg` (see `/docs/er_diagram.svg`).

## Database Structure

The backend uses SQLAlchemy ORM models. Key tables and important columns:

- `users`
	- `id` (PK), `name`, `first_name`, `last_name`, `email` (unique), `password_hash`, `email_verified`, `allowance`, `preferred_range`, `custom_range_start`, `custom_range_end`
- `categories`
	- `id` (PK), `user_id` (FK -> users.id), `name`, `budget`, `color`
- `expenses`
	- `id` (PK), `user_id` (FK -> users.id), `name`, `amount`, `category`, `date`, `deleted` (soft-delete flag), `deleted_at`
- `goals`
	- `id` (PK), `user_id` (FK -> users.id), `name`, `target`, `saved`
- `user_settings`
	- `id` (PK), `user_id` (FK, unique), `country`, `savings_currencies` (JSON)
- `refresh_tokens`
	- `id` (PK), `jti` (unique), `user_id` (FK -> users.id), `token_hash`, `created_at`, `expires_at`, `revoked`, `last_used_at`
- `email_verification_codes`
	- `id` (PK), `user_id` (FK -> users.id), `code_hash`, `expires_at`, `attempts`, `used_at`

All foreign keys use `ON DELETE CASCADE` so user data is removed when a user account is deleted.

## Full Features

- User accounts: signup, email verification, login, logout.
- Authentication: short-lived JWT access tokens + opaque rotating refresh tokens stored (hashed) server-side.
- Expense management: create, list, edit, soft-delete, restore, permanently delete.
- Categories and budgets per user; over-budget detection and warnings.
- Savings goals with progress tracking.
- Receipt upload + client-side OCR (Tesseract.js) helper for parsing receipts.
- Offline resilience: frontend caches state locally and can operate when API is temporarily unreachable.
- Analytics: weekly/monthly summaries and simple rule-based suggestions.
- Security: bcrypt password hashing, verification-code HMAC, refresh-token reuse detection (revokes all tokens on suspected reuse).

## Tech Stack

- Backend: Python, FastAPI, Uvicorn
- ORM / DB: SQLAlchemy (ORM v2), Alembic for migrations
- Database drivers: `psycopg[binary]` for PostgreSQL (SQLite supported for quick local runs)
- Frontend: Vanilla JavaScript, HTML, CSS
- Client libraries: Tesseract.js (optional, for receipt OCR)
- Dev / tooling: GitHub Actions (CI), Alembic, pip, uvicorn

## Architecture Overview

- Single-repo monolith with a lightweight JS frontend served by FastAPI.
- Backend responsibilities:
	- HTTP API (FastAPI) and auth/session management
	- Persistent storage via SQLAlchemy models
	- Email verification & SMTP integration
	- Alembic migrations for schema evolution
- Frontend responsibilities:
	- UI rendering and local state caching
	- Calling API endpoints with `fetch(..., credentials: 'include')` to allow refresh-cookie flows

The app favors server-side session persistence (refresh tokens in DB) and stateless short-lived access tokens for API calls.

## Module / Dependency Graph (high-level)

Backend (selected modules):

- `backend/main.py`  → registers FastAPI routes and depends on:
	- `backend/auth.py` (login, token creation/verification)
	- `backend/database.py` (engine, Base)
	- `backend/models.py` (ORM models)
	- `backend/schemas.py` (Pydantic models)
	- `backend/email_verification.py` (verification flows)

- `backend/auth.py` → uses `backend/models.py` and `backend/database.py` for token persistence and user lookups.
- `backend/seed.py` → uses models to create default categories/settings for new users.
- `backend/alembic/*` → migration scripts that operate on the same models/metadata.

Frontend:

- `index.html`, `app.js`, `styles.css` → UI glue calling the API routes above (state hydration via `GET /api/state`).

ASCII overview (logical):

```
Frontend (index.html, app.js)
	↕ (HTTP, credentials included)
FastAPI app (backend/main.py)
	├─ auth utilities (backend/auth.py)
	├─ DB & models (backend/database.py, backend/models.py)
	├─ migrations (backend/alembic)
	└─ email (backend/email_verification.py)
```

## User Flow (happy path)

1. New user: `POST /api/auth/signup` → receives verification code via email (or console in dev).
2. Verify email: `POST /api/auth/verify-email` → marks account verified.
3. Login: `POST /api/auth/login` → returns access token and sets a rotating refresh cookie.
4. App loads `GET /api/state` to hydrate UI (categories, recent expenses, settings).
5. Create expense: `POST /api/expenses` → expense stored in DB and displayed.
6. Soft-delete expense: `PATCH /api/expenses/{id}/delete` → `deleted=true`, moved to Recycle view.
7. Restore expense: `POST /api/expenses/{id}/restore` → `deleted=false`.
8. Permanently delete: `DELETE /api/expenses/{id}` (only for soft-deleted items).
9. Access token expiry: frontend calls `POST /api/auth/refresh` with refresh cookie to obtain a new access token; refresh tokens are rotated and old tokens are invalidated.

Edge / security flow:

- If a revoked or previously-used refresh token is presented, the backend revokes all refresh tokens for that user and requires a fresh login; this helps detect/recover from token theft.

## Roadmap (suggested)

- Short term
	- Add server-side tests for auth and soft-delete endpoints
	- Add frontend unit/integration tests and CI steps that run migrations + tests
	- Add a `scripts/dev.sh` helper to bootstrap venv, install, migrate, and run server

- Medium term
	- Add scheduled background job to purge permanently-deleted items after configurable TTL
	- Add pagination and filtering to recycle-bin and expenses list
	- Add Redis-backed rate limiting for login attempts

- Long term
	- Multi-user sharing or export/import of budgets
	- Mobile-native wrapper or advanced PWA support (offline sync)
	- Multi-region deployment with managed DB (Postgres) and production-grade secrets/CI/CD
