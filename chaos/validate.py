"""Steady-state hypothesis, made executable.

Polls a target endpoint for a fixed window, tracks the longest continuous
outage, and reports both an availability figure and how much of a monthly
error budget (at a stated SLA) that outage would have consumed. Exits
non-zero if the longest outage exceeds the recovery SLA - this is what
turns a chaos experiment into a CI gate instead of a one-off demo.
"""

import argparse
import sys
import time

import httpx

HEALTHY_STATUSES = {"confirmed", "degraded"}


def check_once(url: str, timeout: float) -> bool:
    try:
        resp = httpx.get(url, timeout=timeout)
    except httpx.HTTPError:
        return False
    if resp.status_code != 200:
        return False
    try:
        return resp.json().get("status") in HEALTHY_STATUSES
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="endpoint to poll, e.g. http://localhost:8080/orders")
    parser.add_argument("--duration", type=int, default=90, help="seconds to poll for")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between checks")
    parser.add_argument("--timeout", type=float, default=3.0, help="per-check request timeout")
    parser.add_argument("--recover-within", type=int, default=30, help="max allowed continuous outage, seconds")
    parser.add_argument("--sla", type=float, default=99.9, help="stated SLA percentage, for the error-budget line")
    args = parser.parse_args()

    start = time.monotonic()
    down_since = None
    longest_outage = 0.0
    total_checks = 0
    failed_checks = 0

    while time.monotonic() - start < args.duration:
        tick = time.monotonic()
        total_checks += 1
        ok = check_once(args.url, args.timeout)

        if not ok:
            failed_checks += 1
            if down_since is None:
                down_since = time.monotonic()
        elif down_since is not None:
            longest_outage = max(longest_outage, time.monotonic() - down_since)
            down_since = None

        elapsed = time.monotonic() - tick
        time.sleep(max(0.0, args.interval - elapsed))

    if down_since is not None:
        longest_outage = max(longest_outage, time.monotonic() - down_since)

    availability = 100.0 * (1 - failed_checks / total_checks) if total_checks else 0.0
    monthly_budget_seconds = (1 - args.sla / 100) * 30 * 24 * 3600

    print(f"checks: {total_checks}, failed: {failed_checks}, availability: {availability:.2f}%")
    print(f"longest continuous outage: {longest_outage:.1f}s (recovery SLA: {args.recover_within}s)")
    print(
        f"at a {args.sla}% SLA, this run's worst outage would consume "
        f"{longest_outage:.1f}s of the ~{monthly_budget_seconds:.0f}s monthly error budget"
    )

    if longest_outage > args.recover_within:
        print("FAIL: recovery exceeded the stated SLA")
        return 1

    print("PASS: recovered within the stated SLA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
