"""
Integration tests — full request/response cycle through all middleware.
"""
import pytest


def test_liveness(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readiness(client):
    r = client.get("/health/ready")
    assert r.status_code in (200, 503)
    assert "status" in r.json()


def test_demo_endpoint(client, api_headers):
    r = client.get("/api/demo", headers=api_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["message"] == "OK"
    assert "timestamp" in data


def test_demo_with_page_param(client, api_headers):
    r = client.get("/api/demo?page=3", headers=api_headers)
    assert r.status_code == 200
    assert r.json()["page"] == 3


def test_demo_post_not_cached(client, api_headers):
    r = client.post("/api/demo/write", headers=api_headers)
    assert r.status_code == 200
    assert r.json()["message"] == "write accepted"


def test_metrics_endpoint(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "http_requests_total" in r.text or "# HELP" in r.text


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert "max-age" in r.headers.get("strict-transport-security", "")


def test_request_id_header_present(client):
    r = client.get("/health")
    assert "x-request-id" in r.headers


def test_request_id_propagated(client):
    r = client.get("/health", headers={"X-Request-ID": "my-trace-123"})
    assert r.headers.get("x-request-id") == "my-trace-123"


def test_cache_status_header_on_get(client, api_headers):
    r = client.get("/api/demo", headers=api_headers)
    assert r.headers.get("x-cache-status") in ("HIT", "MISS", "SKIP", "ERROR")


def test_cache_skipped_on_post(client, api_headers):
    r = client.post("/api/demo/write", headers=api_headers)
    # POST should always be SKIP
    assert r.headers.get("x-cache-status") in ("SKIP", None)


def test_health_not_rate_limited(client):
    # Health endpoint must be in SKIP_PATHS — never rate limited
    for _ in range(20):
        r = client.get("/health")
        assert r.status_code == 200


def test_rate_limit_headers_on_allowed(client, api_headers):
    r = client.get("/api/demo", headers=api_headers)
    assert "x-ratelimit-limit" in r.headers
    assert "x-ratelimit-remaining" in r.headers
    assert "x-ratelimit-reset" in r.headers


def test_docs_available_in_debug(client):
    # DEBUG=true in test env so docs should be available
    r = client.get("/docs")
    assert r.status_code == 200
def test_readiness_checks_redis(client):
    r = client.get("/health/ready")
    data = r.json()
    assert "checks" in data
    assert "redis" in data["checks"]
    assert data["checks"]["redis"]["status"] == "healthy"

def test_readiness_returns_version(client):
    r = client.get("/health/ready")
    assert "version" in r.json()
def test_health_ready_degraded_when_redis_unhealthy(client):
    from unittest.mock import AsyncMock, patch
    with patch("app.api.health.redis_health_check", new_callable=AsyncMock,
               return_value={"status": "unhealthy", "error": "connection refused"}):
        r = client.get("/health/ready")
        assert r.status_code == 503
        assert r.json()["status"] == "degraded"