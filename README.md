# DataPilot AI - Backend

DataPilot AI is an evidence-driven AI data investigation platform. This backend provides high-performance CSV dataset ingestion, validation, statistical profiling, and metadata persistence built with FastAPI, SQLAlchemy 2.0, Alembic, and PostgreSQL.

---

## Table of Contents

- [Architecture & Module Organization](#architecture--module-organization)
- [Requirements](#requirements)
- [First-Time Setup](#first-time-setup)
- [Environment Configuration](#environment-configuration)
- [Database Setup & Migrations](#database-setup--migrations)
- [Running the Server](#running-the-server)
- [API Documentation & Endpoints](#api-documentation--endpoints)
  - [System Endpoints](#system-endpoints)
  - [Dataset Endpoints](#dataset-endpoints)
- [Validation & Error Handling](#validation--error-handling)
- [Testing & Test Safety](#testing--test-safety)

---

## Architecture & Module Organization

The backend enforces a clean separation of concerns across presentation, domain logic, and persistence layers:

```text
datapilot/
├── alembic/                      # Database migration scripts (Alembic)
│   ├── versions/                 # Revision scripts (e.g. f424885817e6_create_datasets_table.py)
│   └── env.py                    # Alembic migration environment (reads app.database.engine)
├── alembic.ini                   # Alembic configuration
├── backend/                      # Backend application source
│   ├── app/
│   │   ├── api/                  # API presentation layer (HTTP routes & validation)
│   │   │   ├── __init__.py       # Aggregates system & dataset routers into api_router
│   │   │   ├── datasets.py       # REST endpoints for dataset upload, inspect, and retrieval
│   │   │   └── system.py         # System welcome and database health check endpoints
│   │   ├── models/               # SQLAlchemy ORM database models
│   │   │   ├── __init__.py       # Re-exports Dataset model
│   │   │   └── dataset.py        # Dataset entity mapping to 'datasets' table
│   │   ├── schemas/              # Pydantic validation & response schemas
│   │   │   ├── __init__.py       # Re-exports DatasetSummary and DatasetDetail
│   │   │   └── dataset.py        # DatasetSummary (listing) and DatasetDetail (full view)
│   │   ├── services/             # Business & domain logic layer
│   │   │   ├── __init__.py       # Re-exports service functions & domain exceptions
│   │   │   └── dataset.py        # CSV parsing, profiling, exclusive file creation, transactions
│   │   ├── config.py             # Application settings validated with Pydantic BaseSettings
│   │   ├── database.py           # Database URL construction, engine pool, and session generator
│   │   ├── datasets.py           # Backward-compatible re-export shim for legacy imports
│   │   ├── main.py               # FastAPI application factory (create_app), lifespan, global 500 handler
│   │   └── profiling.py          # Dataframe statistical profiling engine
│   └── requirements.txt          # Production and development dependencies
├── data/                         # Local storage
│   └── uploads/                  # Ingested CSV files stored as {dataset_id}.csv
├── tests/                        # Automated test suite
│   ├── fixtures.py               # Shared test base, DB isolation safety checks, mock data
│   ├── test_config.py            # Settings validation and precedence tests
│   ├── test_database_lifecycle.py# Connection pool and session lifecycle tests
│   ├── test_dataset_service.py   # Service-layer business logic and storage tests
│   ├── test_datasets_api.py      # End-to-end dataset API integration tests
│   ├── test_profiling.py         # Statistical profiling unit tests
│   └── test_system_api.py        # App factory, health check, and backward-compatibility tests
├── .env.example                  # Environment configuration template
└── README.md                     # Backend documentation
```

### Architectural Principles

1. **API Router Layer (`backend/app/api/`)**: Focuses strictly on HTTP-level concerns: receiving `UploadFile` requests, parsing headers, verifying basic size/extension constraints, managing file close lifecycles, and mapping service exceptions to HTTP status codes.
2. **Service Layer (`backend/app/services/dataset.py`)**: Completely decoupled from FastAPI. Accepts native Python types (`bytes`, `str`, `Session`, `Path`). Handles CSV parsing, statistical profiling, exclusive file creation (`open("xb")`), directory resolution (with external upload path fallbacks), database transactions, compensating file unlinking on commit failure, and retrieval queries.
3. **Database & Lifecycle Layer (`backend/app/database.py`, `backend/app/main.py`)**: Implements engine connection pooling with automatic disposal during FastAPI `lifespan` shutdown, explicit transaction rollbacks on route exceptions, and safe session closure.

---

## Requirements

- Python 3.11+ (Python 3.13 supported)
- PostgreSQL 14+
- Virtual environment (`venv`)

---

## First-Time Setup

1. **Create and activate a Python virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install project dependencies**:
   ```bash
   pip install -r backend/requirements.txt
   ```

3. **Configure environment settings**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your PostgreSQL database credentials and settings.

4. **Ensure PostgreSQL is running**:
   PostgreSQL must be active, and the configured target database (e.g. `datapilot`) must exist before executing database migrations.

---

## Environment Configuration

Configuration is loaded from environment variables and an optional `.env` file via `pydantic-settings`. Template settings are documented in `.env.example`:

```bash
cp .env.example .env
```

### Configuration Variables

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `DATABASE_URL` | `str \| None` | `None` | Optional complete PostgreSQL connection URL (`postgresql+psycopg://...`). **Takes precedence** over discrete `DB_*` variables. |
| `DB_USER` | `str \| None` | `None` | Database user (required if `DATABASE_URL` is omitted). |
| `DB_PASSWORD` | `str \| None` | `None` | Database password (required if `DATABASE_URL` is omitted). |
| `DB_HOST` | `str` | `"localhost"` | Database hostname or IP address. |
| `DB_PORT` | `int` | `5432` | Database port (validated between `1` and `65535`). |
| `DB_NAME` | `str` | `"datapilot"` | Database name. |
| `DB_POOL_SIZE` | `int` | `5` | SQLAlchemy connection pool size (validated between `1` and `100`). |
| `DB_MAX_OVERFLOW`| `int` | `10` | Maximum connection overflow above pool size (validated between `0` and `100`). |
| `DB_POOL_TIMEOUT` | `int` | `30` | Seconds to wait before timing out on pool checkout (validated between `1` and `300`). |
| `DB_POOL_RECYCLE` | `int` | `1800` | Seconds after which idle connections are recycled (validated between `60` and `86400`). |
| `TEST_DATABASE_URL`| `str \| None` | `None` | **Isolated test database URL**. Required to run integration tests; must end with `_test`. |

> **Precedence & Validation Rule**: You may configure either a complete `DATABASE_URL` or discrete variables (`DB_USER`, `DB_PASSWORD`, etc.). If `DATABASE_URL` is provided, `DB_USER` and `DB_PASSWORD` may be omitted. If `DATABASE_URL` is omitted, both `DB_USER` and `DB_PASSWORD` are strictly required. Unknown extra keys in `.env` are safely ignored (`extra="ignore"`).

---

## Database Setup & Migrations

### 1. Create the Database

PostgreSQL must be running before creating the database. Using `psql`:

```sql
CREATE DATABASE datapilot;
```

For running the automated test suite, create an isolated test database whose name ends in `_test`:

```sql
CREATE DATABASE datapilot_test;
```

### 2. Run Database Migrations

Alembic manages schema migrations. The configured database must exist before running migrations:

```bash
# Apply all pending migrations
PYTHONPATH=backend alembic upgrade head

# View current migration revision
PYTHONPATH=backend alembic current

# Revert the latest migration (if needed)
PYTHONPATH=backend alembic downgrade -1
```

---

## Running the Server

Start the application with Uvicorn bound to local interface `127.0.0.1`:

```bash
# Using uvicorn directly
PYTHONPATH=backend uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Or via Python module
PYTHONPATH=backend python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Interactive API Documentation

Once running, interactive documentation is available at:
- **Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **OpenAPI JSON**: [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

---

## API Documentation & Endpoints

### System Endpoints

#### `GET /`
Returns a welcome message confirming the service is active.
- **Status Code**: `200 OK`
- **Response**:
  ```json
  {
    "message": "Welcome to DataPilot AI!"
  }
  ```

#### `GET /health/db`
Performs a live connectivity check against PostgreSQL (`SELECT 1`).
- **Status Code**:
  - `200 OK`: Database connected.
    ```json
    {
      "status": "healthy",
      "database": "connected"
    }
    ```
  - `503 Service Unavailable`: Database unreachable or connection failure.
    ```json
    {
      "detail": "Database connection failed"
    }
    ```

---

### Dataset Endpoints

All dataset endpoints are prefixed with `/api/datasets`.

#### `POST /api/datasets/inspect`
Inspects a CSV file in memory without saving it to disk or PostgreSQL. Generates column metadata and statistical profiles. (Note: Enforces `.csv` extension, non-empty, and `<= 10 MB` size constraints, but does not enforce the 255-character filename limit required for database persistence).
- **Content-Type**: `multipart/form-data`
- **Request Body**: `file` (binary CSV file)
- **Status Code**: `200 OK`
- **Response**:
  ```json
  {
    "filename": "employees.csv",
    "total_rows": 3,
    "total_columns": 4,
    "columns": [
      { "name": "name", "data_type": "object" },
      { "name": "age", "data_type": "int64" },
      { "name": "salary", "data_type": "int64" },
      { "name": "city", "data_type": "object" }
    ],
    "profile": {
      "total_missing_values": 0,
      "duplicate_rows": 0,
      "columns": [
        {
          "name": "age",
          "data_type": "int64",
          "missing_values": 0,
          "unique_values": 3,
          "statistics": {
            "count": 3,
            "mean": 30.0,
            "std": 5.0,
            "min": 25.0,
            "median": 30.0,
            "max": 35.0
          }
        }
      ]
    }
  }
  ```

#### `POST /api/datasets/upload`
Uploads, parses, profiles, exclusively stores (`open("xb")`), and persists a dataset in PostgreSQL. Enforces filename length `<= 255` characters.
- **Content-Type**: `multipart/form-data`
- **Request Body**: `file` (binary CSV file)
- **Status Code**: `201 Created`
- **Response Model**: `DatasetDetail`
- **Response**:
  ```json
  {
    "id": "c3d4e5f6-a7b8-1234-5678-9abcdef01234",
    "filename": "employees.csv",
    "total_rows": 3,
    "total_columns": 4,
    "created_at": "2026-11-19T10:00:00Z",
    "columns": [...],
    "profile": {...}
  }
  ```

#### `GET /api/datasets/`
Lists all persisted datasets ordered by `created_at` descending.
- **Status Code**: `200 OK`
- **Response Model**: `list[DatasetSummary]`
- **Response**:
  ```json
  [
    {
      "id": "c3d4e5f6-a7b8-1234-5678-9abcdef01234",
      "filename": "employees.csv",
      "total_rows": 3,
      "total_columns": 4,
      "created_at": "2026-11-19T10:00:00Z"
    }
  ]
  ```

#### `GET /api/datasets/{dataset_id}`
Retrieves detailed metadata, column types, and statistical profile for a single dataset by UUID.
- **Status Code**:
  - `200 OK`: Dataset found (`DatasetDetail`).
  - `404 Not Found`: Dataset ID does not exist (`{"detail": "Dataset not found"}`).
  - `422 Unprocessable Entity`: `dataset_id` is not a valid UUID string.

---

## Validation & Error Handling

DataPilot AI uses strict validation and standardized JSON error responses across all routes.

### Validation Rules

1. **File Extension**: Must end with `.csv` (case-insensitive).
   - Violation: `400 Bad Request` $\rightarrow$ `{"detail": "Only CSV files are allowed"}`
2. **Filename Length**: Must not exceed 255 characters (enforced by the upload endpoint, not the inspect endpoint).
   - Violation: `400 Bad Request` $\rightarrow$ `{"detail": "Filename must not exceed 255 characters"}`
3. **Payload Size**: File size must not exceed 10 MB (10,485,760 bytes).
   - Violation: `413 Payload Too Large` $\rightarrow$ `{"detail": "File size must not exceed 10 MB"}`
4. **Non-Empty File**: Payload must contain at least 1 byte.
   - Violation: `400 Bad Request` $\rightarrow$ `{"detail": "Uploaded file is empty"}`
5. **CSV Structure & Headers**:
   - Empty CSV / whitespace-only: `400 Bad Request` $\rightarrow$ `{"detail": "CSV contains no data or column headers"}`
   - Corrupt or invalid character encoding: `400 Bad Request` $\rightarrow$ `{"detail": "Invalid CSV format or encoding"}`
   - Headerless / zero-column dataframe: `400 Bad Request` $\rightarrow$ `{"detail": "CSV must contain at least one column"}`
6. **UUID Validation**: Path parameters expecting UUIDs are validated by FastAPI.
   - Violation: `422 Unprocessable Entity` $\rightarrow$ FastAPI standard validation detail list.

### Persistence Safety & Failure Recovery

- **Exclusive File Creation**: Files are created with mode `"xb"` (`open(storage_path, "xb")`). If a file with the target name already exists, it is never overwritten or deleted.
- **Compensating Rollback & File Unlink**:
  - If database persistence (`db.commit()` or `db.refresh()`) raises `SQLAlchemyError`, the transaction is rolled back and the newly created upload file is unlinked from disk.
  - Returns `500 Internal Server Error` $\rightarrow$ `{"detail": "Failed to save dataset metadata"}`.
  - Rollback or unlinking errors are safely caught and never mask the primary database error.
- **Partial File Write Cleanup**:
  - If writing to disk fails midway (`OSError`), the partial file is removed.
  - Returns `500 Internal Server Error` $\rightarrow$ `{"detail": "Failed to store uploaded CSV file"}`.
- **Global Server Error Sanitization**:
  - All uncaught `Exception` instances are captured by the global application error handler, logged server-side via `logger.exception`, and returned as generic JSON: `500 Internal Server Error` $\rightarrow$ `{"detail": "Internal server error"}`.
  - Raw SQL statements, filesystem paths, and Python tracebacks are never exposed to clients.

---

## Testing & Test Safety

### Test Isolation Guardrail

To prevent accidental data loss in development environments, the test suite enforces strict database safety rules:
1. Integration tests **strictly require** the `TEST_DATABASE_URL` environment variable.
2. The database name in `TEST_DATABASE_URL` **must end in `_test`** (e.g., `datapilot_test`).
3. The test suite automatically compares normalized host, port, and database names and **aborts immediately** if `TEST_DATABASE_URL` matches the development `DATABASE_URL`.

### Running Tests

Execute tests from the repository root with the virtual environment activated (`source .venv/bin/activate`). Setting `PYTHONPATH=backend` is required so Python can locate the `app` package.

Execute the full test suite using Python's `unittest` runner:

```bash
TEST_DATABASE_URL="postgresql+psycopg://postgres:your_password@localhost:5432/datapilot_test" \
PYTHONPATH=backend python -m unittest discover -s tests -v
```

### Running Specific Test Modules

```bash
# Configuration and environment validation tests (database-independent)
PYTHONPATH=backend python -m unittest tests/test_config.py -v

# Connection pool and session lifecycle tests (database-independent)
PYTHONPATH=backend python -m unittest tests/test_database_lifecycle.py -v

# Statistical profiling unit tests (database-independent)
PYTHONPATH=backend python -m unittest tests/test_profiling.py -v

# System endpoints, health checks, and backward-compatibility tests
PYTHONPATH=backend python -m unittest tests/test_system_api.py -v

# Dataset service-layer unit and storage tests (requires test DB)
TEST_DATABASE_URL="postgresql+psycopg://postgres:your_password@localhost:5432/datapilot_test" \
PYTHONPATH=backend python -m unittest tests/test_dataset_service.py -v

# Dataset API integration and error handling tests (requires test DB)
TEST_DATABASE_URL="postgresql+psycopg://postgres:your_password@localhost:5432/datapilot_test" \
PYTHONPATH=backend python -m unittest tests/test_datasets_api.py -v
```
