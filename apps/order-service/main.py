import os
import random
import time

import httpx
from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from resilience import CircuitBreaker, call_downstream

app = FastAPI(title="Order Service")

PAYMENT_SERVICE_URL = os.getenv(
    "PAYMENT_SERVICE_URL", "http://payment-api-svc.resilience-lab.svc.cluster.local:8000"
)
RESILIENT_MODE = os.getenv("RESILIENT_MODE", "true").lower() == "true"

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "http_status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "endpoint"]
)

payment_breaker = CircuitBreaker(failure_threshold=3, reset_timeout=10)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/orders")
async def create_order():
    start = time.time()
    order_id = random.randint(1000, 9999)

    async with httpx.AsyncClient() as client:
        payment_result, error = await call_downstream(
            client,
            f"{PAYMENT_SERVICE_URL}/pay",
            payment_breaker,
            resilient=RESILIENT_MODE,
        )

    if error is None:
        status = "confirmed"
    elif payment_result is not None:
        status = "degraded"
    else:
        status = "failed"

    duration = time.time() - start
    http_status = 200 if status in ("confirmed", "degraded") else 502

    REQUEST_COUNT.labels(method="GET", endpoint="/orders", http_status=str(http_status)).inc()
    REQUEST_LATENCY.labels(method="GET", endpoint="/orders").observe(duration)

    body = {
        "order_id": order_id,
        "status": status,
        "payment": payment_result,
        "error": error,
        "latency_ms": round(duration * 1000, 1),
        "resilient_mode": RESILIENT_MODE,
    }

    if http_status != 200:
        return JSONResponse(content=body, status_code=http_status)
    return body


# Mounted last: explicit routes above always win, everything else falls
# through to the static UI (index.html at "/", assets alongside it).
app.mount("/", StaticFiles(directory="static", html=True), name="static")
