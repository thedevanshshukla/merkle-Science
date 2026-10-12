# Sanctum Sanctorum Bookstore — Complete Technical & Interview Guide

This document is an exhaustive, production-grade reference manual for the **Sanctum Sanctorum Bookstore** project. It covers the scenario, full architecture, execution flow, codebase anatomy, diff breakdown, design decisions, alternative patterns, deployment details, git history, and an extensive bank of interview questions with model answers.

---

## Table of Contents
1. [Executive Summary & Assignment Context](#1-executive-summary--assignment-context)
2. [High-Level Architecture & Request Lifecycle](#2-high-level-architecture--request-lifecycle)
3. [Repository File Tree & Responsibilities](#3-repository-file-tree--responsibilities)
4. [Backend Implementation Deep Dive](#4-backend-implementation-deep-dive)
5. [Frontend Implementation Deep Dive](#5-frontend-implementation-deep-dive)
6. [Starter Code vs. My Implementation (What I Wrote)](#6-starter-code-vs-my-implementation-what-i-wrote)
7. [Design Decisions & Trade-Offs ("Why I Wrote It That Way")](#7-design-decisions--trade-offs-why-i-wrote-it-that-way)
8. [Alternative Architectures & Why They Were Rejected](#8-alternative-architectures--why-they-were-rejected)
9. [Testing Strategy, Fixtures & Concurrency Verification](#9-testing-strategy-fixtures--concurrency-verification)
10. [Deployment Architecture (Render & Supabase)](#10-deployment-architecture-render--supabase)
11. [Git Commit Chronology & Engineering Narrative](#11-git-commit-chronology--engineering-narrative)
12. [Master Technical Interview Q&A Bank](#12-master-technical-interview-qa-bank)

---

## 1. Executive Summary & Assignment Context

### The Scenario
You joined the engineering team maintaining the **Sanctum Sanctorum Clubhouse Bookstore**, a private members-only bookstore and library. Members can:
* **Buy books** through the order system with tier-based and bulk discounts.
* **Borrow books** on 14-day loans subject to strict membership tier limits, overdue penalties, and restriction checks.
* **Track statistics and reports** on purchasing history, late fees, and storewide bestsellers.

### Baseline State
The previous developer left the project incomplete:
* **Failing Tests:** More than 70% of the initial 202 acceptance tests failed out-of-the-box (`NotImplementedError` stubs everywhere).
* **Broken / Missing Models:** The `Loan` ORM model was missing essential columns (`due_at`, `returned_at`, `late_fee_cents`).
* **Unimplemented Business Logic:** No ISBN-13 checksum validation, no email normalization, no pricing/discount calculation, no stock reservation/restoration, no loan overdue fee calculation, and no reporting queries.
* **Disconnected Frontend:** The loan return user action on the frontend was unhandled.

### The Objective & Constraints
1. **Pass all 202 acceptance tests** in `tests/` without altering a single line of `tests/`.
2. **Follow `SPEC.md` strictly**, maintaining clean separation of concerns (thin routers, fat services).
3. **Use dependency injection for time:** All business logic requiring current time must consume `Depends(get_now)` rather than calling `datetime.now()` directly.
4. **Deploy a public version** with a live database and web interface.
5. **Implement optional extras:**
   * Paginated `GET /members`.
   * Concurrency-safe stock reservation using PostgreSQL row locking (`with_for_update()`).
6. **Maintain an incremental Git history** and document all decisions and AI usage in `NOTES.md`.

---

## 2. High-Level Architecture & Request Lifecycle

### System Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                                  CLIENT LAYER                                     |
|   Browser UI (Vanilla HTML/CSS/JS)   |   Swagger UI (/docs)   |   Pytest Client  |
+-----------------------------------------+-----------------------------------------+
                                          | HTTP Requests
                                          v
+-----------------------------------------------------------------------------------+
|                                   FASTAPI CORE                                    |
|  - CORS Middleware (Allow All)                                                    |
|  - Global Exception Handlers (422 Pydantic, 501 NotImplemented, 404/403/409 HTTP) |
|  - StaticFiles Mount ("/" -> frontend/index.html)                                 |
+-----------------------------------------+-----------------------------------------+
                                          | Routing
                                          v
+-----------------------------------------------------------------------------------+
|                                   ROUTER LAYER                                    |
|   app/routers/{books, members, orders, loans, reports}.py                         |
|   * Thin controllers: Parse HTTP params, validate DTOs, inject Session & clock   |
+---------------------+-------------------+---------------------+-------------------+
                      |                   |                     |
     DTO Validation   |    DB Session     |   Clock Injection   |
     (Pydantic v2)    |    (get_db)       |   (get_now)         |
                      v                   v                     v
+-----------------------------------------------------------------------------------+
|                                   SERVICE LAYER                                   |
|   app/services/{books, members, orders, loans, reports}.py                        |
|   * Core Domain Logic, Tier Hierarchy, Stock Management, Pricing, Late Fees      |
|   * All-or-nothing transactions, Row-level locking (SELECT ... FOR UPDATE)        |
+-----------------------------------------+-----------------------------------------+
                                          | ORM Operations
                                          v
+-----------------------------------------------------------------------------------+
|                                PERSISTENCE LAYER                                  |
|   SQLAlchemy 2.x Declarative Models (app/models.py)                               |
|   Engine Config: SQLite (check_same_thread=False) | PostgreSQL (psycopg binary)   |
+-----------------------------------------+-----------------------------------------+
                                          |
                     +--------------------+--------------------+
                     |                                         |
                     v                                         v
         +-----------------------+                 +-----------------------+
         |    LOCAL & TESTS      |                 |      PRODUCTION       |
         |    SQLite In-Memory   |                 |   Supabase Postgres   |
         |    / Local File DB    |                 |   (Session Pooler)    |
         +-----------------------+                 +-----------------------+
```

### Detailed Request-Response Lifecycle
1. **HTTP Ingestion:** A request arrives at FastAPI (e.g., `POST /orders`).
2. **Schema Validation:** FastAPI intercepts the body using Pydantic v2 (`OrderCreate`). Pydantic runs field and model validators:
   * Rejects empty `items` list (HTTP 422).
   * Rejects duplicate `book_id`s in the payload (HTTP 422).
   * Rejects non-positive quantities (HTTP 422).
3. **Dependency Injection:** FastAPI resolves dependencies:
   * `db: Session = Depends(get_db)` provides a scoped SQLAlchemy session.
   * `now: datetime = Depends(get_now)` injects the clock timestamp (mocked in tests, real UTC in production).
4. **Router Delegation:** `routers/orders.py` immediately forwards the parsed data, database session, and timestamp to `services.orders.create_order(db, data, now)`.
5. **Business Logic Execution in Service:**
   * Checks member existence (404 if missing).
   * Acquires row-level locks on requested books (`with_for_update()`) in ordered sequence.
   * Checks book existence (404 if missing).
   * Verifies member tier authorization for restricted titles (403 if unauthorized).
   * Checks stock availability for all items (409 if any item has insufficient stock).
   * Mutates stock, computes discounts, builds `OrderItem` rows with frozen prices, and inserts the `Order` record.
   * Calls `db.commit()` and `db.refresh(order)`.
6. **Serialization & Response:** The ORM entity is mapped back to the Pydantic schema `OrderOut` and serialized to JSON.

---

## 3. Repository File Tree & Responsibilities

```
Sanctum-Sanctorum-main/
├── .github/                         # Continuous Integration workflows
├── .gitignore                       # Prevents committing secrets, venv, databases, caches
├── .python-version                  # Specifies Python 3.10+ runtime
├── ASSIGNMENT.md                    # Core problem statement & scenario description
├── INSTRUCTIONS.md                  # Grading rubric, deployment criteria, and submission rules
├── Makefile                         # Helper commands (setup, test, run, reset-db)
├── NOTES.md                         # Candidate notes: live link, architecture, AI statement
├── README.md                        # Quickstart instructions (uv, pip, make)
├── SPEC.md                          # Source of truth: API contracts, status codes, formulas
├── pyproject.toml                   # Project metadata & Python dependencies
├── render.yaml                      # Infrastructure as Code (IaC) Render Web Service Blueprint
├── sanctum.db                       # Local SQLite database (gitignored)
├── uv.lock                          # Deterministic lockfile for all installed dependencies
│
├── app/                             # Core Application Package
│   ├── __init__.py
│   ├── clock.py                     # Deterministic UTC time dependency (get_now)
│   ├── db.py                        # SQLAlchemy engine, SessionLocal, and get_db generator
│   ├── main.py                      # App factory (create_app), lifespan, CORS, static mounts
│   ├── models.py                    # SQLAlchemy ORM declarative models (Book, Member, Order, Loan)
│   ├── schemas.py                   # Pydantic v2 schemas, normalizers, and response DTOs
│   ├── seed.py                      # Seed data script for initial catalog and members
│   │
│   ├── routers/                     # HTTP Transport Layer (Thin Controllers)
│   │   ├── __init__.py
│   │   ├── books.py                 # Endpoints: POST, GET, PATCH /books, GET /books/{id}
│   │   ├── loans.py                 # Endpoints: POST /loans, GET /loans/{id}, POST /loans/{id}/return
│   │   ├── members.py               # Endpoints: POST /members, GET /members, GET /members/{id}/...
│   │   ├── orders.py                # Endpoints: POST, GET /orders, POST /orders/{id}/{pay, cancel}
│   │   └── reports.py               # Endpoints: GET /reports/top-books
│   │
│   └── services/                    # Domain Layer (Pure Business Logic)
│       ├── __init__.py
│       ├── books.py                 # ISBN validation, sorting, filtering, book updates
│       ├── loans.py                 # Tier borrowing limits, status calculation, late fees
│       ├── members.py               # Email uniqueness, tier hierarchy, aggregate stats
│       ├── orders.py                # Pricing, discount calculations, row locking, stock updates
│       └── reports.py               # Aggregate sales queries over paid orders
│
├── frontend/                        # Static UI (Served at "/")
│   ├── app.js                       # Vanilla ES module handling reactive UI, API client, toasts
│   ├── index.html                   # Semantic HTML layout (Catalog, Members, Orders, Loans, Reports)
│   └── styles.css                   # Custom typography, tables, badges, modal dialogs
│
├── integration_tests/               # (Gitignored) Supabase PostgreSQL Integration Suite
│   ├── conftest.py                  # Disposable PostgreSQL schema harness
│   └── test_*.py                    # Mirrors test suite executed against live PostgreSQL
│
└── tests/                           # Acceptance Test Suite (202 Unit & Integration Tests)
    ├── __init__.py
    ├── conftest.py                  # Pytest fixtures: client, clock (FrozenClock), make_book, make_member
    ├── test_books.py                # Tests ISBN validation, catalog filters, pagination, patch
    ├── test_health.py               # Tests /health endpoint
    ├── test_loans.py                # Tests borrowing limits, overdue calculations, late fees
    ├── test_members.py              # Tests tier access, stats aggregation, duplicate emails
    ├── test_orders.py               # Tests order creation, bulk discounts, cancellation, stock
    └── test_reports.py              # Tests top books bestsellers report
```

---

## 4. Backend Implementation Deep Dive

### 4.1 Database Configuration (`app/db.py`)
```python
DATABASE_URL = os.getenv("SANCTUM_DATABASE_URL", "sqlite:///./sanctum.db")

engine_options = {}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
```
* **Dual Database Support:** If `SANCTUM_DATABASE_URL` is set, the application automatically uses PostgreSQL (via `psycopg`). If absent, it transparently defaults to local SQLite.
* **`check_same_thread=False`:** Crucial for SQLite under multi-threaded FastAPI workers so different requests can share database access without driver crashes.
* **`expire_on_commit=False`:** Prevents SQLAlchemy from detaching ORM instance attributes after a commit, allowing Pydantic schemas to read properties without triggering lazy-load queries outside of active sessions.

### 4.2 Time Management (`app/clock.py`)
```python
def get_now() -> datetime:
    return datetime.utcnow()
```
* **Why Dependency Injection?** The entire test suite relies on time travel (`clock.advance(days=15)`). If code called `datetime.now()` directly, time-sensitive calculations (such as loan due dates and overdue statuses) would fail or become non-deterministic.
* By injecting `Depends(get_now)`, routers pass `now` to services, ensuring tests can freeze and manipulate time reliably.

### 4.3 Data Models (`app/models.py`)
The domain models use SQLAlchemy 2.0 `Mapped[...]` syntax:
* **`Book`:** `id`, `title`, `author`, `isbn` (indexed, unique), `price_cents`, `stock`, `restricted` (bool).
* **`Member`:** `id`, `name`, `email` (indexed, unique), `tier` (enum: `apprentice`, `adept`, `master`, `supreme`), `created_at`.
* **`Order`:** `id`, `member_id`, `status` (`pending`, `paid`, `cancelled`), `subtotal_cents`, `discount_percent`, `discount_cents`, `total_cents`, `created_at`.
* **`OrderItem`:** `id`, `order_id`, `book_id`, `quantity`, `unit_price_cents` (frozen snapshot of price).
* **`Loan` (Completed):**
  * Added `due_at: Mapped[datetime]` (strictly `borrowed_at + 14 days`).
  * Added `returned_at: Mapped[Optional[datetime]]` (null while active/overdue).
  * Added `late_fee_cents: Mapped[int]` (defaults to 0, computed upon return).

### 4.4 Schemas & Validation (`app/schemas.py`)
* **ISBN-13 Checksum Algorithm:**
  ```python
  total = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(isbn[:12]))
  expected_check_digit = (10 - total % 10) % 10
  if int(isbn[12]) != expected_check_digit:
      raise ValueError("isbn has an invalid checksum")
  ```
* **Email Normalization:** Automatically trims leading/trailing whitespace and lowercases emails before regex validation (`^[^@\s]+@[^@\s]+\.[^@\s]+$`).
* **Order Item Constraints:** Rejects empty item lists and rejects payloads containing duplicate `book_id`s in a single request.

### 4.5 Service Layer Modules (`app/services/`)

#### A. Books (`app/services/books.py`)
* **Listing (`list_books`):**
  * Implements multi-field search (`q` matches title or author case-insensitively).
  * Filters by `restricted`, `min_price`, and `max_price` (inclusive).
  * Implements dynamic sorting (`title`, `-title`, `price`, `-price`), always breaking ties with `id ASC`.
  * Computes `total` count before applying `offset` and `limit`.
* **Partial Update (`update_book`):** Implements `PATCH` semantics. Silently ignores any provided `isbn` field (as mandated by `SPEC.md`) while validating updated fields.

#### B. Members (`app/services/members.py`)
* **Tier Hierarchy:** Defined as an ordered list: `['apprentice', 'adept', 'master', 'supreme']`. Tier checks compare numerical rank indices.
* **Restricted Book Access:** Enforces that only members with rank $\ge$ `master` (index $\ge$ 2) can purchase or borrow restricted books (raises HTTP 403 otherwise).
* **Aggregate Statistics (`get_member_stats`):**
  * `orders_paid`: Count of orders with status `paid`.
  * `total_spent_cents`: Sum of `total_cents` across `paid` orders.
  * `active_loans`: Loans where `returned_at is None`.
  * `overdue_loans`: Loans where `returned_at is None` and `now > due_at`.
  * `late_fees_cents`: Sum of `late_fee_cents` on returned loans.
* **Paginated Members (`list_members`):** Optional feature returning stable `order_by(Member.id)` results with `total`, `limit`, and `offset` metadata.

#### C. Orders (`app/services/orders.py`)
* **Pricing Math:**
  $$\text{discount\_percent} = \text{tier\_percent} + (5\% \text{ if total\_quantity} \ge 10 \text{ else } 0\%)$$
  $$\text{discount\_cents} = \lfloor(\text{subtotal\_cents} \times \text{discount\_percent}) / 100\rfloor$$
  $$\text{total\_cents} = \text{subtotal\_cents} - \text{discount\_cents}$$
* **All-or-Nothing Stock Reservation:** Every book's stock is validated *before* any book's stock is mutated. If any book lacks inventory, the service aborts with HTTP 409 and leaves existing inventory untouched.
* **Concurrency Locking:** Acquires row-level locks on requested books:
  ```python
  books_by_id = {
      book.id: book
      for book in db.scalars(
          select(Book).where(Book.id.in_(book_ids)).order_by(Book.id).with_for_update()
      )
  }
  ```
  Sorting by `Book.id` guarantees a consistent acquisition order, avoiding database deadlocks when concurrent transactions order the same set of books.
* **Cancellation (`cancel_order`):** Can only cancel orders in `pending` status. Reverses inventory changes by iterating over `order.items` and adding quantities back to `book.stock`.

#### D. Loans (`app/services/loans.py`)
* **Borrowing Rules (`create_loan`):** Enforces 6 strict validation gates in sequence:
  1. Member & Book existence (404).
  2. Restriction authorization (403).
  3. Overdue loan block (409 if member has any unreturned loan past its `due_at`).
  4. Duplicate borrow block (409 if member currently holds an unreturned copy of the same book).
  5. Tier loan limit block (409 if active loans $\ge$ tier allowance: 1 for apprentice, 3 for adept, 5 for master, $\infty$ for supreme).
  6. Out-of-stock block (409 if `book.stock == 0`).
* **Computed Status (`loan_status`):** Status is never statically stored; it is derived dynamically at read time:
  * `returned`: if `loan.returned_at is not None`.
  * `overdue`: if `now > loan.due_at`.
  * `active`: otherwise.
  *(Strict boundary: when `now == due_at`, the loan is still `active` and owes 0 late fee).*
* **Late Fee Calculation:**
  $$\text{days\_late} = \lceil(\text{returned\_at} - \text{due\_at}) / 1\text{ day}\rceil$$
  $$\text{late\_fee\_cents} = \min(\text{days\_late} \times 25, \text{book.price\_cents})$$
  *(Partial days count as full days; fee is capped at the book's price at return time).*

#### E. Reports (`app/services/reports.py`)
* **Top Books (`top_books`):** Executes an optimized aggregation:
  ```python
  select(Book.id, Book.title, func.sum(OrderItem.quantity).label("copies_sold"))
  .join(OrderItem, OrderItem.book_id == Book.id)
  .join(Order, Order.id == OrderItem.order_id)
  .where(Order.status == OrderStatus.PAID.value)
  .group_by(Book.id, Book.title)
  .order_by(func.sum(OrderItem.quantity).desc(), Book.title.asc())
  .limit(limit)
  ```
  Excludes unpaid/cancelled orders and books with zero sales.

---

## 5. Frontend Implementation Deep Dive

The frontend is built in Vanilla ES6+ JavaScript, HTML5, and CSS3 without frameworks or build steps.

### Request Flow & Routing
FastAPI serves the frontend by mounting the `frontend/` directory at `/`:
```python
if FRONTEND_DIR.is_dir():
    application.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
```
Because API routes are declared *before* the static mount, API endpoints take precedence over static files.

### Client-Side State Management (`frontend/app.js`)
* Stores authenticated member context and cart state in `localStorage` (`sanctum.memberId`, `sanctum.cart`).
* Implements tabbed navigation (Catalog, Members, Orders, Loans, Reports).
* Wraps all fetch requests in an `api(path, options)` helper that formats FastAPI 422 validation error arrays into readable UI toast notifications.
* **Loan Return Wire-Up:** Added `case 'loan-return': returnLoan(id, target); break;` to the action dispatcher in `frontend/app.js`, connecting the return button in the UI directly to `POST /loans/{id}/return`.

---

## 6. Starter Code vs. My Implementation (What I Wrote)

| Component / File | Starter Code Baseline | My Implementation | Why / Technical Rationale |
| :--- | :--- | :--- | :--- |
| **`app/models.py`** | `Loan` model had only `id`, `member_id`, `book_id`, `borrowed_at`. | Added `due_at`, `returned_at`, and `late_fee_cents`. | Essential schema columns required to track loan lifecycle and compute penalties. |
| **`app/schemas.py`** | ISBN check digit had a `TODO`; Email validator was a simple regex; `OrderCreate` had no validation. | Added full ISBN-13 weighted checksum; added whitespace trimming and lowercasing for emails; added duplicate book & empty items validation in `OrderCreate`. | Ensures data integrity at the edge before hitting the database or services. |
| **`app/schemas.py`** | No `MemberPage` schema. | Created `MemberPage` schema (`items`, `total`, `limit`, `offset`). | Supported the optional paginated `GET /members` endpoint. |
| **`app/services/books.py`** | Stubs raising `NotImplementedError`. | Implemented `create_book`, `get_book`, `update_book` (partial patch ignoring ISBN), and `list_books` (search, price filters, sorting, pagination). | Satisfied core catalog management requirements and passed all catalog tests. |
| **`app/services/members.py`** | Stubs for validation, access rules, and stats. | Implemented tier rank hierarchy, 403 restriction checks, aggregate stats calculation, and paginated member listing. | Encapsulated all member business rules in the domain layer. |
| **`app/services/orders.py`** | `create_order`, `calculate_discount_percent`, `cancel_order` raised `NotImplementedError`. | Implemented discount math, all-or-nothing stock reservation, cancellation with inventory restoration, and PostgreSQL row-level locking (`with_for_update()`). | Guaranteed transactional integrity and eliminated race conditions for concurrent orders. |
| **`app/services/loans.py`** | All functions raised `NotImplementedError`. | Implemented 6-step borrow validation, dynamic read-time status derivation, `ceil`-based overdue fee calculation, and return inventory restoration. | Completed full library loan management domain. |
| **`app/services/reports.py`** | `top_books` raised `NotImplementedError`. | Implemented SQL join and group-by aggregation across paid orders. | Provided high-performance bestseller reporting. |
| **`app/db.py`** | Configured only for SQLite. | Added conditional support for PostgreSQL via `SANCTUM_DATABASE_URL` and `psycopg`. | Enabled production deployment to Supabase PostgreSQL while keeping SQLite for local tests. |
| **`frontend/app.js`** | Action dispatcher had no handler for `loan-return`. | Wired `case 'loan-return': returnLoan(id, target); break;`. | Enabled users to return books directly from the browser UI. |
| **`render.yaml`** | Did not exist. | Created Render blueprint specifying build and start commands (`uv run uvicorn`). | Infrastructure-as-Code enabling reproducible cloud deployment. |

---

## 7. Design Decisions & Trade-Offs ("Why I Wrote It That Way")

### 1. Thin Routers, Rich Services
* **Decision:** Routers only extract parameters, call services, and return responses. All business rules, queries, and HTTP error raises live in services.
* **Trade-off:** Slightly more boilerplate passing arguments between functions, but provides strict testability, clean boundaries, and zero duplicated logic.

### 2. Time Injection via `Depends(get_now)`
* **Decision:** Never call `datetime.now()` directly; always inject `get_now`.
* **Trade-off:** Functions require an extra `now` parameter, but it allows the test suite to execute fast, deterministic, non-flaky time-travel tests without patching the system clock.

### 3. Database Concurrency via `with_for_update()`
* **Decision:** Used PostgreSQL row-level locking ordered by `Book.id` during order stock reservation.
* **Trade-off:**
  * In-memory Python locks (`threading.Lock`) would fail across multi-process ASGI workers or multiple server replicas.
  * Optimistic locking (version columns) would cause high retry rates under heavy contention.
  * Row-level locking provides strong consistency directly in the database engine, with deterministic sorting preventing deadlocks.

### 4. Single-Service Deployment (API + Static Frontend)
* **Decision:** Mounted static files directly inside FastAPI on Render rather than deploying a separate frontend on Vercel.
* **Trade-off:** Avoided CORS configuration issues, separate build pipelines, and synchronizing deployments across multiple cloud platforms.

### 5. Supabase Session Pooler over Direct Connection
* **Decision:** Configured connection strings to point to the Supabase Session Pooler (port 5432 / 6543) instead of direct connection.
* **Trade-off:** Direct connections fail on networks without IPv6 support. The Session Pooler provides IPv4 compatibility and shields PostgreSQL from connection exhaustion.

---

## 8. Alternative Architectures & Why They Were Rejected

### 1. Async SQLAlchemy (`asyncio` / `async with`)
* **Why Considered:** FastAPI is inherently asynchronous and handles high concurrency well with async drivers (`asyncpg`).
* **Why Rejected:** The assignment starter kit was built around sync SQLAlchemy (`SessionLocal`, sync `get_db`). Switching to async would break the test harness in `tests/conftest.py` (which uses a synchronous test client). The ground rules explicitly forbade modifying `tests/`.

### 2. Application-Level Concurrency (`threading.Lock`)
* **Why Considered:** Simple to write in Python without touching database queries.
* **Why Rejected:** Uvicorn runs multiple worker processes in production (`gunicorn -w 4` or multiple container replicas). A Python memory lock exists only inside a single OS process. Multiple workers would still oversell stock simultaneously. Database-level locking is the only correct distributed solution.

### 3. Client-Side Catalog Filtering
* **Why Considered:** Fetching all books once and filtering them in memory in JavaScript.
* **Why Rejected:** Fails at scale once the catalog contains thousands of records. `SPEC.md` explicitly required server-side query parameters (`q`, `min_price`, `max_price`, `sort`, `limit`, `offset`) with pre-pagination total counts.

---

## 9. Testing Strategy, Fixtures & Concurrency Verification

### The Test Harness (`tests/conftest.py`)
* **Acceptance Suite:** 202 tests across 6 test modules (`test_books.py`, `test_health.py`, `test_loans.py`, `test_members.py`, `test_orders.py`, `test_reports.py`).
* **In-Memory SQLite:** Each test receives a fresh in-memory database instance (`sqlite:///:memory:`), ensuring total isolation and zero state leakage between tests.
* **FrozenClock Fixture:** Tests initialize at `2026-01-01T12:00:00`. Tests advance time using `clock.advance(days=15)` to verify due date boundaries and late fee calculations instantly without waiting for real time.

### PostgreSQL Integration Testing (`integration_tests/`)
* Created an automated integration harness that runs the entire test suite against a live Supabase PostgreSQL database.
* **Schema Isolation:** Generates a disposable schema (`pytest_<uuid>`) per test run, runs tests against PostgreSQL, and drops the schema upon completion.
* **Verification:** Confirmed that all 202 tests pass against both SQLite and PostgreSQL, verifying that SQL dialects, row locking, and date serializations behave identically across database engines.

---

## 10. Deployment Architecture (Render & Supabase)

### Infrastructure Blueprint
* **Compute Platform:** [Render](https://render.com) (Web Service).
  * Runtime: Python 3.10+ managed via `uv`.
  * Build Command: `uv sync --frozen` (installs exact locked dependencies from `uv.lock`).
  * Start Command: `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
* **Database Platform:** [Supabase](https://supabase.com) (Hosted PostgreSQL).
  * Connected via connection pooling URL supplied in `SANCTUM_DATABASE_URL`.
  * Automatic table creation and demo seeding executed in `app/main.py` lifespan handler on startup.
* **Live Deployment:** [https://sanctum-sanctorum-hmqe.onrender.com](https://sanctum-sanctorum-hmqe.onrender.com)
* **Interactive API Docs:** [https://sanctum-sanctorum-hmqe.onrender.com/docs](https://sanctum-sanctorum-hmqe.onrender.com/docs)

---

## 11. Git Commit Chronology & Engineering Narrative

The Git history consists of 23 logical, incremental commits demonstrating a deliberate engineering workflow:

1. `036b2aa` **Initialize bookstore assignment baseline** — Initial repository commit.
2. `4e24ced` **Validate ISBN-13 checksums and reject duplicate books** — Completed ISBN normalizer and book uniqueness logic.
3. `35c6a2e` **Add partial book updates** — Implemented `PATCH /books/{id}` ignoring ISBN.
4. `45da2a5` **Complete book catalogue listing** — Implemented search query, filters, sorting, and pagination.
5. `5bc90fd` **Complete member validation and access rules** — Email normalization and tier hierarchy validation.
6. `03c1520` **Validate order item collections** — Added Pydantic validator rejecting empty orders and duplicate books.
7. `c3e368b` **Implement order creation and pricing** — Tier/volume discount math and stock reservation.
8. `5267369` **Restore stock when cancelling orders** — Handled pending order cancellation and inventory rollback.
9. `04986e9` **Implement loan borrowing and status calculation** — Loan schema migration, borrow limits, read-time status derivation.
10. `9dab20c` **Implement loan returns, late fees, and listings** — Return handling, `ceil` late fee formula, loan listing filters.
11. `52018d0` **Implement member activity statistics** — Aggregate stats computation across orders and loans.
12. `6c1804e` **Implement top books sales report** — Group-by sales query over paid orders.
13. `a2bda6f` **Wire frontend loan return action** — Connected frontend UI button to return endpoint.
14. `be96e3d` **Support PostgreSQL deployments** — Added `psycopg` dependency and dynamic engine configuration.
15. `4b6fecd` **Ignore local Supabase integration harness** — Configured `.gitignore` for local integration suite.
16. `960d28e` **Add Render deployment blueprint** — Created `render.yaml` infrastructure file.
17. `ec62948` **Document deployment and project decisions** — Initial architecture and deployment notes in `NOTES.md`.
18. `bcdf5c0` **Add paginated member listing** — Implemented optional `GET /members` endpoint.
19. `ebc2b01` **Lock books during order stock reservation** — Implemented optional PostgreSQL row-level locking.
20. `3d0ee5d` **Document completed optional features** — Updated `NOTES.md` with optional feature verification.
21. `c986260` **Refine AI usage section in submission notes** — Outlined developer ownership and AI collaboration.
22. `aa4d8c0` **Update assistant attribution to OpenAI Codex in NOTES.md** — Attributed OpenAI Codex as development assistant.
23. `bf88e04` **Document spec trade-offs and future production improvements in NOTES.md** — Added spec critique and production roadmap.

---

## 12. Master Technical Interview Q&A Bank

### Category 1: Architecture & Framework
#### Q1: Why did you keep routers thin and move all logic into services?
**Answer:** "Thin routers treat HTTP as an implementation detail. Routers are only responsible for parsing HTTP inputs, dependency injection, and HTTP status codes. Business rules—such as discount calculations, loan limits, and stock mutations—live in pure service functions. This ensures business logic can be reused across different entry points (e.g., CLI tools, background workers) and tested in isolation without HTTP mocking."

#### Q2: Why use dependency injection for `get_now` instead of `datetime.now()`?
**Answer:** "Directly calling `datetime.now()` introduces non-deterministic side effects into domain logic, making time-travel testing impossible. By injecting `get_now` via FastAPI's `Depends(get_now)`, our test suite can inject a `FrozenClock` that advances time instantaneously (`clock.advance(days=15)`). In production, FastAPI injects real UTC time seamlessly."

#### Q3: Why is loan status computed at read time rather than stored in a database column?
**Answer:** "If status were stored in the database (e.g., `status = 'active'`), a loan would not transition to `'overdue'` when its due date passes unless a background cron job constantly scanned and updated the table. Deriving the status at read time (`if returned_at: 'returned' elif now > due_at: 'overdue' else: 'active'`) guarantees the status is always 100% accurate the instant it is queried, eliminating the need for periodic batch jobs."

---

### Category 2: Databases, ACID & Concurrency
#### Q4: How did you solve the concurrent last-copy problem in orders?
**Answer:** "When multiple users simultaneously order the last available copy of a book, a standard `SELECT` followed by an `UPDATE` creates a race condition (read-modify-write hazard). Both transactions see `stock == 1` and decrement it to 0, resulting in overselling.
I solved this using PostgreSQL row-level locking:
`select(Book).where(Book.id.in_(book_ids)).order_by(Book.id).with_for_update()`.
This issues a `SELECT ... FOR UPDATE`, placing an exclusive lock on the book rows until the transaction commits or aborts. The second transaction blocks until the first completes, at which point it reads the updated `stock == 0` and cleanly aborts with HTTP 409."

#### Q5: Why did you sort `Book.id` before acquiring the row lock?
**Answer:** "To eliminate deadlocks. If Transaction A orders books [1, 2] and Transaction B orders books [2, 1], Transaction A locks row 1 and waits for row 2, while Transaction B locks row 2 and waits for row 1. They would deadlock. Sorting the IDs ensures every transaction acquires row locks in identical numerical order, mathematically eliminating the cyclic dependency required for deadlocks."

#### Q6: How does the application ensure all-or-nothing stock reservation?
**Answer:** "In `create_order`, we iterate over all items to verify stock availability *before* decrementing any inventory. If even one book has insufficient stock, we raise an HTTP 409 before modifying any entity. Furthermore, because all operations occur within a single SQLAlchemy transaction session, any unexpected runtime exception triggers an automatic rollback, ensuring database consistency."

#### Q7: Why do tests use SQLite while production uses PostgreSQL?
**Answer:** "SQLite in-memory is fast, self-contained, and requires zero external infrastructure, allowing `uv run pytest` to run 202 tests in seconds on any developer machine. However, SQLite has limited concurrency support (database-level locking) and lacks persistence on serverless hosts. In production on Render, we use hosted PostgreSQL on Supabase, which provides robust multi-version concurrency control (MVCC) and persistent storage."

---

### Category 3: Domain Rules & Edge Cases
#### Q8: What happens when a loan is returned exactly at `due_at`?
**Answer:** "The spec mandates a strict boundary: at exactly `due_at`, the loan is still considered `active` and owes zero late fee. Overdue status and fees apply only when `now > due_at`. In `calculate_late_fee`, if `returned_at <= due_at`, it returns 0 immediately."

#### Q9: How is the late fee calculated for partial days?
**Answer:** "Any started partial day counts as a full day. We compute elapsed seconds `(returned_at - due_at).total_seconds()`, divide by 86,400 seconds (1 day), and apply `math.ceil()`. This integer is multiplied by 25 cents. Finally, the total is capped at the book's current price: `min(days_late * 25, book.price_cents)`."

#### Q10: How does ISBN-13 checksum validation work?
**Answer:** "First, we strip spaces and hyphens and verify the string is exactly 13 digits. The check digit is calculated by alternating weights of 1 and 3 across the first 12 digits:
$$\text{sum} = \sum_{i=0}^{11} d_i \times (1 \text{ if } i \text{ is even else } 3)$$
The expected check digit is $(10 - (\text{sum} \bmod 10)) \bmod 10$. If the 13th digit does not match, the schema raises a validation error resulting in HTTP 422."

#### Q11: What discount rules apply to orders?
**Answer:** "There are two discount components:
1. **Tier discount:** Apprentice 0%, Adept 5%, Master 10%, Supreme 15%.
2. **Bulk volume discount:** An additional +5% if the total sum of book quantities in the order is $\ge 10$.
Discounts are combined additively before applying to the subtotal. Discount cents are floored using integer division (`subtotal * percent // 100`), and `total_cents = subtotal - discount_cents`."

---

### Category 4: Critique, Trade-Offs & Production Roadmap
#### Q12: Did you notice any flaws or trade-offs in the specification?
**Answer:** "Yes, two major observations:
1. **Dynamic Late Fee Cap vs. Fixed Order Prices:** In orders, the book's price is snapshotted at purchase time so later price adjustments don't affect past transactions. In loans, however, the late fee cap uses the book's price *at the time of return*. If the store increases a book's price while a member has it on loan, their maximum late fee penalty retroactively increases. In a production domain, I would snapshot `price_cents` on the `Loan` record at checkout time to make the fee cap immutable.
2. **Engine Collation Differences:** SQLite performs ASCII-based case-sensitive sorting (uppercase before lowercase), while PostgreSQL uses environmental collation (often case-insensitive). Following the spec's advice to leave sorting engine-native avoids applying `func.lower()` on database columns, which would bypass standard B-tree indexes."

#### Q13: What would you do before releasing this to high-traffic production?
**Answer:**
1. **Alembic Migrations:** Replace `Base.metadata.create_all()` with version-controlled schema migrations to support zero-downtime deployments.
2. **Targeted B-tree Indexes:** Add composite indexes on high-frequency query paths, such as `loans(member_id, returned_at)` and `orders(member_id, status)`.
3. **Idempotency Keys:** Require an `Idempotency-Key` header on `POST /orders` and `POST /loans` to prevent double-charging or duplicate bookings during client retries on unstable networks.
4. **Authentication & Authorization:** Replace the untrusted `member_id` parameters in request bodies with validated JWT/OAuth2 session tokens.

---

### Category 5: AI Collaboration & Engineering Ownership
#### Q14: How did you use AI during this project?
**Answer:** "I used OpenAI Codex as an interactive assistant for rapid scaffolding—generating repetitive Pydantic boilerplate, looking up SQLAlchemy 2.0 query methods, and reviewing edge cases against `SPEC.md`. I maintained full architectural ownership, authored the service logic, and critically reviewed every suggestion."

#### Q15: Where was the AI wrong or unhelpful, and how did you override it?
**Answer:**
1. **Concurrency Locking:** The AI initially recommended using Python's in-memory `threading.Lock` for stock reservations. I rejected that because it fails across multi-worker ASGI processes in production, and instead implemented PostgreSQL row locking (`with_for_update()`).
2. **Date Truncation Bug:** The AI attempted to calculate overdue days using `.days` on timedelta, which truncates and loses partial-day fees. I corrected it to use `math.ceil` on total elapsed seconds to meet the spec's partial-day fee requirement.
3. **Supabase Connectivity:** The AI generated standard direct host connection strings that stalled due to local IPv4 network constraints. I diagnosed the issue and reconfigured the deployment to use the Supabase Session Pooler endpoint.
