# Architecture

## Service chain

```
                 ┌──────────────────┐
   browser  ───► │   order-api      │  (2 replicas, serves the UI)
                 │  GET /orders     │
                 └────────┬─────────┘
                          │ GET /pay
                          ▼
                 ┌──────────────────┐
                 │   payment-api    │  (2 replicas)
                 │  GET /pay        │
                 └────────┬─────────┘
                          │ GET /reserve
                          ▼
                 ┌──────────────────┐
                 │  inventory-api   │  (1 replica)
                 │  GET /reserve    │
                 └──────────────────┘
```

Each hop calls the next over the in-cluster Service DNS name
(`*-api-svc.resilience-lab.svc.cluster.local:8000`). `order-api` also serves
a small static UI at `/` showing the live state of all three services, polled
from the browser every ~1.2s.

Every service exposes:

- `GET /healthz` - liveness/readiness target.
- `GET /metrics` - Prometheus exposition format (`http_requests_total`,
  `http_request_duration_seconds`).

`order-api` and `payment-api` additionally read a `RESILIENT_MODE`
environment variable (default `true`). Toggling it to `false` and restarting
the deployment switches that hop from a resilient call (short timeout, one
retry, a circuit breaker, a graceful fallback) to a naive one (a single call
on the client's default timeout, no fallback) - the same codebase
demonstrates both the "before" and "after" of adding resilience patterns.
See `apps/*/resilience.py`.

## Cluster layout

A single-node kind cluster, namespace `resilience-lab`, holds:

- The three application deployments above.
- Chaos Mesh's controller-manager and per-node daemon (installed via Helm
  into a separate `chaos-mesh` namespace) - no web dashboard, to keep the
  footprint lean on a single laptop.
- A minimal Prometheus (single pod, 6h retention, scraping the three
  services directly - no Alertmanager, no node-exporter, no
  kube-state-metrics) and a minimal Grafana (single pod, one provisioned
  dashboard) for live observability during a demo.
- RBAC (`k8s/rbac/`) scoping who can create/delete Chaos Mesh custom
  resources in the namespace.

`order-api` (NodePort 30080), Prometheus (NodePort 30090), and Grafana
(NodePort 30030) are reachable from the host via the port mappings in
`k8s/kind-config.yaml` - `http://localhost:8080`, `:9090`, `:3000`.

## Why no service mesh and no event-driven architecture

Both are real, valid ways to improve reliability - a service mesh moves
retries, timeouts, and mTLS into the infrastructure layer; an event-driven,
asynchronous architecture changes the failure mode entirely (a queue absorbs
a downstream outage instead of the caller blocking on it). Both are left out
of this reference implementation on purpose, to keep the demo's moving parts
and its memory footprint minimal - see ADR 0001 for the same reasoning
applied to the chaos tooling itself.

## Chaos experiments

| Experiment | Targets | What it tests |
|---|---|---|
| `chaos/experiments/pod-kill.yaml` | one `payment-api` pod | Does a second replica absorb the traffic without the order chain failing? |
| `chaos/experiments/network-latency.yaml` | payment-api → inventory-api link | Does added latency downstream stay within the order chain's p99 budget? |
| `chaos/experiments/network-partition.yaml` | payment-api ↔ inventory-api link | Does payment-api degrade gracefully, or hang/fail, when inventory-api is completely unreachable? |

`chaos/validate.py` polls `order-api`'s `/orders` endpoint through each
experiment window and reports availability, the longest continuous outage,
and how much of a monthly error budget that outage would consume at a stated
SLA - see the README's SRE glossary for the definitions behind those terms.

## A verified finding: resilience compounds across hops

Confirmed by running the chain locally with `inventory-api` stopped:

- **`payment-api` alone, `RESILIENT_MODE=false`, calling a dead
  `inventory-api`:** a hard `502` in ~2s, with a plain error message. This is
  the "before" failure mode - no timeout tuning, no retry, no fallback.
- **The same failing `payment-api`, called through a still-resilient
  `order-api`:** the overall request still returns `200` with
  `"status": "degraded"`. `order-api`'s own timeout, retry, and fallback
  absorbed a naive failure one hop downstream.
- **The full chain in naive mode** (`order-api` and `payment-api` both
  `RESILIENT_MODE=false`) with `inventory-api` down: the `502` propagates
  all the way to the caller.

The practical takeaway: resilience patterns compound across a call chain,
which also means a single resilient hop can quietly mask a naive one
underneath it. That's useful in a pinch, but it is not a substitute for
applying the pattern at every hop - the masking hop still pays the retry
latency, and the moment *it* fails too, there is nothing left to fall back
on.
