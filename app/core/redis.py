from __future__ import annotations
import asyncio
from typing import Optional

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import RedisError, ConnectionError, TimeoutError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis_client: Optional[Redis] = None


def _build_client() -> Redis:
    settings = get_settings()
    retry = Retry(
        ExponentialBackoff(cap=10, base=0.5),
        retries=3,
        supported_errors=(ConnectionError, TimeoutError),
    )
    return aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password or None,
        socket_timeout=settings.redis_socket_timeout,
        socket_connect_timeout=settings.redis_socket_connect_timeout,
        max_connections=settings.redis_max_connections,
        retry_on_timeout=settings.redis_retry_on_timeout,
        retry=retry,
        decode_responses=False,
        health_check_interval=30,
    )


async def init_redis() -> None:
    global _redis_client
    _redis_client = _build_client()
    for attempt in range(3):
        try:
            await _redis_client.ping()
            logger.info("redis_connected", extra={"attempt": attempt + 1})
            return
        except RedisError as e:
            logger.warning("redis_connect_retry", extra={"attempt": attempt + 1, "error": str(e)})
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError("Redis unavailable after 3 connection attempts — aborting startup")


async def close_redis() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("redis_connection_closed")


def get_redis_client() -> Redis:
    if _redis_client is None:
        raise RuntimeError("Redis not initialized — call init_redis() at startup")
    return _redis_client


async def redis_health_check() -> dict:
    try:
        client = get_redis_client()
        info = await client.info("server")
        t = asyncio.get_running_loop().time()
        await client.ping()
        latency_ms = round((asyncio.get_running_loop().time() - t) * 1000, 2)
        return {
            "status": "healthy",
            "latency_ms": latency_ms,
            "redis_version": info.get("redis_version", "unknown"),
            "used_memory_human": info.get("used_memory_human", "unknown"),
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
