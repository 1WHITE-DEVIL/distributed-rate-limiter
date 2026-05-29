"""
Redis integration tests — requires real Redis on localhost:6379.

MUST run in isolation — conftest patches interfere with full suite:
    pytest tests/test_redis.py --no-cov -p no:anyio -v

Strategy: import the real function objects directly from the source module,
bypassing conftest's session-scoped patches on app.core.redis.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from redis.exceptions import RedisError


# ── Import real implementations directly — bypasses conftest patches ──────────
from app.core.redis import (
    _build_client,
    init_redis,
    close_redis,
    get_redis_client,
    redis_health_check,
)
import app.core.redis as redis_module


@pytest.fixture(autouse=True)
async def reset_global_client():
    """Reset _redis_client global before and after every test."""
    redis_module._redis_client = None
    yield
    if redis_module._redis_client is not None:
        try:
            await redis_module._redis_client.aclose()
        except Exception:
            pass
    redis_module._redis_client = None


# ── _build_client ─────────────────────────────────────────────────────────────

def test_build_client_returns_redis_instance():
    import redis.asyncio as aioredis
    client = _build_client()
    assert isinstance(client, aioredis.Redis)


def test_build_client_uses_settings():
    with patch("app.core.redis.get_settings") as mock_settings:
        s = MagicMock()
        s.redis_host = "127.0.0.1"
        s.redis_port = 6379
        s.redis_db = 0
        s.redis_password = None
        s.redis_socket_timeout = 5.0
        s.redis_socket_connect_timeout = 5.0
        s.redis_max_connections = 50
        s.redis_retry_on_timeout = True
        mock_settings.return_value = s
        client = _build_client()
        assert client is not None


# ── init_redis ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_init_redis_success():
    """Happy path — ping succeeds on first attempt."""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)

    with patch("app.core.redis._build_client", return_value=mock_client):
        await init_redis()

    assert redis_module._redis_client is mock_client
    mock_client.ping.assert_called_once()


@pytest.mark.asyncio
async def test_init_redis_succeeds_on_second_attempt():
    """Fails first ping, succeeds on second — retry logic works."""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(
        side_effect=[RedisError("timeout"), True]
    )

    with patch("app.core.redis._build_client", return_value=mock_client), \
         patch("app.core.redis.asyncio.sleep", new_callable=AsyncMock):
        await init_redis()

    assert redis_module._redis_client is mock_client
    assert mock_client.ping.call_count == 2


@pytest.mark.asyncio
async def test_init_redis_all_attempts_fail_raises():
    """All 3 pings fail — must raise RuntimeError."""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(side_effect=RedisError("connection refused"))

    with patch("app.core.redis._build_client", return_value=mock_client), \
         patch("app.core.redis.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(RuntimeError, match="Redis unavailable after 3 connection attempts"):
            await init_redis()

    assert mock_client.ping.call_count == 3


# ── close_redis ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_redis_clears_client():
    """close_redis() acloses and sets global to None."""
    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()
    redis_module._redis_client = mock_client

    await close_redis()

    mock_client.aclose.assert_called_once()
    assert redis_module._redis_client is None


@pytest.mark.asyncio
async def test_close_redis_safe_when_none():
    """close_redis() does not crash when already None."""
    redis_module._redis_client = None
    await close_redis()  # must not raise


# ── get_redis_client ──────────────────────────────────────────────────────────

def test_get_redis_client_raises_before_init():
    """Must raise RuntimeError if init_redis() was never called."""
    redis_module._redis_client = None
    with pytest.raises(RuntimeError, match="Redis not initialized"):
        get_redis_client()


def test_get_redis_client_returns_client_after_init():
    """Returns the correct client after it has been set."""
    mock_client = AsyncMock()
    redis_module._redis_client = mock_client
    assert get_redis_client() is mock_client


# ── redis_health_check ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_healthy():
    """Returns healthy dict with version and latency."""
    mock_client = AsyncMock()
    mock_client.info = AsyncMock(return_value={
        "redis_version": "7.0.0",
        "used_memory_human": "1.00M",
    })
    mock_client.ping = AsyncMock(return_value=True)
    redis_module._redis_client = mock_client

    result = await redis_health_check()

    assert result["status"] == "healthy"
    assert result["redis_version"] == "7.0.0"
    assert result["used_memory_human"] == "1.00M"
    assert "latency_ms" in result
    assert isinstance(result["latency_ms"], float)


@pytest.mark.asyncio
async def test_health_check_returns_unknown_for_missing_fields():
    """Handles Redis info response missing expected fields."""
    mock_client = AsyncMock()
    mock_client.info = AsyncMock(return_value={})
    mock_client.ping = AsyncMock(return_value=True)

    with patch("app.core.redis.get_redis_client", return_value=mock_client):
        result = await redis_health_check()

    assert result["status"] == "healthy"
    assert result["redis_version"] == "unknown"
    assert result["used_memory_human"] == "unknown"


@pytest.mark.asyncio
async def test_health_check_unhealthy_when_redis_down():
    """Returns unhealthy dict when Redis raises on info."""
    mock_client = AsyncMock()
    mock_client.info = AsyncMock(side_effect=RedisError("connection lost"))

    with patch("app.core.redis.get_redis_client", return_value=mock_client):
        result = await redis_health_check()

    assert result["status"] == "unhealthy"
    assert "error" in result
    assert "connection lost" in result["error"]


@pytest.mark.asyncio
async def test_health_check_unhealthy_when_not_initialized():
    """Returns unhealthy when get_redis_client raises RuntimeError."""
    with patch("app.core.redis.get_redis_client", side_effect=RuntimeError("Redis not initialized")):
        result = await redis_health_check()

    assert result["status"] == "unhealthy"
    assert "error" in result


# ── Real Redis integration (requires localhost:6379) ──────────────────────────

@pytest.mark.asyncio
async def test_real_redis_init_and_health():
    """Full integration — real Redis connect + health check."""
    try:
        await init_redis()
        result = await redis_health_check()
        assert result["status"] == "healthy"
        assert "redis_version" in result
        assert result["latency_ms"] >= 0
    except RuntimeError:
        pytest.skip("Redis not available on localhost:6379")
    finally:
        await close_redis()


@pytest.mark.asyncio
async def test_real_redis_close_and_get_raises():
    """After closing, get_redis_client() must raise."""
    try:
        await init_redis()
        await close_redis()
        with pytest.raises(RuntimeError, match="Redis not initialized"):
            get_redis_client()
    except RuntimeError as e:
        if "Redis unavailable" in str(e):
            pytest.skip("Redis not available on localhost:6379")
        raise