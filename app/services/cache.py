"""
Redis Response Cache Service.
Caches GET responses with configurable TTL, key hashing for long URLs,
and pattern-based invalidation using SCAN (non-blocking).
"""
import hashlib
import json
from typing import Optional, Dict, Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class CacheService:
    def __init__(
        self,
        redis_client: Redis,
        settings: Settings,
        key_prefix: str = "cache:response",
    ) -> None:
        self._redis = redis_client
        self._settings = settings
        self._key_prefix = key_prefix

    def _make_cache_key(
        self,
        path: str,
        query_params: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> str:
        components = [path]
        if query_params:
            sorted_params = sorted(query_params.items())
            components.append("&".join(f"{k}={v}" for k, v in sorted_params))
        if user_id:
            components.append(f"user:{user_id}")
        key = ":".join(components)
        if len(key) > self._settings.cache_max_key_length:
            key_hash = hashlib.sha256(key.encode()).hexdigest()
            key = f"hash:{key_hash}"
        return f"{self._key_prefix}:{key}"

    async def get(
        self,
        path: str,
        query_params: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self._settings.cache_enabled:
            return None
        try:
            cache_key = self._make_cache_key(path, query_params, user_id)
            cached_data = await self._redis.get(cache_key)
            if cached_data:
                if isinstance(cached_data, bytes):
                    cached_data = cached_data.decode("utf-8")
                return json.loads(cached_data)
            return None
        except (RedisError, json.JSONDecodeError) as e:
            logger.warning("cache_get_failed", extra={"path": path, "error": str(e)})
            return None

    async def set(
        self,
        path: str,
        response_data: Dict[str, Any],
        ttl: Optional[int] = None,
        query_params: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        if not self._settings.cache_enabled:
            return False
        try:
            cache_key = self._make_cache_key(path, query_params, user_id)
            ttl = ttl or self._settings.cache_default_ttl
            await self._redis.setex(cache_key, ttl, json.dumps(response_data))
            return True
        except (RedisError, TypeError) as e:
            logger.warning("cache_set_failed", extra={"path": path, "error": str(e)})
            return False

    async def delete(
        self,
        path: str,
        query_params: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        try:
            cache_key = self._make_cache_key(path, query_params, user_id)
            deleted = await self._redis.delete(cache_key)
            return bool(deleted)
        except RedisError as e:
            logger.warning("cache_delete_failed", extra={"path": path, "error": str(e)})
            return False

    async def invalidate_pattern(self, pattern: str) -> int:
        try:
            deleted_count = 0
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(
                    cursor=cursor,
                    match=f"{self._key_prefix}:{pattern}",
                    count=100,
                )
                if keys:
                    deleted_count += await self._redis.delete(*keys)
                if cursor == 0:
                    break
            logger.info("cache_pattern_invalidated", extra={"pattern": pattern, "deleted_count": deleted_count})
            return deleted_count
        except RedisError as e:
            logger.error("cache_invalidate_failed", extra={"pattern": pattern, "error": str(e)})
            return 0
