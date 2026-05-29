"""
Unit tests for RateLimiterService — strategy selection, fallback, reset.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from redis.exceptions import RedisError

from app.services.rate_limiter import RateLimiterService, RateLimitStrategy


def make_settings(strategy="token_bucket", enabled=True, fallback_allow=True):
    s = MagicMock()
    s.rate_limit_enabled = enabled
    s.rate_limit_strategy = strategy
    s.rate_limit_requests = 100
    s.rate_limit_window_seconds = 60
    s.token_bucket_capacity = 100
    s.token_bucket_refill_rate = 1.67
    s.rate_limit_fallback_allow = fallback_allow
    return s


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.script_load = AsyncMock(return_value="sha123")
    r.evalsha = AsyncMock(return_value=[1, 99, 0])
    return r


@pytest.mark.asyncio
async def test_disabled_always_allows(mock_redis):
    svc = RateLimiterService(mock_redis, make_settings(enabled=False))
    allowed, usage, retry = await svc.check_rate_limit("user1")
    assert allowed is True
    assert usage == 0


@pytest.mark.asyncio
async def test_token_bucket_allowed(mock_redis):
    mock_redis.evalsha.return_value = [1, 80, 0]
    svc = RateLimiterService(mock_redis, make_settings(strategy="token_bucket"))
    allowed, _, _ = await svc.check_rate_limit("user1")
    assert allowed is True


@pytest.mark.asyncio
async def test_token_bucket_denied(mock_redis):
    mock_redis.evalsha.return_value = [0, 0, 10]
    svc = RateLimiterService(mock_redis, make_settings(strategy="token_bucket"))
    allowed, _, retry = await svc.check_rate_limit("user1")
    assert allowed is False
    assert retry == 10


@pytest.mark.asyncio
async def test_sliding_window_allowed(mock_redis):
    mock_redis.evalsha.return_value = [1, 5, 0]
    svc = RateLimiterService(mock_redis, make_settings(strategy="sliding_window"))
    allowed, count, _ = await svc.check_rate_limit("user1")
    assert allowed is True
    assert count == 5


@pytest.mark.asyncio
async def test_sliding_window_denied(mock_redis):
    mock_redis.evalsha.return_value = [0, 100, 30]
    svc = RateLimiterService(mock_redis, make_settings(strategy="sliding_window"))
    allowed, _, retry = await svc.check_rate_limit("user1")
    assert allowed is False
    assert retry == 30


@pytest.mark.asyncio
async def test_redis_error_fail_open(mock_redis):
    mock_redis.evalsha.side_effect = RedisError("connection lost")
    svc = RateLimiterService(mock_redis, make_settings(fallback_allow=True))
    allowed, _, _ = await svc.check_rate_limit("user1")
    assert allowed is True


@pytest.mark.asyncio
async def test_redis_error_fail_closed(mock_redis):
    mock_redis.evalsha.side_effect = RedisError("connection lost")
    svc = RateLimiterService(mock_redis, make_settings(fallback_allow=False))
    allowed, _, retry = await svc.check_rate_limit("user1")
    assert allowed is False
    assert retry == 60


@pytest.mark.asyncio
async def test_reset_token_bucket(mock_redis):
    svc = RateLimiterService(mock_redis, make_settings(strategy="token_bucket"))
    await svc.reset_limit("user1")
    mock_redis.delete.assert_called_once()


@pytest.mark.asyncio
async def test_reset_sliding_window(mock_redis):
    svc = RateLimiterService(mock_redis, make_settings(strategy="sliding_window"))
    await svc.reset_limit("user1")
    mock_redis.delete.assert_called_once()
