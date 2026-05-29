"""
Prometheus Metrics — counters, histograms, gauges for full observability.
"""
from prometheus_client import Counter, Histogram, Gauge, Info

APP_INFO = Info("app", "Application metadata")

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)
RATE_LIMIT_HITS_TOTAL = Counter(
    "rate_limit_hits_total",
    "Total rate limit checks",
    ["strategy", "result"],
)
CACHE_OPERATIONS_TOTAL = Counter(
    "cache_operations_total",
    "Total cache operations",
    ["operation", "result"],
)
REDIS_CONNECTED = Gauge("redis_connected", "Redis connection status 1=up 0=down")


def set_app_info(version: str, environment: str) -> None:
    APP_INFO.info({"version": version, "environment": environment})


def record_request(method: str, path: str, status_code: int, duration: float) -> None:
    HTTP_REQUESTS_TOTAL.labels(
        method=method, path=path, status_code=str(status_code)
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=path).observe(duration)


def record_rate_limit(strategy: str, allowed: bool) -> None:
    RATE_LIMIT_HITS_TOTAL.labels(
        strategy=strategy,
        result="allowed" if allowed else "blocked",
    ).inc()


def record_cache_operation(operation: str, result: str) -> None:
    CACHE_OPERATIONS_TOTAL.labels(operation=operation, result=result).inc()


def set_redis_status(connected: bool) -> None:
    REDIS_CONNECTED.set(1 if connected else 0)
