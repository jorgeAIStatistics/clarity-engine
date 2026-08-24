"""
Clarity Engine — end-to-end runner (v2).

Now you just give it a TOPIC. It:
  1. Checks the cache — instant if already generated ("generating…" becomes real)
  2. If not cached: pulls studies, auto-discovers what outcomes it's studied for,
     grades each, assembles a full profile, and caches it.
  3. Runs with ZERO paid services (PubMed is free; no LLM required).

Usage:
    python run.py "creatine monohydrate"
    python run.py "bpc-157" peptide
    python run.py "ashwagandha" herb --fresh     (ignore cache, regenerate)
"""

import sys
import time
import json
import pubmed
import classify
import grade
import generate
import discover
import cache


def research(topic, category="supplement", use_cache=True, retmax=40, verbose=True):
    # Effect extraction is slow (per-study LLM calls) and low-yield (abstracts
    # rarely report effects). It can be disabled for fast catalog pre-warming
    # via CLARITY_NO_EFFECTS=1, keeping the cheap+valuable population classifier.
    import os as _os
    extract_effects = _os.environ.get("CLARITY_NO_EFFECTS", "") != "1"
    if use_cache:
        cached = cache.get(topic)
        if cached:
            if verbose:
                print("[cache hit] served instantly", file=sys.stderr)
            return cached

    if verbose:
        print(f"[generating] pulling studies for '{topic}'...", file=sys.stderr)

    # SINGLE RETRIEVAL: fetch a large pool once, then partition it across
    # outcomes locally. Previously each outcome ran its own PubMed search
    # (~15 round-trips, ~55s/compound) and the results overlapped heavily.
    pool_size = max(retmax, 150)
    _t0 = time.time()
    base_studies = classify.classify_all(
        pubmed.search_topic(topic, None, retmax=pool_size))
    if verbose:
        print(f"[generating] retrieved {len(base_studies)} studies "
              f"in {time.time() - _t0:.1f}s", file=sys.stderr)

    # Discover outcomes from RELEVANT, INTERVENTION studies only.
    # PubMed's relevance ranking returns papers where the compound appears
    # incidentally — beta-alanine shows up in microbiome and metabolic
    # literature as a metabolite. Those papers voted for "gut / digestion" and
    # "blood sugar", which were then graded on the scraps that survived the
    # relevance filter (37 and 27 papers rejected respectively). Filtering
    # BEFORE discovery means the outcome list reflects what the compound is
    # actually studied FOR.
    # LLM population pass runs ONCE over the deduplicated pool.
    # It used to run inside each outcome, so a study appearing under three
    # outcomes was classified three times — with a 100-study pool that meant
    # 100+ LLM calls per compound and was the single largest cost. Resolving up
    # front means every outcome inherits an already-classified study.
    try:
        import llm_classify
        _seen_pmids = set()
        _unique = []
        for _st in base_studies:
            _pid = _st.get("pmid")
            if _pid and _pid in _seen_pmids:
                continue
            if _pid:
                _seen_pmids.add(_pid)
            _unique.append(_st)
        # Independent, I/O-bound calls — 60 of them sequentially cost ~14s.
        from concurrent.futures import ThreadPoolExecutor as _TPE
        with _TPE(max_workers=8) as _pool:
            base_studies = list(_pool.map(llm_classify.resolve, _unique))
        if verbose:
            print(f"[generating] population-resolved {len(base_studies)} unique studies",
                  file=sys.stderr)
    except Exception as e:
        print(f"[generating] population pass skipped: {type(e).__name__}", file=sys.stderr)

    _all_studies = list(base_studies)
    _before = len(base_studies)
    _screened = [x for x in base_studies
                 if classify.is_relevant(x, topic)
                 and classify.is_intervention_study(x, topic)
                 and not classify.is_analytical_paper(x)]
    if len(_screened) >= 5:
        base_studies = _screened
        if verbose and _before != len(base_studies):
            print(f"[generating] screened {_before} -> {len(base_studies)} "
                  f"relevant intervention studies for outcome discovery",
                  file=sys.stderr)
    elif verbose:
        print(f"[generating] only {len(_screened)} studies survived screening; "
              f"discovering outcomes from all {_before} to avoid an empty profile",
              file=sys.stderr)

    if not base_studies:
        profile = {
            "name": topic, "category": category, "overall_score": 0, "tier": "Unknown",
            "study_count": 0, "claims": [],
            "honesty_note": "No studies found for this topic. It may be too new, too niche, or spelled differently.",
            "generated_by": "clarity-engine-v2", "reviewed_by": "auto",
        }
        return cache.put(topic, profile) if use_cache else profile

    # Keep the full pool for outcome partitioning; `base_studies` may have been
    # narrowed to screened studies for discovery purposes.
    study_pool = _all_studies
    outcomes = discover.discover(base_studies, topic)
    if verbose:
        print(f"[generating] outcomes found: {', '.join(outcomes)}", file=sys.stderr)

    # PARALLEL: each outcome is an independent pipeline of I/O-bound PubMed and
    # LLM calls. Run sequentially this took ~5 min/compound (11 hours for the
    # catalog). The PubMed throttle is lock-guarded, so concurrency respects
    # NCBI's rate limit rather than triggering the stalls we fixed earlier.
    def _process_outcome(outcome):
        # Select from the pool we already have — no additional PubMed call.
        studies = [s for s in study_pool if discover.assign_to_outcome(s, outcome)]
        if len(studies) < 8:
            # Genuinely sparse in the pool: one targeted search as a top-up,
            # so an outcome isn't graded on two papers when more exist.
            extra = classify.classify_all(
                pubmed.search_topic(topic, outcome, retmax=retmax))
            seen = {s.get("pmid") for s in studies}
            studies += [s for s in extra if s.get("pmid") not in seen]
        if not studies:
            studies = list(study_pool)
        # Drop narrative reviews / non-studies (keyword- or LLM-flagged).
        primary = [s for s in studies if not s.get("is_review")]
        n_reviews = len(studies) - len(primary)

        # RELEVANCE: a paper that never names the compound cannot be evidence
        # about it. PubMed relevance search returns token matches (TB-500 was
        # graded partly on tuberculosis and generic peptide-methods papers).
        before = len(primary)
        primary = [s for s in primary if classify.is_relevant(s, topic)]
        n_offtopic = before - len(primary)

        # INTERVENTION vs BIOMARKER: studies that merely MEASURE endogenous
        # levels are not evidence that administering the compound helps. Keep
        # them out of the human-evidence layer (MOTS-c was graded Moderate on
        # observational biomarker studies where nobody received anything).
        before = len(primary)
        primary = [s for s in primary if classify.is_intervention_study(s, topic)]
        n_biomarker = before - len(primary)

        # ANALYTICAL/ASSAY PAPERS: detection and quantification methodology
        # names the compound but says nothing about whether it works.
        before = len(primary)
        primary = [s for s in primary if not classify.is_analytical_paper(s)]
        n_analytical = before - len(primary)

        if verbose and (n_offtopic or n_biomarker or n_analytical):
            print(f"    [{outcome}] dropped {n_offtopic} off-topic, "
                  f"{n_biomarker} non-intervention, {n_analytical} assay-method")
        if not primary:
            g = grade.grade_outcome([])
            return {"outcome": outcome, "studies": [], "grade": g,
                    "reviews_excluded": n_reviews,
                    "effects": [], "pooled": {"verified": None,
                    "exploratory": None, "note": "no primary studies"},
                    "pooled_from_meta": []}
        g = grade.grade_outcome(primary)

        # Effect-size extraction. Two paths:
        #  A) POOLED (preferred): from meta-analysis/systematic-review abstracts,
        #     which state their headline pooled effect explicitly. This is the
        #     synthesis experts already did — highest yield, most trustworthy.
        #  B) per-study: fallback for individual studies (abstracts rarely report
        #     effect sizes, so this yields little — kept for the rare cases).
        # No-op / not_reported when API unavailable; cached per pmid+outcome.
        effects_list = []
        pooled_effects = []
        pooled = {"verified": None, "exploratory": None, "note": "extractor not run"}
        if extract_effects:
          try:
            import effects as effects_mod
            for s in primary:
                pmid = s.get("pmid")
                if not pmid:
                    continue
                is_meta = s.get("design") in ("meta_analysis", "systematic_review")
                if is_meta:
                    pe = effects_mod.extract_pooled(pmid, s.get("title", ""),
                                                    s.get("abstract", ""), outcome)
                    pe["pmid"] = pmid
                    pe["population"] = s.get("population")
                    if pe.get("status") in ("verified", "derived"):
                        pooled_effects.append(pe)
                        effects_list.append(pe)
                        continue
                # fall through to per-study extraction if not a usable pooled result
                ef = effects_mod.extract(pmid, s.get("title", ""),
                                         s.get("abstract", ""), outcome)
                ef["pmid"] = pmid
                ef["population"] = s.get("population")
                effects_list.append(ef)
            pooled = effects_mod.pool([e for e in effects_list
                                       if e.get("source") != "meta_analysis_pooled"])
          except Exception:
            pass

        # DIRECTION: does the evidence actually favour the treatment? A large
        # literature concluding "no effect" must not read as Strong evidence it
        # works (the Ginkgo / Chromium / BCAA problem). One-way only: this can
        # flag a null result or cap a tier, never promote one.
        try:
            import direction as _direction
            # apply_direction only ever lowers a tier, so running it on an
            # already-low tier costs an API call and changes nothing.
            if g.get("tier") not in ("Strong", "Moderate"):
                raise StopIteration
            _dir = _direction.extract_direction(topic, outcome, primary)
            if _dir and _dir.get("direction") != "unclear":
                g = _direction.apply_direction(g, _dir)
                if verbose and _dir["direction"] in ("null_result", "favors_control"):
                    print(f"    [{outcome}] direction: {_dir['direction']} — "
                          f"tier adjusted")
        except StopIteration:
            pass
        except Exception as e:
            print(f"    [{outcome}] direction step failed: {type(e).__name__}")

        return {"outcome": outcome, "studies": primary, "grade": g,
                "reviews_excluded": n_reviews,
                "effects": effects_list, "pooled": pooled,
                "pooled_from_meta": pooled_effects}

    from concurrent.futures import ThreadPoolExecutor
    workers = min(4, max(1, len(outcomes)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_process_outcome, outcomes))
    # Preserve discovery order — it ranks outcomes by centrality.
    claim_bundles = [r for r in results if r]

    overall = grade.overall_score([cb["grade"] for cb in claim_bundles])
    profile = generate.build_profile(topic, category, claim_bundles, overall)
    return cache.put(topic, profile) if use_cache else profile


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if not args:
        print('Usage: python run.py "<topic>" [category] [--fresh]')
        sys.exit(1)
    topic = args[0]
    category = args[1] if len(args) > 1 else "supplement"

    # --fresh must INVALIDATE then regenerate-and-save. Previously it only set
    # use_cache=False, which skipped the write too, so the fixed profile was
    # never persisted — and the next run served the stale one again. Validating
    # engine changes against a cached profile silently wasted several rounds.
    if "--fresh" in flags:
        removed = cache.invalidate(topic)
        print(f"[fresh] cache {'cleared' if removed else 'was empty'} for '{topic}'",
              file=sys.stderr)

    profile = research(topic, category, use_cache=True)
    print(json.dumps(profile, indent=2))
