# Swarn Bharat

FastAPI backend, PostgreSQL with pgvector, Redis, Celery worker, and plain HTML test console.

## Requirements

- **Python 3.12** (system installation or managed)
- **uv** (fast Python package and project manager)
- **Docker & Docker Compose** (PostgreSQL 16 with pgvector, Redis 7)

## Repository Layout

```text
Swarn_Bharat/
├── backend/
│   ├── alembic/              # Database migration scripts and env
│   ├── src/backend/          # Application source code (FastAPI, core, models, api, worker)
│   ├── tests/                # Automated test suite (pytest)
│   └── pyproject.toml        # Backend package definition
├── packages/
│   └── shared/               # Shared library (swarnbharat_shared: schemas, common enums)
├── docker/
│   ├── postgres/             # PostgreSQL initialization scripts
│   └── docker-compose.yml    # Local development services (Postgres, Redis)
├── docs/
│   └── adr/                  # Architecture Decision Records (ADRs)
├── scripts/                  # Operational and verification scripts (verify, prepare_test_db, etc.)
├── test-console/             # Frontend test console (vanilla HTML/JS)
├── openapi.json              # Versioned authoritative OpenAPI specification
└── pyproject.toml            # Root workspace configuration and shared tooling
```

## Architecture Decision Records (ADRs)

Key architectural decisions are documented under [`docs/adr/`](docs/adr):
- [ADR 0001: Error Envelope](docs/adr/0001-error-envelope.md) - Standardized JSON envelopes for success and error responses.
- [ADR 0002: Rate Limiter](docs/adr/0002-rate-limiter.md) - Fail-closed token bucket rate limiting with Redis fallback.

## Quick Start

```bash
# 1. Copy env template (fill in real values before running)
cp .env.example .env

# 2. Start Postgres and Redis
docker compose --env-file .env -f docker/docker-compose.yml up -d

# 3. Install dependencies in uv workspace
uv sync --all-packages

# 4. Run database migrations
cd backend && uv run alembic upgrade head && cd ..

# 5. Start the API server
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

## Git Hooks

Enable repository git hooks to run all verification gates before pushing:

```bash
git config core.hooksPath .githooks
```

## Verification & Development

Run all verification gates (Ruff lint and format check, mypy strict type check, OpenAPI sync check, tracked files check, and pytest):

```bash
python scripts/verify.py
```

Individual checks:

```bash
# Linting and formatting
uv run python -m ruff check .
uv run python -m ruff format --check .

# Type checking
uv run python -m mypy backend/src packages/shared/src backend/alembic scripts backend/tests

# Prepare test database (creates swarnbharat_test and applies migrations)
uv run python scripts/prepare_test_db.py

# Tests (requires Docker services to be running)
uv run python -m pytest backend/tests -v

# Sync and verify OpenAPI schema
uv run python scripts/export_openapi.py
uv run python scripts/export_openapi.py --check
```

## Dependency Constraints

`pyproject.toml` defines `constraint-dependencies = ["kombu<5.7"]`. This avoids unreleased release candidates (such as kombu 5.7.0rc1) and caps `redis<6.5` (resolving to stable redis 6.4.0) to maintain stable async connection pool semantics across Celery and application code.

## Redis Topology

The system targets a standalone single-node Redis deployment utilizing separate logical database numbers for key isolation (rate limiting, tokens, throttling, and task broker). It does not support Redis Cluster, which restricts multi-database indexing to DB 0.

## Health Probes

- `GET /api/v1/health/live`: Liveness probe returning HTTP 200 as long as the process is running.
- `GET /api/v1/health/ready`: Readiness probe checking PostgreSQL and Redis connectivity. Returns HTTP 200 when all dependencies are reachable, or HTTP 503 (`SERVICE_UNAVAILABLE`) with an ErrorResponse naming unavailable dependencies if degraded.

## API Documentation

- Swagger UI: `http://localhost:8000/api/v1/docs`
- ReDoc: `http://localhost:8000/api/v1/redoc`
- OpenAPI JSON: `http://localhost:8000/api/v1/openapi.json`

The committed `openapi.json` at repository root serves as the authoritative contract.

## Test Console

Open `test-console/index.html` directly in any web browser. It interacts with the backend API via standard `fetch` calls.

## Deployment notes

In production deployments behind a reverse proxy (such as Nginx, Cloudflare, or AWS ALB), run Uvicorn with `--proxy-headers` and explicitly list trusted proxy IPs:

```bash
uv run uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips="<proxy IPs>"
```

Never set `--forwarded-allow-ips="*"` in production, as trusting arbitrary proxy headers allows clients to spoof `X-Forwarded-For` and circumvent client IP identification. Rate limiting relies on the client IP populated by Uvicorn's proxy headers handling; see [ADR 0002: Rate Limiter](docs/adr/0002-rate-limiter.md). Do not add app-level `X-Forwarded-For` parsing. Ensure `ENFORCE_HTTPS=true`, `ALLOWED_HOSTS`, and `CORS_ORIGINS` are configured for production environments.

## Celery Worker

```bash
uv run celery -A backend.worker.celery_app.celery_app worker --loglevel=info --concurrency=4
```
