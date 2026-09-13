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


def _db():
    """
    Postgres backend when DATABASE_URL is set, else None.

    Render's disk is ephemeral, so files alone mean the catalog vanishes on
    every deploy or spin-down. With a database configured, profiles persist and
    the site stays fast across restarts. Local development needs no database —
    files remain the default.
    """
    try:
        import db
        return db if db.available() else None
    except Exception:
        return None


def _slug(topic):
    """Turn 'BPC-157' into a safe filename like 'bpc-157'."""
    s = topic.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unknown"


def _path(topic):
    return os.path.join(CACHE_DIR, f"{_slug(topic)}.json")


def invalidate(topic):
    """
    Delete a cached profile so the next run regenerates it.

    Exists because validating an engine change against a cached profile is
    silent and looks identical to a real result — several rounds were spent
    inspecting stale output after a fix. `run.py --fresh` calls this first.
    Returns True if a file was removed.
    """
    removed = False
    d = _db()
    if d:
        removed = d.invalidate(_slug(topic))
    p = _path(topic)
    try:
        os.remove(p)
        removed = True
    except (FileNotFoundError, OSError):
        pass
    return removed


def get(topic, max_age_days=90):
    """Return a cached profile if it exists and isn't too old, else None."""
    d = _db()
    if d:
        hit = d.get(_slug(topic), max_age_days=max_age_days)
        if hit:
            return hit
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
    # Write through to the database when configured, so a generated profile
    # survives the next restart instead of living only until the disk is wiped.
    d = _db()
    if d:
        d.put(_slug(topic), profile)
    return profile


def list_cached():
    """List all cached topic slugs (what's already been generated)."""
    d = _db()
    if d:
        slugs = d.list_cached()
        if slugs:
            return slugs
    if not os.path.isdir(CACHE_DIR):
        return []
    return sorted(fn[:-5] for fn in os.listdir(CACHE_DIR) if fn.endswith(".json"))


def iter_profiles():
    """Stream stored profiles; avoid per-profile DB connections and full snapshots.

    If the database fails partway through, retain its completed entries and use
    local files for remaining slugs. Callers assess freshness independently.
    """
    database=_db();seen=set()
    if database:
        try:
            for slug,profile in database.iter_profiles():
                seen.add(slug)
                yield slug,profile
        except Exception as error:
            print(f'  [cache] index stream unavailable ({type(error).__name__}); using local records')
    if os.path.isdir(CACHE_DIR):
        for filename in sorted(os.listdir(CACHE_DIR)):
            if filename in {'retrieval.json','citations.json','translations.json'}:continue
            if not filename.endswith('.json') or filename[:-5] in seen:continue
            try:
                with open(os.path.join(CACHE_DIR,filename),encoding='utf-8') as source:
                    profile=json.load(source)
                if isinstance(profile,dict):yield filename[:-5],profile
            except (OSError,ValueError):continue
