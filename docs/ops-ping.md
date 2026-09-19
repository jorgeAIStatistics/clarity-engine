# Keeping the API warm

## The URL

```
https://clarity-engine-api.onrender.com/api/health
```

Expect `200` and a small JSON body. Any interval between 5 and 14 minutes is fine.

**Not `/health`** — that path returns 404. A 404 still wakes the container, so it would work as a
keep-alive by accident, but every monitor would report the check as failing and nobody would trust
the alert that mattered. Use `/api/health`.

## Why an external pinger and not another loop in the app

The service already runs an in-process warmer (`evidence/warm.py`, started by `production.py`). It
pings `/api/health`, `/api/evidence/graph/stats` and `/api/library` on the loopback every ten
minutes, and it does hold the Neo4j connection and the catalog cache warm.

It cannot do the thing that actually hurts. When the container is stopped the warmer is stopped
with it, so nothing inside the box can wake the box. Measured on 2026-09-19:

| request | time |
|---|---|
| first `/api/evidence/graph/stats` of the morning | **37.0s** |
| `/health` later the same evening | **42.5s** |
| the same endpoints once the container is up | 0.3–1.6s |

Both are container starts, not slow queries. Adding a second in-process loop would change nothing.

## What this is not

This does not make the site depend on the ping. `clarity-web` ships `public/library.json` and
`public/graph-profiles.json`, rebuilt by `python -m evidence.intent_graph.snapshot --write --bundle
../clarity-web/public`, and renders the catalog and the main profiles from those with the API
entirely unreachable — labelled as published copies. A pinger makes the live data fresher; it is
not what keeps the site up.

## Setting one up

Any external scheduler works: an uptime service, a cron on a machine that is already awake, or a
scheduled GitHub Actions workflow in either repo. Nothing in this repository schedules it, and
nothing in this repository should: a job that hits production on a timer is a deployment decision,
not a code change.

If the service is moved to a Render plan that does not idle, none of this is needed — check the
plan before adding a pinger, because the blueprint in `render.yaml` already claims one that should
not spin down.
