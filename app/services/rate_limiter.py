"""
Rate Limiter Service — Strategy Pattern.
Abstracts sliding window vs token bucket behind one interface.
Handles Redis failures with configurable fail-open / fail-closed.
"""
from typing import Tuple
from enum import Enum

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.sliding_window import SlidingWindowRateLimiter
from app.services.token_bucket import TokenBucketRateLimiter

logger = get_logger(__name__)


class RateLimitStrategy(str, Enum):
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"


class RateLimiterService:
    def __init__(self, redis_client: Redis, settings: Settings) -> None:
        self._redis = redis_client
        self._settings = settings
        self._sliding_window = SlidingWindowRateLimiter(redis_client)
        self._token_bucket = TokenBucketRateLimiter(redis_client)
        self._strategy = RateLimitStrategy(settings.rate_limit_strategy)
        logger.info(
            "rate_limiter_initialized",
            extra={
                "strategy": self._strategy.value,
                "limit": settings.rate_limit_requests,
                "window_seconds": settings.rate_limit_window_seconds,
            },
        )

    async def check_rate_limit(self, identifier: str) -> Tuple[bool, int, int]:
        if not self._settings.rate_limit_enabled:
            return True, 0, 0
        try:
            if self._strategy == RateLimitStrategy.SLIDING_WINDOW:
                return await self._sliding_window.check_rate_limit(
                    identifier=identifier,
                    limit=self._settings.rate_limit_requests,
                    window_seconds=self._settings.rate_limit_window_seconds,
                )
            elif self._strategy == RateLimitStrategy.TOKEN_BUCKET:
                return await self._token_bucket.check_rate_limit(
                    identifier=identifier,
                    capacity=self._settings.token_bucket_capacity,
                    refill_rate=self._settings.token_bucket_refill_rate,
                )
            else:
                logger.error("unknown_strategy", extra={"strategy": self._strategy})
                return self._fallback_decision()
        except RedisError as e:
            logger.error(
                "rate_limit_redis_error",
                extra={
                    "identifier": identifier,
                    "error": str(e),
                    "fallback_allow": self._settings.rate_limit_fallback_allow,
                },
            )
            return self._fallback_decision()

    def _fallback_decision(self) -> Tuple[bool, int, int]:
        allowed = self._settings.rate_limit_fallback_allow
        retry_after = 0 if allowed else 60
        return allowed, 0, retry_after

    async def reset_limit(self, identifier: str) -> None:
        try:
            if self._strategy == RateLimitStrategy.SLIDING_WINDOW:
                await self._sliding_window.reset_limit(identifier)
            elif self._strategy == RateLimitStrategy.TOKEN_BUCKET:
                await self._token_bucket.reset_bucket(identifier)
        except RedisError as e:
            logger.error("reset_limit_failed", extra={"identifier": identifier, "error": str(e)})
            raise
