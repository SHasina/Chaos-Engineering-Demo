import asyncio
import random
import time

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

app = FastAPI(title="Inventory Service")

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "http_status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "endpoint"]
)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/reserve")
async def reserve():
    start = time.time()
    await asyncio.sleep(random.uniform(0.01, 0.05))
    duration = time.time() - start

    REQUEST_COUNT.labels(method="GET", endpoint="/reserve", http_status="200").inc()
    REQUEST_LATENCY.labels(method="GET", endpoint="/reserve").observe(duration)

    return {
        "status": "confirmed",
        "sku": f"SKU-{random.randint(100, 999)}",
        "latency_ms": round(duration * 1000, 1),
    }
