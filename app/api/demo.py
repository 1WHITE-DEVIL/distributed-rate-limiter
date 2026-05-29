"""
Demo API — shows rate limit and cache headers in action.
Use these endpoints to verify middleware is working correctly.
"""
import time
from fastapi import APIRouter, Request, Query

router = APIRouter(prefix="/api", tags=["demo"])


@router.get("/demo", summary="Demo endpoint — shows rate limit + cache headers")
async def demo(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number — varies cache key"),
):
    return {
        "message": "OK",
        "page": page,
        "timestamp": time.time(),
        "request_id": getattr(request.state, "request_id", None),
        "headers": {
            "x_ratelimit_limit": request.headers.get("X-RateLimit-Limit"),
            "x_ratelimit_remaining": request.headers.get("X-RateLimit-Remaining"),
        },
    }


@router.get("/demo/slow", summary="Slow endpoint — simulates 200ms processing")
async def demo_slow():
    import asyncio
    await asyncio.sleep(0.2)
    return {"message": "slow response", "timestamp": time.time()}


@router.post("/demo/write", summary="POST — never cached, always rate limited")
async def demo_write(request: Request):
    return {"message": "write accepted", "timestamp": time.time()}
