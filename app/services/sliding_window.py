"""
Sliding Window Rate Limiter.
Uses Redis Sorted Sets + Lua for atomic, race-condition-free counting.
O(log N) per request. True sliding window — no fixed bucket spikes.
"""
from typing import Optional, Tuple
import time
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.logging import get_logger

logger = get_logger(__name__)

SLIDING_WINDOW_LUA_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local request_id = ARGV[4]

local window_start = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

local current_count = redis.call('ZCARD', key)

if current_count >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local oldest_timestamp = oldest[2] and tonumber(oldest[2]) or now
    local retry_after = math.ceil(oldest_timestamp + window - now)
    return {0, current_count, retry_after}
end

redis.call('ZADD', key, now, request_id)
redis.call('EXPIRE', key, window + 10)
return {1, current_count + 1, 0}
"""


class SlidingWindowRateLimiter:
    def __init__(self, redis_client: Redis, key_prefix: str = "ratelimit:sliding") -> None:
        self._redis = redis_client
        self._key_prefix = key_prefix
        self._script_sha: Optional[str] = None

    async def _ensure_script_loaded(self) -> str:
        if self._script_sha is None:
            self._script_sha = await self._redis.script_load(SLIDING_WINDOW_LUA_SCRIPT)
        return self._script_sha

    def _make_key(self, identifier: str) -> str:
        return f"{self._key_prefix}:{identifier}"

    async def check_rate_limit(
        self, identifier: str, limit: int, window_seconds: int
    ) -> Tuple[bool, int, int]:
        try:
            now = time.time()
            request_id = f"{now:.6f}-{uuid.uuid4().hex[:8]}"
            script_sha = await self._ensure_script_loaded()
            result = await self._redis.evalsha(
                script_sha, 1,
                self._make_key(identifier),
                now, window_seconds, limit, request_id,
            )
            allowed = bool(result[0])
            current_count = int(result[1])
            retry_after = int(result[2])
            if not allowed:
                logger.info(
                    "rate_limit_exceeded",
                    extra={
                        "identifier": identifier,
                        "current_count": current_count,
                        "limit": limit,
                        "retry_after": retry_after,
                    },
                )
            return allowed, current_count, retry_after
        except RedisError as e:
            logger.error("rate_limit_check_failed", extra={"identifier": identifier, "error": str(e)})
            raise

    async def reset_limit(self, identifier: str) -> None:
        try:
            await self._redis.delete(self._make_key(identifier))
            logger.info("rate_limit_reset", extra={"identifier": identifier})
        except RedisError as e:
            logger.error("rate_limit_reset_failed", extra={"identifier": identifier, "error": str(e)})
            raise

    async def get_current_usage(self, identifier: str) -> int:
        try:
            return await self._redis.zcard(self._make_key(identifier))
        except RedisError:
            return 0
