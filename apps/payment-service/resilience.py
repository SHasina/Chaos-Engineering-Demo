import time

import httpx


class CircuitBreaker:
    """A minimal circuit breaker: opens after N consecutive failures and
    stops calling a failing dependency until the reset timeout elapses."""

    def __init__(self, failure_threshold: int = 3, reset_timeout: float = 10.0):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.opened_at: float | None = None

    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.time() - self.opened_at > self.reset_timeout:
            return False  # half-open: allow the next call through as a trial
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.time()


async def call_downstream(
    client: httpx.AsyncClient,
    url: str,
    breaker: CircuitBreaker,
    resilient: bool = True,
    timeout: float = 1.5,
    retries: int = 1,
):
    """Call a downstream dependency and return (result, error).

    Naive mode: a single call on the client's default timeout. Whatever
    fails, fails, and the caller finds out from an empty result.

    Resilient mode: a short timeout, one retry, a circuit breaker that
    stops hammering an already-failing dependency, and a graceful
    fallback payload instead of surfacing the failure to our own caller.
    """
    if not resilient:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json(), None
        except httpx.HTTPError as exc:
            return None, f"naive call failed: {exc or type(exc).__name__}"

    if breaker.is_open():
        return {"status": "degraded", "reason": "circuit_open"}, "circuit_open"

    last_error = None
    for _ in range(retries + 1):
        try:
            resp = await client.get(url, timeout=timeout)
            resp.raise_for_status()
            breaker.record_success()
            return resp.json(), None
        except httpx.HTTPError as exc:
            last_error = str(exc) or type(exc).__name__
            breaker.record_failure()

    return {"status": "degraded", "reason": last_error}, last_error
