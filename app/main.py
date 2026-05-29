"""
Main FastAPI Application — production entry point.

Middleware order (outermost = first on request, last on response):
  SecurityHeadersMiddleware  →  adds security headers to every response
  RequestIDMiddleware        →  injects X-Request-ID trace header
  CORSMiddleware             →  handles preflight + cross-origin headers
  RateLimitMiddleware        →  enforces per-user request limits
  CacheMiddleware            →  serves cached GET responses from Redis
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import init_redis, close_redis
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.cache import CacheMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.api import health, demo, metrics_route
from app.utils.metrics import set_app_info

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "application_starting",
        extra={"version": settings.app_version, "environment": settings.environment},
    )
    try:
        if settings.cache_enabled or settings.rate_limit_enabled:
            await init_redis()
            logger.info("redis_initialized")
        else:
            logger.info("redis_skipped")

        set_app_info(version=settings.app_version, environment=settings.environment)
        logger.info("application_started")
        yield
    finally:
        logger.info("application_shutting_down")
        if settings.cache_enabled or settings.rate_limit_enabled:
            await close_redis()
        logger.info("application_stopped")


def create_application() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Production-grade distributed rate limiter with Redis backend",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
    )

    # ── Middleware stack — add in reverse order of execution ─────────────────
    # Last added = outermost = first to receive request

    # Cache (innermost — runs closest to route handler)
    if settings.cache_enabled:
        app.add_middleware(CacheMiddleware)
        logger.info("cache_middleware_enabled")

    # Rate limiting
    if settings.rate_limit_enabled:
        app.add_middleware(RateLimitMiddleware)
        logger.info(
            "rate_limit_middleware_enabled",
            extra={"strategy": settings.rate_limit_strategy},
        )

    # CORS
    origins = (
        settings.cors_origins.split(",")
        if settings.cors_origins != "*"
        else ["*"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Request ID tracing
    app.add_middleware(RequestIDMiddleware)

    # Security headers (outermost — applied to every response)
    app.add_middleware(SecurityHeadersMiddleware)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(demo.router)
    app.include_router(metrics_route.router)

    return app


app = create_application()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        workers=1,
        log_level=settings.log_level.lower(),
        reload=settings.debug,
    )
