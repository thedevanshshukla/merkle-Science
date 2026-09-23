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
- Paginated `GET /members` with stable ID ordering and total-count metadata.
- PostgreSQL row locking during order stock reservation to protect concurrent last-copy orders.
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

## Optional work

Both optional extras from the assignment were implemented: paginated `GET /members` and PostgreSQL row locking during order stock reservation. The locking behavior was verified through the Supabase order integration tests.

## Spec observations and trade-offs

- **Late fee price snapshot vs order price snapshot**: In `SPEC.md`, order line items record the unit price at order creation so subsequent price changes do not affect existing purchases. In contrast, loan returns calculate late fees using `min(days_late * 25, book.price_cents)` using the book's price at the time of return. If the bookstore raises prices while a book is out on loan, the maximum late fee penalty increases retroactively. An alternative domain design would be snapshotting `price_cents` on the `Loan` record at checkout time to ensure the penalty cap remains immutable.
- **Mixed-case sorting**: SQLite defaults to binary ASCII ordering (uppercase before lowercase), whereas PostgreSQL uses the database collation (frequently case-insensitive). Following the spec's advice to leave mixed-case ordering engine-native avoids forcing functional `lower()` operations that would bypass standard database indexes.

## What I would do with more time

- **Database migrations**: Introduce Alembic migrations rather than relying on `Base.metadata.create_all()` to enable versioned, reversible schema changes in production.
- **Targeted database indexes**: Add composite B-tree indexes on foreign keys and frequently filtered columns: `orders(member_id)`, `loans(member_id, returned_at)`, and `books(title, author)`.
- **API idempotency**: Implement `Idempotency-Key` headers on `POST /orders` and `POST /loans` to safely handle client network retries without creating duplicate orders or loans.
- **Authentication & authorization**: Replace raw `member_id` parameters with authenticated JWT/session tokens to ensure members can only inspect and manage their own orders and loans.

## AI usage

I used OpenAI Codex as an interactive coding assistant and rubber duck throughout development, while retaining full ownership of the architecture, implementation choices, and test verification.

- **How I used it**: I used the assistant primarily for scaffolding repetitive Pydantic boilerplate, looking up SQLAlchemy 2.0 query syntax patterns, and discussing edge cases against `SPEC.md`. All generated snippets were manually vetted, adapted to match the repository's coding style, and verified against the test suite.
- **Where I had to intervene & override**:
  - *Concurrency & Race Conditions*: When addressing the optional concurrent stock reservation, the assistant initially suggested application-level Python locks (`threading.Lock`), which would be ineffective across multi-worker ASGI processes in production. I rejected that approach and implemented database-level row locking using PostgreSQL `with_for_update()` ordered deterministically by book ID to avoid deadlocks.
  - *Loan Return Boundary Logic*: The assistant initially attempted to calculate late fees using simple day-truncation (`.days`), which miscalculated partial-day overdues. I corrected the logic to use `math.ceil` on total elapsed seconds and enforced the strict boundary where loans exactly at `due_at` incur zero fee as required by the specification.
  - *Database Connection*: When direct Supabase connections stalled due to local IPv4 network constraints, I identified the root cause and reconfigured the setup to use the Supabase Session Pooler endpoint.

