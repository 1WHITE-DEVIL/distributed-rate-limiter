"""
Shared test fixtures.
Boots the full FastAPI app with Redis mocked out — no real Redis needed.
"""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

# Set test environment before any app imports
os.environ.update({
    "ENVIRONMENT": "test",
    "DEBUG": "true",
    "RATE_LIMIT_ENABLED": "true",
    "CACHE_ENABLED": "true",
    "RATE_LIMIT_STRATEGY": "token_bucket",
    "RATE_LIMIT_FALLBACK_ALLOW": "true",
    "LOG_JSON": "false",
    "LOG_LEVEL": "WARNING",
})


def make_mock_redis():
    """Build a fully functional AsyncMock Redis client."""
    mock = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.setex = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=1)
    mock.scan = AsyncMock(return_value=("0", []))
    mock.zcard = AsyncMock(return_value=0)
    mock.zrange = AsyncMock(return_value=[])
    mock.hget = AsyncMock(return_value=None)
    mock.info = AsyncMock(return_value={
        "redis_version": "7.0.0",
        "used_memory_human": "1.00M",
        "connected_clients": 1,
    })
    # Lua script support
    mock.script_load = AsyncMock(return_value="mock_sha_abc123")
    mock.evalsha = AsyncMock(return_value=[1, 99, 0])  # allowed by default
    return mock


@pytest.fixture(scope="session")
def mock_redis():
    return make_mock_redis()


@pytest.fixture(scope="session")
def app(mock_redis):
    with (
        patch("app.core.redis.init_redis", new_callable=AsyncMock),
        patch("app.core.redis.close_redis", new_callable=AsyncMock),
        patch("app.core.redis.get_redis_client", return_value=mock_redis),
        patch("app.core.redis.redis_health_check", new_callable=AsyncMock,
              return_value={"status": "healthy", "latency_ms": 0.5,
                            "redis_version": "7.0.0", "used_memory_human": "1M"}),
    ):
        from app.main import create_application
        application = create_application()
        yield application


@pytest.fixture(scope="session")
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-user-001"}
