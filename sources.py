"""
Multi-source retrieval merge + dedup.

Combines results from several literature sources (PubMed, Europe PMC — more can
be added) into ONE deduplicated study list for the grading pipeline. The point
is broader COVERAGE without double-counting: the same paper appears in PubMed and
Europe PMC under different ids, so we must merge them into a single record, not
grade it twice.

DEDUP KEY (in priority order):
  1. DOI (normalized lowercase) — the strongest cross-source identifier.
  2. PMID — when both sources carry it.
  3. Normalized title (lowercased, punctuation/space-stripped) — last resort for
     records missing DOI and PMID (e.g. some preprints).

MERGE RULE: when the same paper comes from two sources, keep the record with the
most information (longest abstract, then most fields), and union useful signals
(carry over cited_by, doi, is_preprint if either source has them).

HONESTY: dedup NEVER inflates counts — if anything it reduces them, which is
correct. Preprint flags and citation counts are preserved so downstream grading
can weight/flag appropriately. Falls back gracefully: if a source errors, the
others still return.
"""

import re


def _norm_title(t):
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def _key(study):
    doi = (study.get("doi") or "").strip().lower()
    if doi:
        return ("doi", doi)
    pmid = str(study.get("pmid") or "").strip()
    if pmid:
        return ("pmid", pmid)
    nt = _norm_title(study.get("title"))
    if nt:
        return ("title", nt)
    return None


def _richer(a, b):
    """Return whichever record carries more information."""
    la = len(a.get("abstract") or "")
    lb = len(b.get("abstract") or "")
    if la != lb:
        return a if la > lb else b
    fa = sum(1 for v in a.values() if v)
    fb = sum(1 for v in b.values() if v)
    return a if fa >= fb else b


def _merge_pair(a, b):
    """Merge two records of the same paper: richer base, union of signals."""
    base = dict(_richer(a, b))
    other = b if base is a else a
    # union useful signals
    if not base.get("doi") and other.get("doi"):
        base["doi"] = other["doi"]
    if not base.get("pmid") and other.get("pmid"):
        base["pmid"] = other["pmid"]
    # citation count: take the max seen (sources lag differently)
    cbs = [x.get("cited_by") for x in (a, b) if isinstance(x.get("cited_by"), int)]
    if cbs:
        base["cited_by"] = max(cbs)
    # preprint: it's a preprint only if BOTH agree it isn't peer-reviewed-indexed;
    # if either source has it as a real published record, prefer that.
    base["is_preprint"] = bool(a.get("is_preprint")) and bool(b.get("is_preprint"))
    # provenance: record which sources it came from
    srcs = set()
    for x in (a, b):
        rf = x.get("retrieved_from")
        if rf:
            srcs.add(rf)
    base["retrieved_from"] = ",".join(sorted(srcs)) if srcs else base.get("retrieved_from")
    # union publication types
    pts = []
    for x in (a, b):
        for p in (x.get("publication_types") or []):
            if p not in pts:
                pts.append(p)
    if pts:
        base["publication_types"] = pts
    return base


def merge(*source_lists):
    """
    Merge any number of study lists (each a list of study dicts) into one
    deduplicated list. Records without any usable key are kept as-is (can't be
    deduped, but shouldn't be dropped).
    """
    merged = {}
    unkeyable = []
    for lst in source_lists:
        for study in (lst or []):
            k = _key(study)
            if k is None:
                unkeyable.append(study)
                continue
            if k in merged:
                merged[k] = _merge_pair(merged[k], study)
            else:
                merged[k] = dict(study)
    return list(merged.values()) + unkeyable


