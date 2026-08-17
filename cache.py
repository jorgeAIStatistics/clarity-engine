"""
Profile cache — makes the "generating…" state real.

The first time a topic is researched, we run the (slow) pipeline and save the
finished profile to disk as JSON. Every request after that reads the cached file
instantly. This is the mechanism that keeps cost near zero (lazy generation) and
makes the app feel fast.

In production this would be a database (Postgres). For local dev, plain JSON files
in a /cache folder are perfect and require zero setup.
"""

import os
import json
import re
import time

CACHE_DIR = os.environ.get("CLARITY_CACHE_DIR", "cache")


def _slug(topic):
    """Turn 'BPC-157' into a safe filename like 'bpc-157'."""
    s = topic.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unknown"


def _path(topic):
    return os.path.join(CACHE_DIR, f"{_slug(topic)}.json")


def get(topic, max_age_days=90):
    """Return a cached profile if it exists and isn't too old, else None."""
    p = _path(topic)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Optional freshness check — evidence changes, so re-generate old profiles.
        gen = data.get("_cached_at", 0)
        if max_age_days and (time.time() - gen) > max_age_days * 86400:
            return None
        return data
    except Exception:
        return None


def put(topic, profile):
    """Save a finished profile to the cache."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    profile = dict(profile)
    profile["_cached_at"] = time.time()
    with open(_path(topic), "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    return profile


def list_cached():
    """List all cached topic slugs (what's already been generated)."""
    if not os.path.isdir(CACHE_DIR):
        return []
    return sorted(fn[:-5] for fn in os.listdir(CACHE_DIR) if fn.endswith(".json"))
