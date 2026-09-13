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
import hashlib

DATABASE_URL = os.environ.get("DATABASE_URL", "")
STORE_ASK_TEXT = os.environ.get("CLARITY_STORE_ASK_TEXT", "0").strip().lower() in {"1", "true", "yes"}
ASK_HASH_SALT = os.environ.get("CLARITY_ASK_HASH_SALT", "").strip()

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

CREATE TABLE IF NOT EXISTS ask_events (
    id                BIGSERIAL PRIMARY KEY,
    compound          TEXT,
    question          TEXT,
    answer            TEXT,
    question_hash     TEXT,
    question_chars    INTEGER DEFAULT 0,
    answer_chars      INTEGER DEFAULT 0,
    grounded          BOOLEAN,
    coverage          TEXT,
    retrieved_studies INTEGER DEFAULT 0,
    mode              TEXT,
    helpful           BOOLEAN,
    created_at        DOUBLE PRECISION NOT NULL
);
ALTER TABLE ask_events ALTER COLUMN question DROP NOT NULL;
ALTER TABLE ask_events ALTER COLUMN answer DROP NOT NULL;
ALTER TABLE ask_events ADD COLUMN IF NOT EXISTS question_hash TEXT;
ALTER TABLE ask_events ADD COLUMN IF NOT EXISTS question_chars INTEGER DEFAULT 0;
ALTER TABLE ask_events ADD COLUMN IF NOT EXISTS answer_chars INTEGER DEFAULT 0;
CREATE INDEX IF NOT EXISTS ask_events_compound_idx ON ask_events (compound);
CREATE INDEX IF NOT EXISTS ask_events_created_idx ON ask_events (created_at);
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


def list_catalog():
    """
    Cheap catalog listing: slug, name, category, tier, study_count for EVERY
    stored profile, from indexed top-level columns (no JSON parsing). This is
    what the landing page loads once so every card shows its REAL grade on
    arrival, instead of "Ungraded" until each is clicked.
    """
    if not available():
        return []
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT slug, name, category, tier, study_count, "
                    "profile->>'best_outcome', profile->>'best_tier', "
                    "profile->>'outcome_dependent', profile->>'overall_tier_basis', "
                    "profile->>'engine_version', profile->>'generated_at', "
                    "profile->>'schema_version' "
                    "FROM profiles ORDER BY slug")
                rows = cur.fetchall()
        return [{"slug": r[0], "name": r[1], "category": r[2],
                 "tier": r[3], "study_count": r[4],
                 "best_outcome": r[5], "best_tier": r[6] or r[3],
                 "outcome_dependent": str(r[7]).lower() == "true",
                 "overall_tier_basis": r[8], "engine_version": r[9],
                 "generated_at": r[10], "schema_version": int(r[11]) if r[11] else None} for r in rows]
    except Exception as e:
        print(f"  [db] list_catalog failed ({type(e).__name__})")
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


def pull_to_files(cache_dir="cache", verbose=True):
    """
    Write every profile FROM Postgres to local cache/*.json.

    The inverse of sync_from_files. Needed when the DB is the source of truth
    (e.g. after local files were cleared) and you want to run a local pass —
    translation, re-explanation — against the full catalog, then sync back up.
    """
    if not available():
        print("No DATABASE_URL set (or driver missing) — nothing to pull.")
        return 0
    os.makedirs(cache_dir, exist_ok=True)
    slugs = list_cached()
    n = 0
    for slug in slugs:
        prof = get(slug, max_age_days=100000)   # ignore age on pull
        if not prof:
            continue
        try:
            with open(os.path.join(cache_dir, f"{slug}.json"), "w") as f:
                json.dump(prof, f, indent=2, ensure_ascii=False)
            n += 1
            if verbose and n % 25 == 0:
                print(f"  pulled {n}...")
        except Exception as e:
            print(f"  [db] could not write {slug}: {type(e).__name__}")
    print(f"Pulled {n} profiles from Postgres into {cache_dir}/.")
    return n


if __name__ == "__main__":
    import sys
    if not DATABASE_URL:
        print("DATABASE_URL is not set.")
        print("Local:  export DATABASE_URL='postgresql://user:pass@localhost/clarity'")
        print("Render: copy the External Database URL from your Postgres instance.")
        sys.exit(1)
    print("driver available:", available())
    if "--sync" in sys.argv:
        sync_from_files()
    elif "--pull" in sys.argv:
        pull_to_files()
    else:
        print("stored profiles:", len(list_cached()))
        print("Run with --sync to upload cache/*.json into the database,")
        print("or --pull to download the database into cache/*.json.")


def log_ask_event(compound, question, answer, grounded=True, coverage=None, retrieved_studies=0, mode=None):
    """Store Ask Clarity quality metadata. Raw free text is OFF by default.

    Health questions can contain sensitive personal details even without an
    account or explicit name. Production therefore stores only a one-way query
    hash, lengths, retrieval metadata and optional helpful/not-helpful feedback
    unless CLARITY_STORE_ASK_TEXT=1 is deliberately enabled.
    """
    if not available():
        return None
    q = str(question or "")[:1200]
    a = str(answer or "")[:6000]
    normalized_q = " ".join(q.lower().split())
    # Salted one-way fingerprint is useful for duplicate-query rates without
    # making common health questions reversible through a simple lookup table.
    fingerprint_input = f"{ASK_HASH_SALT}\0{normalized_q}" if ASK_HASH_SALT else normalized_q
    qhash = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()[:24] if q else None
    raw_q = q if STORE_ASK_TEXT else None
    raw_a = a if STORE_ASK_TEXT else None
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO ask_events
                       (compound, question, answer, question_hash, question_chars, answer_chars,
                        grounded, coverage, retrieved_studies, mode, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (compound, raw_q, raw_a, qhash, len(q), len(a), bool(grounded),
                     coverage, int(retrieved_studies or 0), mode, time.time()))
                row = cur.fetchone()
            conn.commit()
        return int(row[0]) if row else None
    except Exception as e:
        print(f"  [db] ask event log failed ({type(e).__name__})")
        return None


def set_ask_feedback(event_id, helpful):
    """Attach helpful/not-helpful feedback to a prior privacy-minimized Ask Clarity event."""
    if not available():
        return False
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute("UPDATE ask_events SET helpful=%s WHERE id=%s", (bool(helpful), int(event_id)))
                ok = cur.rowcount > 0
            conn.commit()
        return ok
    except Exception:
        return False


def iter_profiles():
    """Stream indexing inputs through one server-side cursor and connection."""
    if not available():return
    with _connect() as conn:
        _ensure_schema(conn)
        with conn.cursor(name='clarity_profile_index') as cur:
            cur.execute('SELECT slug, profile FROM profiles ORDER BY slug')
            while True:
                row=cur.fetchone()
                if row is None:break
                slug,profile=row
                yield slug,profile if isinstance(profile,dict) else json.loads(profile)
