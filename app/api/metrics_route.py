"""
Prometheus metrics scrape endpoint.
Prometheus scrapes this every 15s. Do not expose publicly without auth.
"""
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def metrics():
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )
