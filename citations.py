"""
Citation enrichment — per-study citation counts from NIH's iCite API.

WHY: the weighted scorer needs a citation count per study to reward
heavily-cited research and stop uncited papers from inflating scores. PubMed's
E-utilities don't return citation counts, so this fills the gap. iCite is the
NIH's own citation service (Open Citation Collection) — free, no API key, same
NCBI family as PubMed and PubChem, so attribution stays consistent.

API: https://icite.od.nih.gov/api/pubs?pmids=<comma-list>&format=json
  - up to 200 PMIDs per request (we batch at 180 to stay safe)
  - returns citation_count, relative_citation_ratio, human/animal flags per PMID
  - the /api/pubs/<id> path form rejects comma lists; the ?pmids= query form works

Degrades silently: no network / no match -> citation stays None, and the scorer
treats missing citations as a neutral 1.0 multiplier (never a penalty). Cached
by PMID (including misses) so a compound re-run costs nothing.
"""

import os
import json
import time

import requests

_BASE = "https://icite.od.nih.gov/api/pubs"
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "citations.json")
_BATCH = 180
_MIN_INTERVAL = 0.25          # be a good citizen; iCite is generous but polite wins
_last_call = [0.0]


def _throttle():
    dt = time.time() - _last_call[0]
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    _last_call[0] = time.time()


def _load_cache():
    try:
        with open(_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(c):
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, "w") as f:
            json.dump(c, f, indent=2)
    except Exception:
        pass


def _fetch_batch(pmids):
    """One iCite call for up to _BATCH PMIDs. Returns {pmid: record} or {}."""
    _throttle()
    try:
        r = requests.get(
            _BASE,
            params={"pmids": ",".join(pmids), "format": "json"},
            timeout=20,
            headers={"User-Agent": "clarity-engine (research/education)"},
        )
        if r.status_code != 200:
            return {}
        rows = r.json().get("data", []) or []
        out = {}
        for row in rows:
            pid = str(row.get("pmid"))
            if not pid:
                continue
            cc = row.get("citation_count")
            out[pid] = {
                "citation_count": int(cc) if isinstance(cc, (int, float)) else None,
                "rcr": row.get("relative_citation_ratio"),
                "is_human": row.get("human"),
                "is_clinical": row.get("is_clinical"),
                "source": "iCite",
            }
        return out
    except Exception:
        return {}


def fetch_many(pmids):
    """
    Return {pmid: citation_record} for a list of PMIDs. Cache-first; only
    uncached PMIDs hit the network, batched. Missing/failed PMIDs are cached as
    None so we don't re-query them every run.
    """
    pmids = [str(p) for p in pmids if p]
    if not pmids:
        return {}

    cache = _load_cache()
    result = {}
    need = []
    for p in pmids:
        if p in cache:
            result[p] = cache[p]        # may be None (cached miss)
        else:
            need.append(p)

    # Batch the uncached ones.
    for i in range(0, len(need), _BATCH):
        batch = need[i:i + _BATCH]
        got = _fetch_batch(batch)
        for p in batch:
            rec = got.get(p)             # None if iCite had no record
            cache[p] = rec
            result[p] = rec

    if need:
        _save_cache(cache)
    return result


def citation_count(pmid):
    """Convenience: citation count for one PMID, or None."""
    rec = fetch_many([pmid]).get(str(pmid))
    return rec.get("citation_count") if rec else None


def enrich_studies(studies):
    """
    Attach citation_count (and rcr) to each study dict in place, keyed by pmid.
    Studies without a pmid, or with no iCite record, get citation_count=None —
    the scorer treats that as a neutral multiplier, never a penalty. Returns the
    same list for convenience.
    """
    pmids = [s.get("pmid") for s in studies if s.get("pmid")]
    if not pmids:
        return studies
    recs = fetch_many(pmids)
    for s in studies:
        rec = recs.get(str(s.get("pmid"))) if s.get("pmid") else None
        if rec:
            s["citation_count"] = rec.get("citation_count")
            s["rcr"] = rec.get("rcr")
        else:
            s.setdefault("citation_count", None)
    return studies


if __name__ == "__main__":
    import sys
    # Smoke test with a couple of well-known PMIDs (RCR metric paper + a review).
    test = sys.argv[1:] or ["27599104", "23456789", "99999999999"]
    recs = fetch_many(test)
    for p in test:
        r = recs.get(p)
        if r:
            print(f"PMID {p}: {r['citation_count']} citations  "
                  f"(RCR {r.get('rcr')}, human={r.get('is_human')})")
        else:
            print(f"PMID {p}: no iCite record")
