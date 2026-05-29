# Distributed Rate Limiter

A production-grade distributed rate limiting system built with FastAPI and Redis. Implements two battle-tested algorithms — **Token Bucket** and **Sliding Window** — using atomic Redis Lua scripts to eliminate race conditions across multiple servers. Includes response caching, full Prometheus observability, security hardening, and 97% test coverage.

---

## Table of Contents

- [What Problem This Solves](#what-problem-this-solves)
- [Architecture](#architecture)
- [Rate Limiting Algorithms](#rate-limiting-algorithms)
- [Why Lua Scripts](#why-lua-scripts)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Setup and Running](#setup-and-running)
- [API Endpoints](#api-endpoints)
- [Response Headers](#response-headers)
- [Configuration](#configuration)
- [Running Tests](#running-tests)
- [Load Testing](#load-testing)
- [Observability](#observability)
- [Production Hardening Checklist](#production-hardening-checklist)
- [Bugs Fixed During Development](#bugs-fixed-during-development)
- [Tech Stack](#tech-stack)

---

## What Problem This Solves

When you run an API, one user or bot sending thousands of requests can degrade service for everyone else. A naive in-memory counter fails the moment you run more than one server — Server A has no idea how many requests Server B already allowed for that user.

This system solves that by storing all state in Redis — a shared external store accessible to every server simultaneously — with atomic Lua scripts ensuring no two servers can produce a race condition on the same counter.

---

## Architecture

```
Incoming Request
      │
      ▼
SecurityHeadersMiddleware    ← adds security headers to every response
      │
      ▼
RequestIDMiddleware          ← stamps X-Request-ID for distributed tracing
      │
      ▼
CORSMiddleware               ← handles cross-origin preflight and headers
      │
      ▼
RateLimitMiddleware          ← checks Redis: allow or return HTTP 429
      │
      ▼
CacheMiddleware              ← serve from Redis cache or hit route handler
      │
      ▼
Route Handler                ← your actual API logic
```

> Middleware executes in reverse registration order.
> Rate limiting runs **before** caching — a blocked request never touches the cache.

---

## Rate Limiting Algorithms

### Token Bucket

Each user gets a bucket with capacity 100 tokens. Every request costs 1 token. Tokens refill at 1.67/second (100/minute). An idle user accumulates tokens up to capacity and can burst. Stored in Redis as a **Hash**: `{tokens, last_refill}`.

**Best for:** APIs where natural burst traffic is acceptable — most REST APIs.

### Sliding Window Log

Stores every request timestamp in a Redis **Sorted Set**. On each request, removes entries older than the window, counts remaining, rejects if at limit. True sliding window — no fixed boundary spike at the top of every minute.

**Best for:** billing, financial, or fairness-critical APIs where a fixed-window boundary burst is unacceptable.

**Switch between them in `.env`:**
```env
RATE_LIMIT_STRATEGY=token_bucket    # or sliding_window
```

### Algorithm Comparison

| Property | Token Bucket | Sliding Window |
|---|---|---|
| Redis structure | Hash | Sorted Set |
| Time complexity | O(1) | O(log N) |
| Burst handling | Allows burst up to capacity | Strict — no boundary spike |
| Memory per user | Fixed (2 fields) | Grows with request count |
| Best for | General APIs | Financial / billing APIs |

---

## Why Lua Scripts

Both algorithms execute as **Lua scripts inside Redis**. This is the most important design decision in the project.

Without Lua, a rate limit check requires three separate Redis commands:
1. GET current count
2. Check if under limit
3. SET new count

Between steps 1 and 3, another server can read the same stale value and allow two requests when only one should be permitted. This is a **race condition**.

Lua scripts execute **atomically** inside Redis. The entire read-check-write is one indivisible operation. No two scripts can interleave. This guarantees accuracy regardless of how many application servers run simultaneously.

---

## Project Structure

```
distributed-rate-limiter/
├── app/
│   ├── main.py                    — app factory, middleware stack, lifespan
│   ├── core/
│   │   ├── config.py              — settings via Pydantic BaseSettings + .env
│   │   ├── redis.py               — connection pool, retry logic, health check
│   │   └── logging.py             — JSON or plain formatter, log level config
│   ├── api/
│   │   ├── health.py              — /health (liveness) /health/ready (readiness)
│   │   ├── demo.py                — demo endpoints to verify middleware headers
│   │   └── metrics_route.py       — /metrics Prometheus scrape endpoint
│   ├── middleware/
│   │   ├── rate_limit.py          — identifier extraction, limit check, headers
│   │   ├── cache.py               — cache lookup, store on miss, skip binary/POST
│   │   ├── security.py            — security headers on every response
│   │   └── request_id.py          — X-Request-ID generation and propagation
│   ├── services/
│   │   ├── rate_limiter.py        — strategy pattern, algorithm selection, fallback
│   │   ├── token_bucket.py        — Lua script + Redis Hash implementation
│   │   ├── sliding_window.py      — Lua script + Redis Sorted Set implementation
│   │   └── cache.py               — key building, get/set/delete/invalidate_pattern
│   └── utils/
│       └── metrics.py             — Prometheus counter, histogram, gauge definitions
├── tests/
│   ├── conftest.py                — session-scoped app with fully mocked Redis
│   ├── test_api.py                — integration tests through full middleware stack
│   ├── test_redis.py              — Redis core tests (run in isolation — see below)
│   ├── test_rate_limiter.py       — unit tests for rate limiter service
│   ├── test_token_bucket.py       — unit tests for token bucket algorithm
│   ├── test_sliding_window.py     — unit tests for sliding window algorithm
│   ├── test_cache_service.py      — unit tests for cache service
│   ├── test_middleware_rate_limit.py
│   ├── test_middleware_extra.py
│   ├── test_logging.py
│   └── test_metrics.py
├── monitoring/
│   └── prometheus.yml             — Prometheus scrape config
├── locustfile.py                  — load test scenarios
├── requirements.txt
├── .env.example                   — copy to .env and fill in values
├── pytest.ini
└── README.md
```

---

## Prerequisites

- Python 3.10+
- Redis 7.x
- Git

---

## Setup and Running

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/distributed-rate-limiter.git
cd distributed-rate-limiter
```

### 2. Create and activate virtual environment

```bash
python -m venv venv

# Linux / Mac / WSL
source venv/bin/activate

# Windows CMD
venv\Scripts\activate
```

You should see `(venv)` at the start of your terminal prompt.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env if needed — defaults work for local development
```

### 5. Start Redis

```bash
# WSL / Linux
sudo service redis-server start

# Docker
docker run -d -p 6379:6379 --name redis redis:7

# Verify Redis is running
redis-cli ping
# Expected: PONG
```

### 6. Start the API server

```bash
uvicorn app.main:app --reload --port 8000
```

Expected output:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

### 7. Verify everything is working

```bash
# Liveness
curl http://localhost:8000/health
# {"status": "ok"}

# Readiness — checks Redis
curl http://localhost:8000/health/ready
# {"status": "ready", "checks": {"redis": {"status": "healthy", ...}}}

# Demo — first hit (cache MISS)
curl -i http://localhost:8000/api/demo
# x-cache-status: MISS

# Demo — second hit (cache HIT)
curl -i http://localhost:8000/api/demo
# x-cache-status: HIT

# Interactive API docs (DEBUG=true required)
open http://localhost:8000/docs
```

### 8. Stop everything cleanly

```bash
# Stop uvicorn
Ctrl+C

# Stop Redis
sudo service redis-server stop

# Deactivate venv
deactivate
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe — always 200 if process is alive |
| GET | `/health/ready` | Readiness probe — checks Redis connectivity |
| GET | `/api/demo` | Demo endpoint — shows rate limit + cache headers |
| GET | `/api/demo?page=N` | Paginated demo — different cache key per page |
| GET | `/api/demo/slow` | Simulates 200ms processing time |
| POST | `/api/demo/write` | POST — never cached, always rate limited |
| GET | `/metrics` | Prometheus metrics scrape endpoint |
| GET | `/docs` | Swagger UI — only when `DEBUG=true` |
| GET | `/redoc` | ReDoc UI — only when `DEBUG=true` |

---

## Response Headers

Every API response includes:

| Header | Example Value | Meaning |
|---|---|---|
| `X-RateLimit-Limit` | `100` | Max requests allowed per window |
| `X-RateLimit-Remaining` | `87` | Requests remaining in current window |
| `X-RateLimit-Reset` | `1716823260` | Unix timestamp when window resets |
| `X-Cache-Status` | `HIT` / `MISS` / `SKIP` | Whether response was served from cache |
| `X-Request-ID` | `uuid4-string` | Unique trace ID for this request |
| `X-Frame-Options` | `DENY` | Clickjacking protection |
| `X-Content-Type-Options` | `nosniff` | MIME type sniffing protection |
| `Strict-Transport-Security` | `max-age=31536000` | HTTPS enforcement |

### Rate Limited Response (HTTP 429)

```json
{
  "error": "rate_limit_exceeded",
  "message": "Too many requests. Please try again later.",
  "retry_after": 30
}
```

With headers:
```
Retry-After: 30
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1716823290
```

---

## Configuration

All settings are controlled via `.env`. Full reference:

```env
# Application
APP_NAME=distributed-rate-limiter
APP_VERSION=1.0.0
ENVIRONMENT=development        # development | production
DEBUG=true                     # false in production

# Server
HOST=0.0.0.0
PORT=8000
WORKERS=4

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=                # required in production
REDIS_SOCKET_TIMEOUT=5.0
REDIS_SOCKET_CONNECT_TIMEOUT=5.0
REDIS_MAX_CONNECTIONS=50
REDIS_RETRY_ON_TIMEOUT=true

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_STRATEGY=token_bucket        # token_bucket | sliding_window
RATE_LIMIT_FALLBACK_ALLOW=true          # fail-open when Redis is down

# Token Bucket
TOKEN_BUCKET_CAPACITY=100
TOKEN_BUCKET_REFILL_RATE=1.67           # 1.67 tokens/sec = 100/min

# Cache
CACHE_ENABLED=true
CACHE_DEFAULT_TTL=300
CACHE_MAX_KEY_LENGTH=200

# Logging
LOG_LEVEL=INFO                          # DEBUG | INFO | WARNING | ERROR
LOG_JSON=false                          # true for production log aggregators

# Metrics
METRICS_ENABLED=true
METRICS_PATH=/metrics

# CORS
CORS_ORIGINS=*                          # restrict to your domain in production
```

---

## Running Tests

```bash
# Full suite with coverage report (recommended)
pytest

# Fast run — no coverage
pytest --no-cov -v

# Redis integration tests — MUST run in isolation
pytest tests/test_redis.py --no-cov -p no:anyio -v

# View HTML coverage report
open htmlcov/index.html          # Mac
start htmlcov/index.html         # Windows
xdg-open htmlcov/index.html      # Linux
```

### Why Redis Tests Run in Isolation

The main `conftest.py` patches `app.core.redis` functions at **session scope** for the entire test suite. If `test_redis.py` runs inside the full suite, it hits those mocked versions instead of the real functions — every assertion on real behavior fails.

Additionally, `app/core/redis.py` uses a module-level global `_redis_client` variable. Tests that modify this global contaminate subsequent tests. Running in isolation with a per-test autouse fixture that resets `_redis_client = None` before and after each test eliminates this contamination.

The `-p no:anyio` flag prevents event loop conflicts between the asyncio and anyio plugins when both are present in the same run.

### Coverage Results

```
Name                               Cover
─────────────────────────────────────────
app/core/redis.py                  100%
app/services/cache.py              100%
app/services/sliding_window.py     100%
app/services/token_bucket.py       100%
app/utils/metrics.py               100%
─────────────────────────────────────────
TOTAL                               97%
```

---

## Load Testing

```bash
locust -f locustfile.py --headless -u 100 -r 10 --run-time 60s --host http://localhost:8000
```

**Two user types are simulated:**
- `APIUser` — moderate request rate, verifies cache headers
- `BurstUser` — aggressive rate, should trigger 429s quickly

**Pass criteria:**
- Rate limited count > 0 (limiter is working)
- Cache hit rate > 30% after warmup
- Errors column = 0

---

## Observability

The `/metrics` endpoint exposes Prometheus metrics. Scrape using `monitoring/prometheus.yml`.

| Metric | Type | Labels | What it tells you |
|---|---|---|---|
| `http_requests_total` | Counter | method, path, status_code | Request volume and error rates |
| `http_request_duration_seconds` | Histogram | method, path | p50 / p95 / p99 latency |
| `rate_limit_hits_total` | Counter | strategy, result | Allow vs block decisions |
| `cache_operations_total` | Counter | operation, result | Cache hit rate and errors |
| `redis_connected` | Gauge | — | Redis health: 1=up, 0=down |
| `app_info` | Info | version, environment | App metadata |

**Alerts to configure:**
- `redis_connected == 0` → page on-call immediately
- `rate_limit_hits_total{result="blocked"}` spike → possible DDoS or misconfigured client
- `http_request_duration_seconds p99 > 500ms` → performance regression
- `cache_operations_total{result="error"}` > 0 → Redis write issues

---

## Production Hardening Checklist

Before deploying to production:

- [ ] `DEBUG=false` — hides `/docs` and `/redoc`
- [ ] `ENVIRONMENT=production`
- [ ] `CORS_ORIGINS=https://yourdomain.com` — remove wildcard
- [ ] `REDIS_PASSWORD=<strong-password>` — never leave empty
- [ ] Redis on private network — port 6379 never exposed publicly
- [ ] TLS termination via nginx or caddy in front of uvicorn
- [ ] `LOG_JSON=true` — structured logs for log aggregators
- [ ] Prometheus alerting on `redis_connected=0`
- [ ] Rate limit values tuned for your actual traffic profile

---

## Bugs Fixed During Development

Six production bugs were identified and fixed:

### 1. Infinite Loop in Cache Invalidation
**File:** `app/services/cache.py`
Redis returns an integer cursor. The original code compared it to string `"0"`. Python type mismatch meant the loop never terminated on any cache invalidation call.
**Fix:** Use integer `0` for the cursor comparison and initialization.

### 2. Rate Limit Bucket Hijacking (Security Vulnerability)
**File:** `app/middleware/rate_limit.py`
Missing `ip:` prefix on forwarded IP identifiers. An attacker could send `X-Forwarded-For: apikey:victim` and drain another user's rate limit bucket without making any real requests themselves.
**Fix:** Prefix all IP-derived identifiers with `ip:` to prevent namespace collision with API key identifiers.

### 3. Crash on Binary HTTP Responses
**File:** `app/middleware/cache.py`
`body.decode("utf-8")` raised `UnicodeDecodeError` on images, PDFs, and any non-UTF8 content, crashing the middleware for those requests.
**Fix:** Wrap in try/except, skip caching binary responses, record a `skip_binary` metric.

### 4. Concurrency Undercounting in Sliding Window
**File:** `app/services/sliding_window.py`
Two concurrent requests at the same microsecond generated identical sorted set members (timestamp only). Redis sorted sets treat a duplicate member as an update, not an addition. The second request silently overwrote the first, undercounting usage and allowing one extra request through.
**Fix:** Append a UUID suffix to every request ID — `f"{now:.6f}-{uuid.uuid4().hex[:8]}"`.

### 5. Deprecated asyncio API
**File:** `app/core/redis.py`
`asyncio.get_event_loop()` is deprecated in Python 3.10+ and raises a `DeprecationWarning`. It becomes a runtime error in Python 3.12+.
**Fix:** Replace with `asyncio.get_running_loop()`.

### 6. Prometheus Gauge Never Updated
**File:** `app/api/health.py`
The `redis_connected` gauge was defined and exported but `set_redis_status()` was never called from the health check endpoint. Prometheus dashboards showed no data for Redis health.
**Fix:** Call `set_redis_status(is_redis_healthy)` in the readiness endpoint after every Redis health check.

---

## Tech Stack

| Technology | Version | Purpose |
|---|---|---|
| FastAPI | 0.111.0 | Web framework and API routing |
| Starlette | 0.37.2 | ASGI middleware stack |
| Redis (asyncio) | 5.0.4 | Shared state: rate limits and response cache |
| Pydantic Settings | 2.2.1 | Configuration management via .env |
| Prometheus Client | 0.20.0 | Metrics instrumentation and export |
| pytest | 8.2.0 | Test framework |
| pytest-asyncio | 0.23.6 | Async test support |
| Locust | 2.28.0 | Load testing |
| Uvicorn | 0.29.0 | ASGI server |
| uvloop | 0.22.1 | High-performance event loop |

---

## Author

**Aditya Gupta**
Final Year B.Tech CS (AI), BIT Bhilai
Graduating June 2026

---

*Built to solve real distributed systems problems. Every design decision has a reason. Every bug fix has a lesson.*
