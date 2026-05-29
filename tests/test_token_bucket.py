"""
Unit tests for TokenBucketRateLimiter.
"""
import pytest
from unittest.mock import AsyncMock
from redis.exceptions import RedisError

from app.services.token_bucket import TokenBucketRateLimiter


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.script_load = AsyncMock(return_value="sha_tb_123")
    r.evalsha = AsyncMock(return_value=[1, 99, 0])
    r.delete = AsyncMock(return_value=1)
    r.hget = AsyncMock(return_value=None)
    return r


@pytest.fixture
def limiter(mock_redis):
    return TokenBucketRateLimiter(redis_client=mock_redis)


@pytest.mark.asyncio
async def test_script_loaded_only_once(limiter, mock_redis):
    await limiter.check_rate_limit("u1", 100, 1.67)
    await limiter.check_rate_limit("u1", 100, 1.67)
    assert mock_redis.script_load.call_count == 1


@pytest.mark.asyncio
async def test_allowed_request(limiter, mock_redis):
    mock_redis.evalsha.return_value = [1, 80, 0]
    allowed, tokens, retry = await limiter.check_rate_limit("u1", 100, 1.67)
    assert allowed is True
    assert tokens == 80
    assert retry == 0


@pytest.mark.asyncio
async def test_denied_request(limiter, mock_redis):
    mock_redis.evalsha.return_value = [0, 0, 10]
    allowed, tokens, retry = await limiter.check_rate_limit("u1", 100, 1.67)
    assert allowed is False
    assert retry == 10


@pytest.mark.asyncio
async def test_custom_tokens_requested(limiter, mock_redis):
    mock_redis.evalsha.return_value = [1, 95, 0]
    await limiter.check_rate_limit("u1", 100, 1.67, tokens_requested=5)
    call_args = mock_redis.evalsha.call_args[0]
    assert call_args[-1] == 5


@pytest.mark.asyncio
async def test_redis_error_raises(limiter, mock_redis):
    mock_redis.evalsha.side_effect = RedisError("down")
    with pytest.raises(RedisError):
        await limiter.check_rate_limit("u1", 100, 1.67)


@pytest.mark.asyncio
async def test_key_contains_prefix_and_identifier(limiter, mock_redis):
    mock_redis.evalsha.return_value = [1, 99, 0]
    await limiter.check_rate_limit("user_xyz", 100, 1.67)
    key = mock_redis.evalsha.call_args[0][2]
    assert "ratelimit:tokenbucket" in key
    assert "user_xyz" in key


@pytest.mark.asyncio
async def test_reset_calls_delete(limiter, mock_redis):
    await limiter.reset_bucket("u1")
    mock_redis.delete.assert_called_once()


@pytest.mark.asyncio
async def test_reset_redis_error_raises(limiter, mock_redis):
    mock_redis.delete.side_effect = RedisError("fail")
    with pytest.raises(RedisError):
        await limiter.reset_bucket("u1")


@pytest.mark.asyncio
async def test_get_remaining_tokens_value(limiter, mock_redis):
    mock_redis.hget.return_value = b"63.9"
    assert await limiter.get_remaining_tokens("u1", 100) == 63


@pytest.mark.asyncio
async def test_get_remaining_tokens_empty_returns_capacity(limiter, mock_redis):
    mock_redis.hget.return_value = None
    assert await limiter.get_remaining_tokens("u1", 100) == 100


@pytest.mark.asyncio
async def test_get_remaining_tokens_redis_error_returns_capacity(limiter, mock_redis):
    mock_redis.hget.side_effect = RedisError("fail")
    assert await limiter.get_remaining_tokens("u1", 100) == 100
