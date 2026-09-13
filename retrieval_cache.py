"""
Retrieval cache — persistent, provenance-tracked cache of the raw study lists
pulled from the literature sources (PubMed, Europe PMC).

WHY: the same compound's retrieval was re-fetched from every source on every
regeneration. Studies don't change minute to minute, so that's wasted API calls
and latency. This caches the merged, deduplicated study list per compound and
serves it back until it's genuinely stale.

CACHE vs. FRESHNESS (per spec — these are deliberately separate):
  - CACHE: opening a compound again NEVER re-hits APIs. The cached dataset is
    served immediately, always, if present.
  - FRESHNESS: each cached entry carries a TTL (default 30 days). Past the TTL
    the entry is MARKED STALE — but stale data is still served (we don't block
    the user). A caller can act on staleness (e.g. trigger a background refresh)
    without this layer forcing a blocking re-fetch.
  - force_refresh: an explicit path (regeneration/admin) that bypasses the cache
    and re-queries the sources.

PROVENANCE (per spec): every entry records
  - per-source `last_queried` timestamps (when each API was last hit)
  - `dataset_changed_at` (when the retrieved set last actually changed, by
    content fingerprint — reopening that returns identical studies does NOT bump
    this, so you can tell "re-queried" from "actually changed")
  - `fingerprint` of the study set (drives the retrieval-skip in run.py)

STALE-WHILE-REVALIDATE READY: `get()` returns (data, meta) where meta.stale
tells the caller whether a background refresh is warranted. Wiring an async
refresher later needs no change to this layer.
"""

import os
import json
import time
import hashlib
import threading

_CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "retrieval.json")
_DEFAULT_TTL_DAYS = float(os.environ.get("CLARITY_RETRIEVAL_TTL_DAYS", "30"))
_lock = threading.Lock()


def _now():
    return time.time()


def _load():
    try:
        with open(_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(cache):
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        tmp = _CACHE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _CACHE_PATH)   # atomic
    except Exception as e:
        print(f"  [retrieval_cache] save failed: {type(e).__name__}")


def _key(topic, outcome=None):
    o = (outcome or "").lower().strip()
    return f"{(topic or '').lower().strip()}::{o}"


def fingerprint(studies):
    """Content hash of a study set — identity-stable ids, sorted, so the same
    papers always hash the same regardless of retrieval order."""
    ids = sorted(
        (str(s.get("doi") or s.get("pmid") or s.get("epmc_id") or s.get("title") or ""))
        for s in (studies or [])
    )
    return hashlib.sha1("||".join(ids).encode("utf-8")).hexdigest()[:16]


def get(topic, outcome=None, ttl_days=None):
    """
    Return (studies, meta) or (None, None) on miss.
    meta = {stale: bool, age_days: float, sources: {name: last_queried},
            dataset_changed_at: ts, fingerprint: str}
    Always returns cached data if present — staleness is a FLAG, not a block.
    """
    ttl = _DEFAULT_TTL_DAYS if ttl_days is None else ttl_days
    with _lock:
        entry = _load().get(_key(topic, outcome))
    if not entry:
        return None, None
    age_days = (_now() - entry.get("cached_at", 0)) / 86400.0
    meta = {
        "stale": age_days > ttl,
        "age_days": round(age_days, 2),
        "sources": entry.get("sources", {}),
        "dataset_changed_at": entry.get("dataset_changed_at"),
        "fingerprint": entry.get("fingerprint"),
    }
    return entry.get("studies", []), meta


def put(topic, outcome, studies, source_times):
    """
    Store a retrieved study set with provenance.
    source_times: {source_name: last_queried_ts} for each API actually hit.
    dataset_changed_at only advances if the fingerprint changed from what was
    stored — so provenance distinguishes "re-queried" from "actually changed".
    """
    fp = fingerprint(studies)
    with _lock:
        cache = _load()
        prev = cache.get(_key(topic, outcome)) or {}
        changed = prev.get("fingerprint") != fp
        cache[_key(topic, outcome)] = {
            "studies": studies,
            "cached_at": _now(),
            "fingerprint": fp,
            "dataset_changed_at": _now() if changed else prev.get("dataset_changed_at", _now()),
            "sources": {**prev.get("sources", {}), **(source_times or {})},
            "n_studies": len(studies),
        }
        _save(cache)
    return fp


if __name__ == "__main__":
    # Smoke test (no network): put then get.
    demo = [{"pmid": "1", "title": "A"}, {"doi": "10.1/x", "title": "B"}]
    put("demo-compound", None, demo, {"pubmed": _now(), "europe_pmc": _now()})
    data, meta = get("demo-compound")
    print("cached studies:", len(data), "| meta:", json.dumps(meta, indent=2))
    print("fingerprint stable:", fingerprint(demo) == fingerprint(list(reversed(demo))))
