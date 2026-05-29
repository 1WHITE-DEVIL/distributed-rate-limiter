"""
Unit tests for SlidingWindowRateLimiter.
"""
import pytest
from unittest.mock import AsyncMock
from redis.exceptions import RedisError

from app.services.sliding_window import SlidingWindowRateLimiter


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.script_load = AsyncMock(return_value="sha_sw_456")
    r.evalsha = AsyncMock(return_value=[1, 5, 0])
    r.delete = AsyncMock(return_value=1)
    r.zcard = AsyncMock(return_value=3)
    return r


@pytest.fixture
def limiter(mock_redis):
    return SlidingWindowRateLimiter(redis_client=mock_redis)


@pytest.mark.asyncio
async def test_script_loaded_only_once(limiter, mock_redis):
    await limiter.check_rate_limit("u1", 100, 60)
    await limiter.check_rate_limit("u1", 100, 60)
    assert mock_redis.script_load.call_count == 1


@pytest.mark.asyncio
async def test_allowed_request(limiter, mock_redis):
    mock_redis.evalsha.return_value = [1, 10, 0]
    allowed, count, retry = await limiter.check_rate_limit("u1", 100, 60)
    assert allowed is True
    assert count == 10


@pytest.mark.asyncio
async def test_denied_request(limiter, mock_redis):
    mock_redis.evalsha.return_value = [0, 100, 45]
    allowed, count, retry = await limiter.check_rate_limit("u1", 100, 60)
    assert allowed is False
    assert retry == 45


@pytest.mark.asyncio
async def test_redis_error_raises(limiter, mock_redis):
    mock_redis.evalsha.side_effect = RedisError("fail")
    with pytest.raises(RedisError):
        await limiter.check_rate_limit("u1", 100, 60)


@pytest.mark.asyncio
async def test_key_contains_prefix_and_identifier(limiter, mock_redis):
    mock_redis.evalsha.return_value = [1, 1, 0]
    await limiter.check_rate_limit("user_abc", 100, 60)
    key = mock_redis.evalsha.call_args[0][2]
    assert "ratelimit:sliding" in key
    assert "user_abc" in key


@pytest.mark.asyncio
async def test_reset_deletes_key(limiter, mock_redis):
    await limiter.reset_limit("u1")
    mock_redis.delete.assert_called_once()


@pytest.mark.asyncio
async def test_reset_redis_error_raises(limiter, mock_redis):
    mock_redis.delete.side_effect = RedisError("fail")
    with pytest.raises(RedisError):
        await limiter.reset_limit("u1")


@pytest.mark.asyncio
async def test_get_current_usage(limiter, mock_redis):
    mock_redis.zcard.return_value = 7
    assert await limiter.get_current_usage("u1") == 7


@pytest.mark.asyncio
async def test_get_current_usage_redis_error_returns_zero(limiter, mock_redis):
    mock_redis.zcard.side_effect = RedisError("fail")
    assert await limiter.get_current_usage("u1") == 0
