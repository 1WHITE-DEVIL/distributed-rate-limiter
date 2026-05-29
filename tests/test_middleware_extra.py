import pytest


def test_cache_bypass_header(client, api_headers):
    headers = {**api_headers, "X-Cache-Bypass": "true"}
    r = client.get("/api/demo", headers=headers)
    assert r.status_code == 200
    assert r.headers.get("x-cache-status") == "SKIP"


def test_cache_skips_health(client):
    r = client.get("/health")
    assert r.headers.get("x-cache-status") == "SKIP"


def test_rate_limit_bypass_header_present(client, api_headers):
    r = client.get("/api/demo", headers=api_headers)
    assert "x-ratelimit-limit" in r.headers
    assert "x-ratelimit-remaining" in r.headers
    assert "x-ratelimit-reset" in r.headers


def test_different_api_keys_get_own_limits(client):
    r1 = client.get("/api/demo", headers={"X-API-Key": "user-aaa"})
    r2 = client.get("/api/demo", headers={"X-API-Key": "user-bbb"})
    assert r1.status_code in (200, 429)
    assert r2.status_code in (200, 429)


def test_forwarded_for_identifier(client):
    r = client.get("/api/demo", headers={"X-Forwarded-For": "10.0.0.1"})
    assert r.status_code in (200, 429)


def test_demo_slow_endpoint(client, api_headers):
    r = client.get("/api/demo/slow", headers=api_headers)
    assert r.status_code == 200


def test_rate_limiter_unknown_strategy(client):
    # Unknown strategy falls back gracefully
    from app.services.rate_limiter import RateLimiterService, RateLimitStrategy
    from unittest.mock import MagicMock, AsyncMock
    settings = MagicMock()
    settings.rate_limit_enabled = True
    settings.rate_limit_strategy = "token_bucket"
    settings.rate_limit_fallback_allow = True
    settings.token_bucket_capacity = 100
    settings.token_bucket_refill_rate = 1.67
    redis = AsyncMock()
    redis.script_load = AsyncMock(return_value="sha")
    redis.evalsha = AsyncMock(return_value=[1, 99, 0])
    svc = RateLimiterService(redis, settings)
    svc._strategy = "bad_strategy"

    import asyncio
    allowed, _, _ = asyncio.get_event_loop().run_until_complete(
        svc.check_rate_limit("user1")
    )
    assert allowed is True  # fallback_allow=True
def test_rate_limit_fallback_on_redis_error(client, api_headers):
    from unittest.mock import AsyncMock, patch
    with patch("app.middleware.rate_limit.RateLimitMiddleware._get_rate_limiter") as mock_rl:
        mock_svc = AsyncMock()
        mock_svc.check_rate_limit = AsyncMock(side_effect=Exception("redis down"))
        mock_rl.return_value = mock_svc
        r = client.get("/api/demo", headers=api_headers)
        # Fail-open — must still return 200
        assert r.status_code == 200
        assert r.headers.get("x-ratelimit-error") == "bypass"


def test_cache_write_error_still_returns_response(client, api_headers):
    from unittest.mock import AsyncMock, patch
    with patch("app.middleware.cache.CacheMiddleware._get_cache_service") as mock_cs:
        svc = AsyncMock()
        svc.get = AsyncMock(return_value=None)
        svc.set = AsyncMock(side_effect=Exception("redis write fail"))
        mock_cs.return_value = svc
        r = client.get("/api/demo", headers=api_headers)
        assert r.status_code == 200


def test_cache_hit_serves_cached(client, api_headers):
    from unittest.mock import AsyncMock, patch
    with patch("app.middleware.cache.CacheMiddleware._get_cache_service") as mock_cs:
        svc = AsyncMock()
        svc.get = AsyncMock(return_value={
            "content": '{"message":"cached"}',
            "status_code": 200,
            "headers": {},
            "media_type": "application/json",
        })
        mock_cs.return_value = svc
        r = client.get("/api/demo", headers=api_headers)
        assert r.status_code == 200
        assert r.headers.get("x-cache-status") == "HIT"