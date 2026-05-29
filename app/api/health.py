"""
Health API.
/health       — liveness probe  (Kubernetes restarts pod if this fails)
/health/ready — readiness probe (Kubernetes stops traffic if this fails)
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.redis import redis_health_check
from app.utils.metrics import set_redis_status

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def liveness():
    """Always returns 200 if the process is alive."""
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness probe")
async def readiness():
    """Returns 200 only when all dependencies are reachable."""
    settings = get_settings()
    checks = {}
    healthy = True

    if settings.cache_enabled or settings.rate_limit_enabled:
        redis_status = await redis_health_check()
        checks["redis"] = redis_status
        is_redis_healthy = redis_status["status"] == "healthy"
        set_redis_status(is_redis_healthy)
        if not is_redis_healthy:
            healthy = False

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ready" if healthy else "degraded",
            "checks": checks,
            "version": settings.app_version,
            "environment": settings.environment,
        },
    )
