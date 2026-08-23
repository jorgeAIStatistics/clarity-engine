"""
Clarity Engine — HTTP API.

Wraps the existing engine (run.research) behind a small web API the frontend can
call. Designed cache-first so it stays cheap: a search that's already been
generated is served instantly from cache and costs nothing; only a genuine
cache MISS triggers a (slow, paid) generation.

COST & ABUSE PROTECTION IS BUILT IN, NOT BOLTED ON — because a public endpoint
that generates on demand is a public endpoint that spends your money on demand:
  1. DAILY_GENERATION_CAP   — hard limit on NEW generations per day (cached hits
                              don't count). Once hit, misses return 503 instead
                              of spending. This is your bill's circuit breaker.
  2. Per-IP rate limiting   — one client can't hammer generation.
  3. Input validation       — topic length/charset limited; blocks junk queries.
  4. The ANTHROPIC key lives in the server env, never sent to the browser.

Run locally:
    pip install flask flask-cors
    python app.py
Then the API is at http://localhost:8000

Endpoints:
    GET  /api/health
    GET  /api/cached                 -> list of already-generated slugs (free)
    GET  /api/profile?topic=creatine&category=supplement
                                     -> cache-first; generates on miss (capped)
"""

import os
import time
import threading
from collections import defaultdict

from flask import Flask, request, jsonify
from flask_cors import CORS

import run
import cache

app = Flask(__name__)
CORS(app)  # allow the frontend origin to call this API

# ---- Guardrail configuration (tune via env vars) --------------------------
DAILY_GENERATION_CAP = int(os.environ.get("CLARITY_DAILY_CAP", "50"))
PER_IP_MIN_INTERVAL = float(os.environ.get("CLARITY_IP_INTERVAL", "3.0"))  # seconds
MAX_TOPIC_LEN = 80

# ---- In-memory counters (fine for single-process; use Redis if you scale) --
_lock = threading.Lock()
_gen_day = [time.strftime("%Y-%m-%d"), 0]      # [date, count]
_last_ip_call = defaultdict(float)


def _valid_topic(t):
    if not t or len(t) > MAX_TOPIC_LEN:
        return False
    # letters, numbers, spaces, hyphens only — blocks injection / junk
    return all(c.isalnum() or c in " -_" for c in t)


def _rate_limited(ip):
    now = time.time()
    with _lock:
        if now - _last_ip_call[ip] < PER_IP_MIN_INTERVAL:
            return True
        _last_ip_call[ip] = now
    return False


def _generation_budget_ok():
    today = time.strftime("%Y-%m-%d")
    with _lock:
        if _gen_day[0] != today:
            _gen_day[0], _gen_day[1] = today, 0
        return _gen_day[1] < DAILY_GENERATION_CAP


def _count_generation():
    with _lock:
        _gen_day[1] += 1


@app.get("/api/health")
def health():
    return jsonify({"ok": True,
                    "generations_today": _gen_day[1],
                    "daily_cap": DAILY_GENERATION_CAP})


@app.get("/api/cached")
def cached():
    # Free: just lists what's already on disk. No generation, no cost.
    # Exclude the engine's internal cache files (LLM caches etc.) — they live in
    # the same folder but are not compound profiles.
    internal = {"effect_sizes", "llm_population", "effect-sizes", "llm-population"}
    profiles = [s for s in cache.list_cached() if s not in internal]
    return jsonify({"cached": profiles})


@app.get("/api/profile")
def profile():
    topic = (request.args.get("topic") or "").strip()
    category = (request.args.get("category") or "supplement").strip()
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")

    if not _valid_topic(topic):
        return jsonify({"error": "invalid topic"}), 400

    # Resolve vendor/brand/street names to the compound the research is under
    # (e.g. "GLP-3" -> retatrutide, "Ozempic" -> semaglutide). The note is
    # returned so the UI can tell the user WHY they're seeing a different name.
    alias_note = None
    try:
        import aliases as _aliases
        resolved, resolved_cat, alias_note = _aliases.resolve(topic)
        if resolved.lower() != topic.lower():
            topic = resolved
            if resolved_cat:
                category = resolved_cat
    except Exception:
        pass

    # 1) CACHE FIRST — always free, always fast. This is the common path.
    cached_profile = cache.get(topic)
    if cached_profile:
        return jsonify({"profile": cached_profile, "source": "cache", "alias_note": alias_note})

    # 2) CACHE MISS -> would generate (slow + paid). Apply guardrails.
    if _rate_limited(ip):
        return jsonify({"error": "rate limited; try again in a few seconds"}), 429
    if not _generation_budget_ok():
        return jsonify({"error": "daily research limit reached; try again tomorrow",
                        "hint": "already-researched compounds are still available"}), 503

    # 3) Generate (cache-first inside research too; writes to cache on success).
    try:
        _count_generation()
        result = run.research(topic, category, use_cache=True, verbose=False)
        return jsonify({"profile": result, "source": "generated", "alias_note": alias_note})
    except Exception as e:
        return jsonify({"error": "generation failed", "detail": type(e).__name__}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
