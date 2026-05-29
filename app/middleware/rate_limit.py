"""
Rate Limiting Middleware.
Fixed: call_next is never called inside an except block — avoids
the Starlette NotImplementedError / ASGI stream corruption bug.
"""
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi import status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.redis import get_redis_client
from app.core.logging import get_logger
from app.services.rate_limiter import RateLimiterService
from app.utils.metrics import record_request, record_rate_limit

logger = get_logger(__name__)

SKIP_PATHS = {"/health", "/health/ready", "/metrics", "/docs", "/openapi.json", "/redoc"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._settings = get_settings()
        self._rate_limiter: Optional[RateLimiterService] = None

    def _get_rate_limiter(self) -> RateLimiterService:
        if self._rate_limiter is None:
            self._rate_limiter = RateLimiterService(
                redis_client=get_redis_client(),
                settings=self._settings,
            )
        return self._rate_limiter

    @staticmethod
    def _get_identifier(request: Request) -> str:
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"apikey:{api_key}"
        if hasattr(request.state, "user_id"):
            return f"user:{request.state.user_id}"
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        host = request.client.host if request.client else "unknown"
        return f"ip:{host}"

    async def dispatch(self, request: Request, call_next) -> Response:
        # Never rate-limit infra endpoints
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        identifier = self._get_identifier(request)
        start_time = time.time()

        # --- Check rate limit BEFORE calling call_next ---
        # This keeps call_next completely outside any except block.
        allowed = True
        current_usage = 0
        retry_after = 0
        error_occurred = False

        try:
            rate_limiter = self._get_rate_limiter()
            allowed, current_usage, retry_after = await rate_limiter.check_rate_limit(
                identifier=identifier
            )
            record_rate_limit(self._settings.rate_limit_strategy, allowed)
        except Exception as e:
            error_occurred = True
            logger.error(
                "rate_limit_check_error",
                extra={
                    "identifier": identifier,
                    "path": request.url.path,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            # Fail-open: allow the request through on Redis failure

        # --- Return 429 before touching call_next ---
        if not allowed:
            logger.info(
                "request_rate_limited",
                extra={
                    "identifier": identifier,
                    "path": request.url.path,
                    "retry_after": retry_after,
                },
            )
            record_request(request.method, request.url.path, 429, time.time() - start_time)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "rate_limit_exceeded",
                    "message": "Too many requests. Please try again later.",
                    "retry_after": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self._settings.rate_limit_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(start_time + retry_after)),
                },
            )

        # --- All clear — call downstream ---
        response = await call_next(request)

        # Attach rate limit headers
        remaining = max(0, self._settings.rate_limit_requests - current_usage)
        reset_time = int(start_time + self._settings.rate_limit_window_seconds)
        response.headers["X-RateLimit-Limit"] = str(self._settings.rate_limit_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_time)
        if error_occurred:
            response.headers["X-RateLimit-Error"] = "bypass"

        duration = time.time() - start_time
        record_request(request.method, request.url.path, response.status_code, duration)
        logger.info(
            "request_processed",
            extra={
                "identifier": identifier,
                "path": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
                "rate_limit_remaining": remaining,
            },
        )
        return response
