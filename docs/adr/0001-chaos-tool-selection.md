# ADR 0001: Chaos Mesh as the sole fault-injection tool

## Status

Accepted

## Context

This reference architecture needs a way to inject infrastructure and network
faults into a Kubernetes-hosted service chain, in a way that is auditable,
governable through RBAC, and runnable without a cloud account. The landscape
splits into three camps:

| Camp | Examples | Fit |
|---|---|---|
| CNCF / Kubernetes-native | Chaos Mesh, LitmusChaos, kube-monkey | Vendor-neutral, native CRDs, runs anywhere Kubernetes does |
| Cloud-provider native | Azure Chaos Studio, AWS FIS | Deepest integration for a team already committed to one hyperscaler; requires a cloud subscription |
| Commercial | Gremlin, Steadybit, Harness | Cross-platform governance and dashboards, at licensing cost and outside the org's existing IAM boundary |

## Decision

Use **Chaos Mesh** alone, covering the full fault taxonomy this reference
architecture needs (pod-kill, network delay, network partition) with one
tool and one operational surface to secure.

## Alternatives considered and rejected

- **LitmusChaos** - equally CNCF-governed and capable, but the full
  ChaosCenter experience needs its own datastore for equivalent capability.
  Heavier control plane for no functional gain at this scope.
- **Gremlin** - the commercial comparison, rejected on build-vs-buy grounds:
  proprietary, licensing/lock-in, a separate system of record outside the
  org's existing Kubernetes RBAC/IAM boundary.
- **kube-monkey** - unmaintained, a single fault type.
- **Chaos Toolkit** - considered for CI orchestration; dropped because it
  would duplicate a small validation script (`chaos/validate.py`) for no
  functional gain at this scope.
- **Azure Chaos Studio / AWS FIS** - the right next step for a team already
  committed to one hyperscaler. Not evaluated for adoption here: this build
  runs with no cloud account, by design, so it stays portable to any laptop
  or CI runner.

## Decision drivers

- CNCF governance, vendor-neutral.
- Native CRDs mean experiments are Kubernetes objects - version-controlled,
  PR-reviewed, deployed through the same pipeline as everything else
  (GitOps fit).
- Native Kubernetes RBAC (`k8s/rbac/`) gives a real multi-tenant governance
  model: a platform team owns the experiment templates, application teams
  get scoped trigger rights per namespace.
- `Schedule`/`Workflow` CRDs support continuous, scheduled verification
  rather than point-in-time GameDays, when this reference architecture is
  extended toward production.
- One tool covering the full fault taxonomy in scope is itself a maturity
  argument: fewer moving parts, a smaller operational and security surface
  to govern, than standardizing on multiple overlapping tools.

## Future extensions (not built here)

Mesh-layer fault injection (for example, Istio `VirtualService` fault
injection) as a second maturity layer, for platforms already running a
service mesh. Deliberately out of scope for this reference implementation -
named here as a scoping decision, not a gap.

Event-driven / asynchronous architecture (queues, event buses) is another
axis that materially changes failure modes and resilience patterns
(backpressure, dead-letter queues, at-least-once delivery) but is out of
scope for this synchronous, three-service reference chain.
