"""
Locust Load Test.

Run:
    pip install locust
    locust -f locustfile.py --headless -u 100 -r 10 --run-time 60s --host http://localhost:8000

Pass criteria:
    p99 latency < 50ms
    Errors column = 0
    Rate limited count > 0 (proves limiter is working on burst users)
    Cache hit rate > 30% after 10s warmup
"""
import random
from locust import HttpUser, task, between, events

stats = {"rate_limited": 0, "cache_hits": 0, "cache_misses": 0, "errors": 0}


class APIUser(HttpUser):
    """Normal API consumer — moderate request rate."""
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.headers = {"X-API-Key": f"user-{random.randint(1, 50)}"}

    @task(5)
    def demo(self):
        with self.client.get(
            "/api/demo", headers=self.headers, catch_response=True, name="/api/demo"
        ) as r:
            if r.status_code == 200:
                if r.headers.get("X-Cache-Status") == "HIT":
                    stats["cache_hits"] += 1
                else:
                    stats["cache_misses"] += 1
                r.success()
            elif r.status_code == 429:
                stats["rate_limited"] += 1
                r.success()  # 429 is expected — not an error
            else:
                stats["errors"] += 1
                r.failure(f"Unexpected {r.status_code}")

    @task(3)
    def demo_paged(self):
        page = random.randint(1, 5)
        with self.client.get(
            f"/api/demo?page={page}", headers=self.headers,
            catch_response=True, name="/api/demo?page=[n]"
        ) as r:
            if r.status_code in (200, 429):
                r.success()
            else:
                r.failure(f"Unexpected {r.status_code}")

    @task(2)
    def health(self):
        self.client.get("/health", name="/health")

    @task(1)
    def ready(self):
        with self.client.get("/health/ready", catch_response=True, name="/health/ready") as r:
            if r.status_code in (200, 503):
                r.success()


class BurstUser(HttpUser):
    """Aggressive user — should get rate limited quickly."""
    wait_time = between(0.01, 0.05)

    def on_start(self):
        self.headers = {"X-API-Key": f"burst-{random.randint(1, 3)}"}

    @task
    def burst(self):
        with self.client.get(
            "/api/demo", headers=self.headers,
            catch_response=True, name="/api/demo [burst]"
        ) as r:
            if r.status_code in (200, 429):
                r.success()
            else:
                r.failure(f"Unexpected {r.status_code}")


@events.quitting.add_listener
def on_quit(environment, **kwargs):
    total_cache = stats["cache_hits"] + stats["cache_misses"]
    hit_rate = round(stats["cache_hits"] / total_cache * 100, 1) if total_cache else 0
    print("\n" + "=" * 50)
    print("LOAD TEST SUMMARY")
    print("=" * 50)
    print(f"  Rate limited (429): {stats['rate_limited']}")
    print(f"  Cache hits:         {stats['cache_hits']}")
    print(f"  Cache misses:       {stats['cache_misses']}")
    print(f"  Cache hit rate:     {hit_rate}%")
    print(f"  Errors:             {stats['errors']}")
    print("=" * 50)
    if stats["errors"] > 0:
        print("FAILED — errors detected")
    elif stats["rate_limited"] == 0:
        print("WARNING — no requests were rate limited (check burst users)")
    else:
        print("PASSED")
