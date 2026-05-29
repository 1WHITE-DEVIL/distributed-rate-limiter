"""
Unit tests for CacheService — get/set/delete/invalidate + error paths.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from redis.exceptions import RedisError

from app.services.cache import CacheService


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    r.scan = AsyncMock(return_value=("0", []))
    return r


@pytest.fixture
def settings():
    s = MagicMock()
    s.cache_enabled = True
    s.cache_default_ttl = 300
    s.cache_max_key_length = 200
    return s


@pytest.fixture
def svc(mock_redis, settings):
    return CacheService(redis_client=mock_redis, settings=settings)


# ── GET ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_disabled_returns_none(svc, settings):
    settings.cache_enabled = False
    assert await svc.get("/test") is None


@pytest.mark.asyncio
async def test_get_cache_hit_bytes(svc, mock_redis):
    payload = json.dumps({"content": "ok", "status_code": 200}).encode()
    mock_redis.get.return_value = payload
    result = await svc.get("/test")
    assert result["status_code"] == 200


@pytest.mark.asyncio
async def test_get_cache_hit_string(svc, mock_redis):
    mock_redis.get.return_value = json.dumps({"content": "ok", "status_code": 201})
    result = await svc.get("/test")
    assert result["status_code"] == 201


@pytest.mark.asyncio
async def test_get_cache_miss_returns_none(svc, mock_redis):
    mock_redis.get.return_value = None
    assert await svc.get("/test") is None


@pytest.mark.asyncio
async def test_get_redis_error_returns_none(svc, mock_redis):
    mock_redis.get.side_effect = RedisError("connection lost")
    assert await svc.get("/test") is None


@pytest.mark.asyncio
async def test_get_bad_json_returns_none(svc, mock_redis):
    mock_redis.get.return_value = b"not { valid json"
    assert await svc.get("/test") is None


@pytest.mark.asyncio
async def test_get_sorts_query_params(svc, mock_redis):
    mock_redis.get.return_value = None
    await svc.get("/test", query_params={"z": "last", "a": "first"})
    key = mock_redis.get.call_args[0][0]
    assert key.index("a=first") < key.index("z=last")


@pytest.mark.asyncio
async def test_get_user_id_appended_to_key(svc, mock_redis):
    mock_redis.get.return_value = None
    await svc.get("/test", user_id="u99")
    assert "user:u99" in mock_redis.get.call_args[0][0]


# ── SET ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_disabled_returns_false(svc, settings, mock_redis):
    settings.cache_enabled = False
    assert await svc.set("/test", {}) is False
    mock_redis.setex.assert_not_called()


@pytest.mark.asyncio
async def test_set_success_uses_default_ttl(svc, mock_redis, settings):
    assert await svc.set("/test", {"content": "x", "status_code": 200}) is True
    assert mock_redis.setex.call_args[0][1] == settings.cache_default_ttl


@pytest.mark.asyncio
async def test_set_custom_ttl(svc, mock_redis):
    await svc.set("/test", {"content": "x"}, ttl=42)
    assert mock_redis.setex.call_args[0][1] == 42


@pytest.mark.asyncio
async def test_set_redis_error_returns_false(svc, mock_redis):
    mock_redis.setex.side_effect = RedisError("write failed")
    assert await svc.set("/test", {"content": "x"}) is False


@pytest.mark.asyncio
async def test_set_type_error_returns_false(svc, mock_redis):
    mock_redis.setex.side_effect = TypeError("not serializable")
    assert await svc.set("/test", {"content": object()}) is False


# ── DELETE ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_success(svc, mock_redis):
    mock_redis.delete.return_value = 1
    assert await svc.delete("/test") is True


@pytest.mark.asyncio
async def test_delete_key_not_found(svc, mock_redis):
    mock_redis.delete.return_value = 0
    assert await svc.delete("/test") is False


@pytest.mark.asyncio
async def test_delete_redis_error(svc, mock_redis):
    mock_redis.delete.side_effect = RedisError("fail")
    assert await svc.delete("/test") is False


# ── KEY HASHING ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_long_key_is_hashed(svc, mock_redis):
    mock_redis.get.return_value = None
    long_path = "/api/" + "x" * 300
    await svc.get(long_path)
    key = mock_redis.get.call_args[0][0]
    assert "hash:" in key


# ── INVALIDATE PATTERN ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalidate_deletes_matching_keys(svc, mock_redis):
    mock_redis.scan.return_value = (0, [b"k1", b"k2"])
    mock_redis.delete.return_value = 2
    count = await svc.invalidate_pattern("/api/users/*")
    assert count == 2


@pytest.mark.asyncio
async def test_invalidate_multi_page_cursor(svc, mock_redis):
    mock_redis.scan.side_effect = [(99, [b"k1"]), (0, [b"k2"])]
    mock_redis.delete.return_value = 1
    count = await svc.invalidate_pattern("/api/*")
    assert count == 2


@pytest.mark.asyncio
async def test_invalidate_redis_error_returns_zero(svc, mock_redis):
    mock_redis.scan.side_effect = RedisError("scan failed")
    assert await svc.invalidate_pattern("/api/*") == 0
