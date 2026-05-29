"""
Unit tests for Prometheus metrics utility.
"""
from app.utils import metrics as m


def test_set_app_info():
    m.set_app_info(version="1.0.0", environment="test")


def test_record_request_200():
    m.record_request("GET", "/api/demo", 200, 0.05)


def test_record_request_429():
    m.record_request("GET", "/api/demo", 429, 0.001)


def test_record_request_500():
    m.record_request("GET", "/api/demo", 500, 0.1)


def test_record_rate_limit_allowed():
    m.record_rate_limit("token_bucket", True)


def test_record_rate_limit_blocked():
    m.record_rate_limit("token_bucket", False)


def test_record_rate_limit_sliding_allowed():
    m.record_rate_limit("sliding_window", True)


def test_record_cache_hit():
    m.record_cache_operation("get", "hit")


def test_record_cache_miss():
    m.record_cache_operation("get", "miss")


def test_record_cache_set_success():
    m.record_cache_operation("set", "success")


def test_record_cache_error():
    m.record_cache_operation("set", "error")


def test_record_cache_delete():
    m.record_cache_operation("delete", "success")


def test_set_redis_status_up():
    m.set_redis_status(True)


def test_set_redis_status_down():
    m.set_redis_status(False)
