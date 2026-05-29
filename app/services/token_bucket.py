"""
Token Bucket Rate Limiter.
Allows burst traffic up to capacity, refills at constant rate.
O(1) per request. Ideal for APIs with occasional burst patterns.
"""
from typing import Optional, Tuple
import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.logging import get_logger

logger = get_logger(__name__)

TOKEN_BUCKET_LUA_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local tokens_requested = tonumber(ARGV[4])

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1]) or capacity
local last_refill = tonumber(bucket[2]) or now

local time_elapsed = now - last_refill
local tokens_to_add = time_elapsed * refill_rate
tokens = math.min(capacity, tokens + tokens_to_add)

if tokens >= tokens_requested then
    tokens = tokens - tokens_requested
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 3600)
    return {1, math.floor(tokens), 0}
else
    local tokens_needed = tokens_requested - tokens
    local retry_after = math.ceil(tokens_needed / refill_rate)
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 3600)
    return {0, math.floor(tokens), retry_after}
end
"""


class TokenBucketRateLimiter:
    def __init__(self, redis_client: Redis, key_prefix: str = "ratelimit:tokenbucket") -> None:
        self._redis = redis_client
        self._key_prefix = key_prefix
        self._script_sha: Optional[str] = None

    async def _ensure_script_loaded(self) -> str:
        if self._script_sha is None:
            self._script_sha = await self._redis.script_load(TOKEN_BUCKET_LUA_SCRIPT)
        return self._script_sha

    def _make_key(self, identifier: str) -> str:
        return f"{self._key_prefix}:{identifier}"

    async def check_rate_limit(
        self,
        identifier: str,
        capacity: int,
        refill_rate: float,
        tokens_requested: int = 1,
    ) -> Tuple[bool, int, int]:
        try:
            now = time.time()
            script_sha = await self._ensure_script_loaded()
            result = await self._redis.evalsha(
                script_sha, 1,
                self._make_key(identifier),
                capacity, refill_rate, now, tokens_requested,
            )
            allowed = bool(result[0])
            remaining_tokens = int(result[1])
            retry_after = int(result[2])
            if not allowed:
                logger.info(
                    "token_bucket_limit_exceeded",
                    extra={
                        "identifier": identifier,
                        "remaining_tokens": remaining_tokens,
                        "retry_after": retry_after,
                    },
                )
            return allowed, remaining_tokens, retry_after
        except RedisError as e:
            logger.error("token_bucket_check_failed", extra={"identifier": identifier, "error": str(e)})
            raise

    async def reset_bucket(self, identifier: str) -> None:
        try:
            await self._redis.delete(self._make_key(identifier))
            logger.info("token_bucket_reset", extra={"identifier": identifier})
        except RedisError as e:
            logger.error("token_bucket_reset_failed", extra={"identifier": identifier, "error": str(e)})
            raise

    async def get_remaining_tokens(self, identifier: str, capacity: int) -> int:
        try:
            result = await self._redis.hget(self._make_key(identifier), "tokens")
            return int(float(result)) if result else capacity
        except RedisError:
            return capacity
