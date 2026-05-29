"""
Cache Middleware.
Caches GET responses in Redis. Skips admin/auth/metrics paths.
call_next is never called inside an except block.
"""
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.core.redis import get_redis_client
from app.core.logging import get_logger
from app.utils.metrics import record_cache_operation

logger = get_logger(__name__)

NO_CACHE_PREFIXES = ("/admin", "/auth", "/metrics", "/health")


class CacheMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._settings = get_settings()
        self._cache_service = None

    def _get_cache_service(self):
        if self._cache_service is None:
            from app.services.cache import CacheService
            self._cache_service = CacheService(
                redis_client=get_redis_client(),
                settings=self._settings,
            )
        return self._cache_service

    def _should_cache(self, request: Request) -> bool:
        if request.method != "GET":
            return False
        if request.headers.get("X-Cache-Bypass") == "true":
            return False
        return not any(request.url.path.startswith(p) for p in NO_CACHE_PREFIXES)

    def _extract_user_id(self, request: Request):
        return request.headers.get("X-API-Key") or getattr(request.state, "user_id", None)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self._should_cache(request):
            response = await call_next(request)
            response.headers["X-Cache-Status"] = "SKIP"
            return response

        user_id = self._extract_user_id(request)
        query_params = dict(request.query_params) or None

        # Try to serve from cache
        cached = None
        try:
            cached = await self._get_cache_service().get(
                path=request.url.path,
                query_params=query_params,
                user_id=user_id,
            )
        except Exception as e:
            logger.error("cache_read_error", extra={"path": request.url.path, "error": str(e)})

        if cached:
            record_cache_operation("get", "hit")
            response = Response(
                content=cached.get("content", ""),
                status_code=cached.get("status_code", 200),
                headers=cached.get("headers", {}),
                media_type=cached.get("media_type", "application/json"),
            )
            response.headers["X-Cache-Status"] = "HIT"
            return response
        record_cache_operation("get", "miss")

        # Cache miss — call downstream
        response = await call_next(request)

        if 200 <= response.status_code < 300:
            body = b""
            async for chunk in response.body_iterator:
                body += chunk

            try:
                content_str = body.decode("utf-8")
                await self._get_cache_service().set(
                    path=request.url.path,
                    response_data={
                        "content": content_str,
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "media_type": response.media_type,
                    },
                    query_params=query_params,
                    user_id=user_id,
                )
                record_cache_operation("set", "ok")
            except UnicodeDecodeError:
                logger.debug("cache_skip_binary", extra={"path": request.url.path})
                record_cache_operation("set", "skip_binary")
            except Exception as e:
                logger.error("cache_write_error", extra={"path": request.url.path, "error": str(e)})
                record_cache_operation("set", "error")

            response = Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
            response.headers["X-Cache-Status"] = "MISS"
        else:
            response.headers["X-Cache-Status"] = "SKIP"

        return response
