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

Both are container starts, not slow queries — the Free instance type spinning down after fifteen
idle minutes. Adding a second in-process loop would change nothing.

## What this is not

This does not make the site depend on the ping. `clarity-web` ships `public/library.json` and
`public/graph-profiles.json`, rebuilt by `python -m evidence.intent_graph.snapshot --write --bundle
../clarity-web/public`, and renders the catalog and the main profiles from those with the API
entirely unreachable — labelled as published copies. A pinger makes the live data fresher; it is
not what keeps the site up.

## Read this before setting one up

**Do not add a pinger while the service is on Render's Free instance type.** It will make the
outage worse, not better.

A Render workspace gets 750 free instance hours per calendar month, shared across every free web
service in it, and Render suspends all of them for the rest of the month once those hours are
gone. A service left to idle uses almost none of them. A service held awake by a pinger uses 24
hours a day — about 720 in a 30-day month — so a single always-on free service sits right on the
cap, and two exhaust it before the middle of the month.

Checked on 13 October 2026: the live `clarity-engine-api` service is on **Free**, while
`render.yaml` declares `plan: 0.5c-512mb`. The blueprint and the service have drifted, and the
blueprint does not retroactively change an existing service's instance type. That drift is what
produced every cold start recorded below.

The same day the service stopped waking at all: Render served its `SERVICE WAKING UP`
interstitial for seven minutes and then returned `503`, repeatedly, over about forty-five minutes.
A normal free spin-up takes about one minute. Seven minutes and a 503 is a suspended service or a
failed start, not a cold one.

## The fix is the instance type, not a pinger

Render dashboard → `clarity-engine-api` → Settings → Instance Type → `0.5c-512mb` (Starter,
$7/month at the time of writing). That is what `render.yaml` already declares, so it ends the
drift as well as the idling. A paid instance does not spin down, so no pinger is needed and none
of the hour accounting above applies.

Upgrading is a billing change on the Render account. It cannot be done from this repository.

## If a pinger is still wanted, on a paid instance

Any external scheduler works: an uptime service, a cron on a machine that is already awake, or a
scheduled GitHub Actions workflow in either repo. Nothing in this repository schedules it, and
nothing in this repository should: a job that hits production on a timer is a deployment decision,
not a code change.
