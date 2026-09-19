"""Keep the process warm so the first visitor after a quiet stretch does not pay for the cold path.

What is actually cold is measurable and is not Render spinning down — this service runs on a paid
plan that does not idle. Two things go cold inside the process:

  * the Neo4j driver's connection, where the first read costs about 3.3s against 0.45s warm;
  * the five-minute lru_cache in front of build_library(), which costs about 13s to rebuild —
    longer than the browser waits, which is how the index came to show fourteen curated profiles.

So this pings the local API rather than reaching out to the internet: one loopback request each to
health, graph stats and the library, every few minutes. It holds the connection open and keeps the
catalog bucket populated. It cannot and does not try to stop a platform-level spin-down; if this
service is ever moved to a plan that idles, an external pinger or a Render cron is the answer and
this loop is not.

Run as its own child of production.py, never as a thread inside gunicorn.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

INTERVAL = max(60, int(os.getenv('CLARITY_WARM_INTERVAL', '600')))
PATHS = ('/api/health', '/api/evidence/graph/stats', '/api/library')


def ping(base, path, timeout=45):
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(f'{base}{path}', timeout=timeout) as response:
            response.read(1)
            return response.status, round((time.perf_counter() - started) * 1000)
    except urllib.error.HTTPError as error:
        return error.code, round((time.perf_counter() - started) * 1000)
    except Exception as error:
        return type(error).__name__, round((time.perf_counter() - started) * 1000)


def sweep(base):
    return {path: ping(base, path) for path in PATHS}


def run_once(base):
    """One sweep, logged. Returns True when every path answered under 400, False otherwise.

    It never raises. A warmer that dies takes the supervisor's other children with it, and a 503
    from a restarting API is the ordinary case this exists for, not a reason to stop.
    """
    try:
        results = sweep(base)
    except Exception as error:
        print(json.dumps({'event': 'warm_failed', 'error': type(error).__name__}), flush=True)
        return False
    healthy = all(isinstance(status, int) and status < 400 for status, _ in results.values())
    print(json.dumps({'event': 'warm_sweep', 'base': base, 'healthy': healthy,
                      'results': {p: {'status': s, 'ms': ms} for p, (s, ms) in results.items()}}), flush=True)
    return healthy


def main(argv=None):
    base = (argv or sys.argv[1:] or [f"http://127.0.0.1:{os.getenv('PORT', '8000')}"])[0].rstrip('/')
    # The API needs to be listening before the first sweep means anything.
    time.sleep(min(30, INTERVAL))
    while True:
        run_once(base)
        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
