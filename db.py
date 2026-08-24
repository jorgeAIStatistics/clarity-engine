"""
Postgres storage for profiles.

WHY THIS EXISTS: Render's filesystem is ephemeral. Every deploy, restart, or
idle spin-down wipes the cache folder — so an hour of catalog generation
survives only until the next push, and any profile generated for a user
disappears. That makes "cached" mean "until something restarts", which is not
persistence at all.

DESIGN: this is a drop-in backend for cache.py, not a replacement for it. The
same four operations (get / put / invalidate / list_cached), so no other module
changes. cache.py picks Postgres when DATABASE_URL is set and falls back to
JSON files otherwise — local development needs no database, and the deployed
service gets durability.

SCHEMA: one table, profile JSON stored as JSONB. Slug is the primary key so
put() is an upsert and re-generating a compound replaces it atomically.
"""

import os
import json
import time

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    slug        TEXT PRIMARY KEY,
    name        TEXT,
    category    TEXT,
    tier        TEXT,
    study_count INTEGER,
    profile     JSONB NOT NULL,
    cached_at   DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS profiles_tier_idx ON profiles (tier);
CREATE INDEX IF NOT EXISTS profiles_category_idx ON profiles (category);
"""

_pool = None
_init_done = False


def available():
    """True if a database is configured and the driver is importable."""
    if not DATABASE_URL:
        return False
    try:
        import psycopg  # noqa: F401
        return True
    except ImportError:
        try:
            import psycopg2  # noqa: F401
            return True
        except ImportError:
            return False


def _connect():
    """
    Open a connection. Prefers psycopg 3, falls back to psycopg2 so this works
    whichever driver the host image provides.
    """
    url = DATABASE_URL
    try:
        import psycopg
        return psycopg.connect(url)
    except ImportError:
        import psycopg2
        return psycopg2.connect(url)


def _ensure_schema(conn):
    global _init_done
    if _init_done:
        return
    with conn.cursor() as cur:
        cur.execute(_SCHEMA)
    conn.commit()
    _init_done = True


def get(slug, max_age_days=90):
    """Return a profile dict, or None if absent / too old / unavailable."""
    if not available():
        return None
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT profile, cached_at FROM profiles WHERE slug = %s",
                    (slug,))
                row = cur.fetchone()
        if not row:
            return None
        profile, cached_at = row[0], row[1]
        if max_age_days and (time.time() - float(cached_at)) > max_age_days * 86400:
            return None
        # psycopg returns JSONB as dict; psycopg2 may return str.
        return profile if isinstance(profile, dict) else json.loads(profile)
    except Exception as e:
        print(f"  [db] get failed ({type(e).__name__}); falling back to files")
        return None


def put(slug, profile):
    """Upsert a profile. Returns True on success."""
    if not available():
        return False
    try:
        payload = json.dumps(profile)
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO profiles
                        (slug, name, category, tier, study_count, profile, cached_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (slug) DO UPDATE SET
                        name = EXCLUDED.name,
                        category = EXCLUDED.category,
                        tier = EXCLUDED.tier,
                        study_count = EXCLUDED.study_count,
                        profile = EXCLUDED.profile,
                        cached_at = EXCLUDED.cached_at
                    """,
                    (slug, profile.get("name"), profile.get("category"),
                     profile.get("tier"), profile.get("study_count", 0),
                     payload, profile.get("_cached_at", time.time())))
            conn.commit()
        return True
    except Exception as e:
        print(f"  [db] put failed ({type(e).__name__}); profile kept in files only")
        return False


def invalidate(slug):
    """Delete a profile. Returns True if a row was removed."""
    if not available():
        return False
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM profiles WHERE slug = %s", (slug,))
                removed = cur.rowcount > 0
            conn.commit()
        return removed
    except Exception:
        return False


def list_cached():
    """All stored slugs."""
    if not available():
        return []
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT slug FROM profiles ORDER BY slug")
                return [r[0] for r in cur.fetchall()]
    except Exception:
        return []


def sync_from_files(cache_dir="cache", verbose=True):
    """
    Load every JSON profile from disk into Postgres.

    This is how the locally-generated catalog reaches the deployed database:
    generate locally (fast, no cost concerns), then push the results up once.
    """
    if not available():
        print("No DATABASE_URL set (or driver missing) — nothing to sync.")
        return 0
    import glob
    internal = {"effect_sizes", "llm_population", "explanations", "appraisals",
                "pubchem", "directions", "outcomes"}
    n = 0
    for path in sorted(glob.glob(os.path.join(cache_dir, "*.json"))):
        slug = os.path.splitext(os.path.basename(path))[0]
        if slug in internal:
            continue
        try:
            profile = json.load(open(path))
        except Exception:
            continue
        if not profile.get("claims"):
            continue
        if put(slug, profile):
            n += 1
            if verbose and n % 25 == 0:
                print(f"  synced {n}...")
    print(f"Synced {n} profiles into Postgres.")
    return n


if __name__ == "__main__":
    import sys
    if not DATABASE_URL:
        print("DATABASE_URL is not set.")
        print("Local:  export DATABASE_URL='postgresql://user:pass@localhost/clarity'")
        print("Render: copy the Internal Database URL from your Postgres instance.")
        sys.exit(1)
    print("driver available:", available())
    if "--sync" in sys.argv:
        sync_from_files()
    else:
        print("stored profiles:", len(list_cached()))
        print("Run with --sync to upload cache/*.json into the database.")