def retrieve(topic, outcome=None, retmax=60, use_europepmc=True,
             force_refresh=False, ttl_days=None, timing=None):
    """
    Pull from all enabled sources CONCURRENTLY and return one merged, deduplicated
    study list. Cache-first: a cached retrieval is served without hitting APIs
    unless force_refresh=True. Staleness is flagged (see retrieval_cache), never
    blocks the user.

    Args:
      force_refresh: bypass cache, re-query sources (regeneration/admin path).
      timing: optional dict; if passed, per-stage latencies are recorded into it
              (pubmed_s, europepmc_s, retrieval_total_s, cache_hit, n_api_requests).

    PubMed and Europe PMC are independent, so they run in parallel. Each source's
    own throttle/backoff still applies, so concurrency respects API limits.
    """
    t = timing if timing is not None else {}
    t.setdefault("n_api_requests", 0)

    # --- CACHE-FIRST -------------------------------------------------------
    if not force_refresh:
        cached, meta = None, None
        try:
            import retrieval_cache
            cached, meta = retrieval_cache.get(topic, outcome, ttl_days=ttl_days)
        except Exception:
            pass
        if cached is not None:
            t["cache_hit"] = True
            t["retrieval_total_s"] = 0.0
            t["stale"] = bool(meta and meta.get("stale"))
            # Stale is a flag for a future background refresher — we still serve
            # the cached data immediately (stale-while-revalidate ready).
            return cached

    t["cache_hit"] = False

    # --- CONCURRENT SOURCE FETCH ------------------------------------------
    from concurrent.futures import ThreadPoolExecutor
    import time as _time

    def _pubmed():
        s = _time.time()
        try:
            import pubmed
            r = pubmed.search_topic(topic, outcome, retmax=retmax)
        except Exception as e:
            print(f"  [sources] pubmed failed: {type(e).__name__}: {e}")
            r = []
        t["pubmed_s"] = round(_time.time() - s, 3)
        for x in r:
            x.setdefault("retrieved_from", "pubmed")
        return r

    def _epmc():
        if not use_europepmc:
            t["europepmc_s"] = 0.0
            return []
        s = _time.time()
        try:
            import europepmc
            r = europepmc.search_topic(topic, outcome, retmax=retmax)
        except Exception as e:
            print(f"  [sources] europepmc failed: {type(e).__name__}: {e}")
            r = []
        t["europepmc_s"] = round(_time.time() - s, 3)
        return r

    _t0 = _time.time()
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_pm = pool.submit(_pubmed)
        f_ep = pool.submit(_epmc)
        pm, ep = f_pm.result(), f_ep.result()
    lists = [pm, ep]
    t["n_api_requests"] = t.get("n_api_requests", 0) + 2

    merged = merge(*lists)
    t["retrieval_total_s"] = round(_time.time() - _t0, 3)
    t["n_studies"] = len(merged)

    # --- WRITE CACHE WITH PROVENANCE --------------------------------------
    try:
        import retrieval_cache
        retrieval_cache.put(topic, outcome, merged, {
            "pubmed": _time.time() if pm else None,
            "europe_pmc": _time.time() if (use_europepmc and ep) else None,
        })
    except Exception:
        pass

    return merged


if __name__ == "__main__":
    import sys, time as _t
    topic = sys.argv[1] if len(sys.argv) > 1 else "tb-500"
    outcome = sys.argv[2] if len(sys.argv) > 2 else None
    force = "--fresh" in sys.argv

    timing = {}
    _s = _t.time()
    res = retrieve(topic, outcome, retmax=60, force_refresh=force, timing=timing)
    wall = _t.time() - _s

    n_pre = sum(1 for s in res if s.get("is_preprint"))
    srcs = {}
    for s in res:
        srcs[s.get("retrieved_from", "?")] = srcs.get(s.get("retrieved_from", "?"), 0) + 1
    print(f"\n=== RETRIEVAL BENCHMARK: '{topic}'"
          + (f" / '{outcome}'" if outcome else "") + " ===")
    print(f"  cache_hit         : {timing.get('cache_hit')}"
          + ("  (stale)" if timing.get("stale") else ""))
    print(f"  pubmed_s          : {timing.get('pubmed_s', '—')}")
    print(f"  europepmc_s       : {timing.get('europepmc_s', '—')}")
    print(f"  retrieval_total_s : {timing.get('retrieval_total_s')}")
    print(f"  wall_s            : {round(wall, 3)}")
    print(f"  api_requests      : {timing.get('n_api_requests', 0)}")
    print(f"  unique_studies    : {len(res)}  (preprints: {n_pre})")
    print(f"  by_source         : {srcs}")
    print("  (run twice — second run should be cache_hit=True, ~0s, 0 api_requests)")
