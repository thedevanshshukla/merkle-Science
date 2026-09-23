# Sanctum Sanctorum Bookstore

Live application: https://sanctum-sanctorum-sk25.onrender.com

Use the Members tab with seeded member ID `1` to inspect the deployed application. The API documentation is available at `/docs`.

## Completed

- ISBN-13 normalization and checksum validation.
- Book creation, duplicate detection, filtering, sorting, pagination, and partial updates.
- Member validation, normalized email uniqueness, tier access rules, and statistics.
- Order validation, tier and bulk discounts, stock reservation, payment, cancellation, and stock restoration.
- Loan limits, restricted-book access, due dates, computed statuses, returns, late fees, and member loan listings.
- Top-books reporting.
- Static frontend flows for catalog browsing, member selection, orders, loans, returns, and reports.
- PostgreSQL deployment support through SQLAlchemy and `psycopg`.

## Architecture and deployment decisions

- Routers remain thin; validation is handled by Pydantic schemas and business rules live in service modules.
- SQLAlchemy models provide the persistence layer, with `get_now` used for deterministic time-dependent behavior.
- SQLite remains the default local database so the supplied test suite works without external services.
- Production uses Supabase PostgreSQL through the Session Pooler. The PostgreSQL URL is supplied through `SANCTUM_DATABASE_URL` and is never committed.
- Render hosts the FastAPI service. The same service serves the static frontend and API, which keeps the deployment small and avoids a separate frontend build.

## Verification

- Original suite: 202 tests passed with the supplied SQLite fixtures.
- Separate local-only integration suite: 202 tests passed against a disposable Supabase PostgreSQL schema.
- Public deployment checks passed for `/`, `/health`, `/books`, `/members/1`, `/members/1/stats`, `/members/1/loans`, `/reports/top-books`, `/docs`, and `/openapi.json`.
- The deployed frontend includes the loan-return action handler.

The test run reports two existing dependency deprecation warnings from FastAPI/Starlette/httpx and AnyIO. They do not indicate application failures, so the dependency stack was not changed merely to suppress them.

## Optional work not implemented

- Concurrency-safe reservation of the last available copy under simultaneous orders.
- A paginated `GET /members` endpoint.

## AI usage

OpenAI Codex was used as a development assistant for repository exploration, task decomposition, debugging, test execution, deployment troubleshooting, and code review. I reviewed the generated suggestions and verified the resulting behavior with the supplied tests and a separate PostgreSQL integration run.

One important correction was required during development: the initial direct Supabase database endpoint was not reachable from the local IPv4 network. After verifying the failure, I switched to the Supabase Session Pooler endpoint and validated the application against PostgreSQL.
