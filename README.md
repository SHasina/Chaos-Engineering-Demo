# Resilience Lab: SLO-Driven Chaos Engineering

A reference architecture that validates the reliability of a small
cloud-native service chain by deliberately breaking it, on a single laptop,
with no cloud account required.

Three FastAPI services form a synchronous call chain - `order-api` calls
`payment-api`, which calls `inventory-api` - deployed to a local
[kind](https://kind.sigs.k8s.io/) Kubernetes cluster alongside
[Chaos Mesh](https://chaos-mesh.org/) for fault injection and a minimal
Prometheus/Grafana stack for observability. A GitHub Actions pipeline runs
the same experiments against real load on every push, gating on whether the
system recovers within a stated SLA.

See [`docs/architecture.md`](docs/architecture.md) for the full component
diagram and [`docs/adr/0001-chaos-tool-selection.md`](docs/adr/0001-chaos-tool-selection.md)
for why Chaos Mesh was chosen over the alternatives.

## Repository layout

```
apps/
  order-service/      FastAPI, serves the UI and GET /orders
  payment-service/     FastAPI, GET /pay
  inventory-service/    FastAPI, GET /reserve
k8s/
  namespace.yaml
  kind-config.yaml     single-node cluster, NodePort mappings
  order/ payment/ inventory/   Deployment + Service per component
  rbac/                who may manage Chaos Mesh resources, and how
  observability/       Prometheus + Grafana, provisioned
chaos/
  experiments/         PodChaos / NetworkChaos definitions
  validate.py          steady-state check, used locally and in CI
load/k6/               background traffic generator
docs/
  architecture.md
  adr/0001-chaos-tool-selection.md
.github/workflows/
  chaos-pipeline.yml    the CI resilience gate
```

## Running it locally

Requirements: Docker Desktop, `kind`, `kubectl`, `helm`.

```bash
# 1. Build the three service images
docker build -t order-api:local ./apps/order-service
docker build -t payment-api:local ./apps/payment-service
docker build -t inventory-api:local ./apps/inventory-service

# 2. Create the cluster and load the images
kind create cluster --config k8s/kind-config.yaml --name resilience-lab
kind load docker-image order-api:local payment-api:local inventory-api:local --name resilience-lab

# 3. Deploy
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/rbac/
kubectl apply -f k8s/order/ -f k8s/payment/ -f k8s/inventory/
kubectl apply -f k8s/observability/

# 4. Install Chaos Mesh (no dashboard, to keep the footprint small)
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm repo update
kubectl create namespace chaos-mesh
helm install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace=chaos-mesh --set dashboard.create=false --wait
```

Then open:

- `http://localhost:8080` - the live service-chain dashboard
- `http://localhost:9090` - Prometheus
- `http://localhost:3000` - Grafana (the "Resilience Lab" dashboard is
  provisioned automatically)

Run an experiment:

```bash
kubectl apply -f chaos/experiments/pod-kill.yaml
python3 chaos/validate.py --url http://localhost:8080/orders --duration 45 --recover-within 30
kubectl delete -f chaos/experiments/pod-kill.yaml
```

To see the "before resilience" behavior, flip the flag and restart the
affected deployment, then re-run the partition experiment:

```bash
kubectl -n resilience-lab set env deployment/payment-api RESILIENT_MODE=false
kubectl apply -f chaos/experiments/network-partition.yaml
python3 chaos/validate.py --url http://localhost:8080/orders --duration 75 --recover-within 30
kubectl delete -f chaos/experiments/network-partition.yaml
kubectl -n resilience-lab set env deployment/payment-api RESILIENT_MODE=true
```

### Freeing memory between sessions

Docker images built above stay cached on disk at no memory cost. To reclaim
the cluster's memory when not actively using it:

```bash
kind delete cluster --name resilience-lab
```

Recreating it from the cached images (steps 2-4 above, skipping the builds)
takes a couple of minutes and needs no rebuild.

## Continuous validation

`.github/workflows/chaos-pipeline.yml` runs on every push: it builds the
three images, stands up an ephemeral kind cluster, deploys the chain,
installs Chaos Mesh, generates background load with k6, and runs each of the
three experiments in turn - failing the build if recovery exceeds the stated
SLA. This is the resilience gate: a change that breaks recovery behavior
does not merge silently. With `RESILIENT_MODE=true` as the deployed default,
this gate is expected to stay green.

`.github/workflows/before-after-demo.yml` is a separate, `workflow_dispatch`-
only workflow - not a gate, a demonstration. It runs the same network-
partition experiment twice against the same deployment: once with
`payment-api` in naive mode (that step is marked `continue-on-error` because
it is expected to fail the stated SLA) and once in resilient mode (expected
to pass). Run it from the Actions tab to see the naive failure and the
resilient recovery side by side in one run's logs.

## SRE and resilience glossary

**SLI (Service Level Indicator)** - a directly measured signal, such as
availability, error rate, or p95 latency. In this repository, SLIs are read
straight from each service's Prometheus metrics.

**SLO (Service Level Objective)** - the internal reliability target
engineered for, usually set with margin above the SLA. Example used here:
99.95% availability, p95 latency under 500ms.

**SLA (Service Level Agreement)** - the external, often contractual,
reliability commitment made to customers. Example used here: 99.9%
availability, which allows roughly 43.2 minutes of downtime per 30-day
month.

**Error budget** - the amount of unreliability an SLA permits, expressed as
time: at a 99.9% SLA, the monthly error budget is about 43.2 minutes.
`chaos/validate.py` reports how much of that budget a single experiment's
worst outage would consume.

**Steady state** - the measurable, boring baseline a system holds when
nothing is wrong. Every hypothesis in this repository is checked against a
stated steady state, not a vague sense that "it seems fine."

**Chaos engineering** - the discipline of forming a hypothesis about how a
system behaves under a specific failure, deliberately introducing that
failure under a controlled blast radius, and measuring whether the
hypothesis held. It is distinct from random destructive testing: the
hypothesis, the measurement, and the learning loop are what make it an
experiment rather than an outage.

**Fault injection** - the mechanism (killing a pod, adding latency,
partitioning a network link). Chaos engineering is the broader discipline
built around that mechanism.

**Blast radius** - the scope a fault is allowed to reach: one pod, one link,
one percent of traffic. This repository's experiments are scoped to a
single dependency link at a time.

**Abort condition** - the trip-wire that halts an experiment before it
becomes an incident. In CI, `chaos/validate.py` exiting non-zero is that
trip-wire; in a production rollout, it would be wired to the same alerting
the on-call team already trusts.

**GameDay** - a scheduled, coordinated resilience exercise involving the
humans who operate a system, not just its software - testing whether the
team can diagnose and respond under a failure, not only whether the
infrastructure recovers.

**Circuit breaker** - a pattern that stops calling a dependency once it has
failed enough times in a row, failing fast instead of continuing to pile up
slow, doomed requests against it. Implemented in `apps/*/resilience.py`,
active when `RESILIENT_MODE=true`.

**Retry** - re-attempting a failed call, usually a small, bounded number of
times, on the assumption that the failure might be transient. Implemented
alongside the circuit breaker above; it is bounded (one retry) so that
retries cannot themselves cause a request pile-up.

**Timeout** - an upper bound on how long a caller will wait for a
dependency before giving up. `RESILIENT_MODE=true` uses a short, explicit
timeout (1.5s); `RESILIENT_MODE=false` falls back to the HTTP client's
default, demonstrating why an explicit timeout matters.

**Fallback** - a degraded but useful response returned when a dependency is
unavailable, instead of surfacing that failure to the caller. In this
repository, a degraded order still returns `HTTP 200` with
`"status": "degraded"`, rather than failing the whole request.

**RBAC (Role-Based Access Control)** - scoping who may perform which
actions on which resources. `k8s/rbac/` scopes who may create, run, or
delete Chaos Mesh experiments in this namespace - a real governance
boundary, not a convention.

**Maturity model (this repository's position)** - level 0: no resilience
testing. Level 1: manual, occasional experiments. Level 2: scheduled
GameDays. **Level 3: CI/CD-gated** - the level this repository operates at,
where `chaos-pipeline.yml` blocks a regression on every push. Level 4:
continuous, RBAC-scoped verification in production, feeding the error.
budget directly - the target state this reference architecture is designed
to grow into, not something it runs today.


** Commands for Local Testing:**


http://localhost:8080 (the live order UI — this is what's already generating traffic)
http://localhost:3000 → "Resilience Lab" dashboard (admin/admin)


cd C:\Users\HP\Chaos-Engineering

pod-kill ("Request rate by service")

docker run -d --rm --name k6-run -e BASE_URL=http://host.docker.internal:8080 -e K6_DURATION=45s -v "${PWD}\load\k6:/scripts" grafana/k6 run /scripts/script.js
kubectl apply -f chaos/experiments/pod-kill.yaml
python chaos/validate.py --url http://localhost:8080/orders --duration 45 --recover-within 30
kubectl delete -f chaos/experiments/pod-kill.yaml

network-latency ("p95 latency by service", payment-api line)

docker run -d --rm --name k6-run -e BASE_URL=http://host.docker.internal:8080 -e K6_DURATION=75s -v "${PWD}\load\k6:/scripts" grafana/k6 run /scripts/script.js
kubectl apply -f chaos/experiments/network-latency.yaml
python chaos/validate.py --url http://localhost:8080/orders --duration 75 --recover-within 30
kubectl delete -f chaos/experiments/network-latency.yaml

network-partition, both resilient → PASS

docker run -d --rm --name k6-run -e BASE_URL=http://host.docker.internal:8080 -e K6_DURATION=75s -v "${PWD}\load\k6:/scripts" grafana/k6 run /scripts/script.js
kubectl apply -f chaos/experiments/network-partition.yaml
python chaos/validate.py --url http://localhost:8080/orders --duration 75 --recover-within 30
kubectl delete -f chaos/experiments/network-partition.yaml

Act 3b — payment-api naive only, order-api still resilient → PASS but degraded

kubectl -n resilience-lab set env deployment/payment-api RESILIENT_MODE=false
kubectl -n resilience-lab rollout status deployment/payment-api --timeout=60s

docker run -d --rm --name k6-run -e BASE_URL=http://host.docker.internal:8080 -e K6_DURATION=75s -v "${PWD}\load\k6:/scripts" grafana/k6 run /scripts/script.js
kubectl apply -f chaos/experiments/network-partition.yaml
curl.exe -s http://localhost:8080/orders
python chaos/validate.py --url http://localhost:8080/orders --duration 70 --recover-within 30
kubectl delete -f chaos/experiments/network-partition.yaml


Act 3c — both naive → real FAIL

kubectl -n resilience-lab set env deployment/order-api RESILIENT_MODE=false
kubectl -n resilience-lab rollout status deployment/order-api --timeout=60s

docker run -d --rm --name k6-run -e BASE_URL=http://host.docker.internal:8080 -e K6_DURATION=75s -v "${PWD}\load\k6:/scripts" grafana/k6 run /scripts/script.js
kubectl apply -f chaos/experiments/network-partition.yaml
python chaos/validate.py --url http://localhost:8080/orders --duration 75 --recover-within 30
kubectl delete -f chaos/experiments/network-partition.yaml

Reset to baseline

kubectl -n resilience-lab set env deployment/order-api RESILIENT_MODE=true
kubectl -n resilience-lab set env deployment/payment-api RESILIENT_MODE=true
kubectl -n resilience-lab rollout status deployment/order-api --timeout=60s
kubectl -n resilience-lab rollout status deployment/payment-api --timeout=60s
