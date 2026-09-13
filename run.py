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
import re
import pubmed
import classify
import grade
import generate
import discover
import cache
import indications


# --- Weighted-score support ------------------------------------------------
# Map each study's DESIGN to a scorer tier. Per the agreed rules:
#   Strong      : meta-analysis, systematic review, or a large RCT (verified N>=100)
#   Moderate    : standard/small RCT (N<100 or unknown), clinical trial, cohort/observational
#   Emerging    : animal (in vivo), pilot human
#   Preliminary : in vitro, case report, computational
def _study_to_tier(s):
    design = (s.get("design") or "").lower()
    pop = (s.get("population") or "").lower()
    n = s.get("sample_size")
    n = int(n) if isinstance(n, (int, float)) and n > 0 else None

    if design in ("meta_analysis", "systematic_review"):
        return "Strong"
    if design == "rct":
        # Large/high-powered human RCTs are Strong; smaller or unknown-N ones Moderate.
        return "Strong" if (n is not None and n >= 100) else "Moderate"
    if design in ("trial", "observational"):
        return "Moderate"
    if design == "animal" or pop == "animal":
        return "Emerging"
    if design in ("in_vitro", "case_report"):
        return "Preliminary"
    # Unclassified human work is treated as Emerging (pilot-human bucket);
    # anything else falls to Preliminary. Never invents a higher tier.
    return "Emerging" if pop == "human" else "Preliminary"


def _outcome_direction(g):
    """
    Normalize the outcome's direction to the scorer's vocabulary. This is now
    REPORTED alongside the evidence-strength score (not used to gate it), so a
    well-studied negative finding scores high with a 'worsens' tag instead of 0.
    """
    d = g.get("direction")
    if d in ("null_result", "no_significant_difference"):
        return "null_result"
    if d == "favors_control":
        return "favors_control"
    if d in ("favors_treatment", "positive", "statistically_significant_benefit"):
        return "favors_treatment"
    if g.get("null_result") is True:
        return "null_result"
    return "unclear"


def _cap_strong_when_direction_unverified(g, status):
    """Top-tier efficacy claims require a completed direction check."""
    if g.get("tier") != "Strong" or status == "assessed":
        return g
    out = dict(g)
    out["tier"] = "Moderate"
    out["certainty"] = "moderate"
    out["score"] = min(float(out.get("score") or 70), 70)
    out["score_band"] = (60, 79)
    reasons = list(out.get("reasons") or [])
    reasons.append("Direction verification was not conclusive; the top tier is withheld until the evidence direction can be confirmed.")
    out["reasons"] = reasons
    return out


def _stable_study_key(study):
    """Stable publication identity used before grading and storage.

    PMID is preferred, then DOI, Europe PMC ID, then a normalized title. This
    mirrors the profile/audit identity rules so the same paper cannot count
    twice merely because it arrived from multiple retrieval paths.
    """
    pmid = str(study.get("pmid") or "").strip()
    if pmid:
        return f"pmid:{pmid}"
    doi = str(study.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    epmc = str(study.get("epmc_id") or "").strip().lower()
    if epmc:
        return f"epmc:{epmc}"
    title = re.sub(r"[^a-z0-9]+", " ", str(study.get("title") or "").lower()).strip()
    return f"title:{title}" if title else None


def _dedup_studies(studies):
    """Deduplicate one outcome's evidence before grading.

    Duplicate source records are merged conservatively: the first record wins,
    while missing/unknown metadata may be filled from a later copy. Population
    labels are normalized so ``Human``/`` human `` cannot escape the human gate.
    Records with no usable identity are retained; the launch audit will flag them
    rather than silently deleting evidence.
    """
    out = []
    positions = {}

    def clean(rec):
        rec = dict(rec)
        design = str(rec.get("design") or "").strip().lower()
        pop = str(rec.get("population") or "").strip().lower()
        # Cell-culture work is mechanistic/preclinical even when the cells are
        # human-derived. Never let "human osteocytes" or similar wording turn an
        # in-vitro experiment into direct human clinical evidence.
        if design == "in_vitro":
            pop = "in_vitro"
        elif design == "animal":
            pop = "animal"
        if pop:
            rec["population"] = pop
        return rec

    for raw in studies or []:
        st = clean(raw)
        key = _stable_study_key(st)
        if not key:
            out.append(st)
            continue

        if key not in positions:
            positions[key] = len(out)
            out.append(st)
            continue

        old = out[positions[key]]
        merged = dict(old)
        for field, value in st.items():
            old_value = merged.get(field)
            old_missing = old_value is None or old_value == "" or old_value == "unknown" or old_value == [] or old_value == {}
            new_known = value is not None and value != "" and value != "unknown" and value != [] and value != {}
            if old_missing and new_known:
                merged[field] = value
        out[positions[key]] = merged

    return out


def _build_study_objs(primary, g):
    """
    Build score.Study objects for one outcome's studies. Since direction is now
    decoupled from the score (reported separately), every study is marked as
    agreeing with the outcome's consensus — the score measures evidence STRENGTH,
    and the consistency term in the CI reflects agreement, which at the
    outcome-direction level is uniform. Returns (study_objs, direction).
    """
    import score as _score
    direction = _outcome_direction(g)
    objs = []
    for s in primary:
        tier = _study_to_tier(s)
        n = s.get("sample_size")
        n = int(n) if isinstance(n, (int, float)) and n > 0 else None
        c = s.get("citation_count")
        c = int(c) if isinstance(c, (int, float)) and c >= 0 else None
        objs.append(_score.Study(tier=tier, is_supportive=True,
                                 sample_size=n, citation_count=c))
    return objs, direction


def _compound_aggregate(claim_bundles):
    """
    Compound-level score: score-weighted average of outcome scores
    (sum(sq)/sum), with a broad-but-shallow penalty. No compound-level CI —
    outcome CIs are meaningful; a combined band would imply false rigor.
    """
    scores = [cb["score"]["final_score"] for cb in claim_bundles
              if cb.get("score") and cb["score"].get("final_score") is not None]
    if not scores:
        return None
    denom = sum(scores)
    agg = (sum(v * v for v in scores) / denom) if denom > 0 else 0.0
    fragmented = len(scores) >= 4 and max(scores) < 50
    if fragmented:
        agg *= 0.9
    return {
        "score": round(agg, 1),
        "n_outcomes_scored": len(scores),
        "best_outcome_score": round(max(scores), 1),
        "fragmentation_penalty_applied": fragmented,
        "method": "score-weighted average (sum of squares / sum); "
                  "broad-but-shallow penalty when >=4 outcomes and best <50; "
                  "no compound-level CI by design",
    }



def _topic_terms(topic):
    raw = str(topic or "").lower().strip()
    # Some catalog labels are dangerously ambiguous as bare acronyms. VIP is a
    # peptide here (vasoactive intestinal peptide), but "VIP" also appears in
    # unrelated care programs, chemotherapy regimens, and generic prose. For
    # these entries, relevance/intervention checks must use the biomedical name.
    ambiguous = {
        "vip": ["vasoactive intestinal peptide", "vasoactive intestinal polypeptide"],
    }
    if raw in ambiguous:
        terms = list(ambiguous[raw])
    else:
        terms = [raw]
        try:
            terms += indications.search_aliases(topic)
        except Exception:
            pass
    out = []
    for t in terms:
        t = " ".join(str(t or "").lower().split())
        if t and t not in out:
            out.append(t)
    return out


def _is_relevant(study, topic):
    """Original relevance check + recognized naming variants for vitamins."""
    try:
        if classify.is_relevant(study, topic):
            return True
    except Exception:
        pass
    blob = f"{study.get('title','')} {study.get('abstract','')}".lower()
    return any(term in blob for term in _topic_terms(topic))


def _is_intervention(study, topic):
    """Try the catalog name and factual aliases; never promotes a non-intervention."""
    for term in _topic_terms(topic):
        try:
            if classify.is_intervention_study(study, term):
                return True
        except Exception:
            continue
    return False


def research(topic, category="supplement", use_cache=True, retmax=40, verbose=True, force_refresh=False):
    # Effect extraction is slow (per-study LLM calls) and low-yield (abstracts
    # rarely report effects). It can be disabled for fast catalog pre-warming
    # via CLARITY_NO_EFFECTS=1, keeping the cheap+valuable population classifier.
    import os as _os
    extract_effects = _os.environ.get("CLARITY_NO_EFFECTS", "") != "1"
    if use_cache and not force_refresh:
        cached = cache.get(topic)
        if cached:
            current = (cached.get("engine_version") == generate.ENGINE_VERSION
                       and int(cached.get("schema_version") or 0) >= generate.PROFILE_SCHEMA_VERSION)
            if current:
                if verbose:
                    print("[cache hit] served instantly", file=sys.stderr)
                return cached
            if verbose:
                print("[cache stale] engine/schema changed; regenerating without deleting the old profile", file=sys.stderr)
            # Preserve the old profile until a complete replacement has been built
            # and cache.set() succeeds. A transient source/provider failure must
            # never turn a stale-but-readable profile into missing data.

    if verbose:
        print(f"[generating] pulling studies for '{topic}'...", file=sys.stderr)

    # SINGLE RETRIEVAL: fetch a large pool once, then partition it across
    # outcomes locally. Previously each outcome ran its own PubMed search
    # (~15 round-trips, ~55s/compound) and the results overlapped heavily.
    pool_size = max(retmax, 150)
    _t0 = time.time()
    _timing = {}
    # MULTI-SOURCE, CONCURRENT, CACHED: PubMed + Europe PMC fire in parallel and
    # the merged set is cached with provenance. force_refresh (from --fresh /
    # use_cache=False) bypasses the retrieval cache. All classify/relevance/
    # intervention filters below still run — wider pool, same quality gate.
    _force = bool(force_refresh or (not use_cache))
    try:
        import sources
        _raw = sources.retrieve(topic, None, retmax=pool_size,
                                force_refresh=_force, timing=_timing)
    except Exception as e:
        print(f"[generating] multi-source failed ({type(e).__name__}); PubMed only")
        _raw = pubmed.search_topic(topic, None, retmax=pool_size)
    _t_retrieval = time.time() - _t0
    _t_norm0 = time.time()
    base_studies = classify.classify_all(_raw)
    _timing["normalization_s"] = round(time.time() - _t_norm0, 3)
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

    # Normalize/deduplicate the resolved pool once so every outcome starts from
    # the same publication identity and population label.
    base_studies = _dedup_studies(base_studies)
    _all_studies = list(base_studies)
    _before = len(base_studies)

    # Canonical population by publication identity. Targeted outcome top-ups are
    # allowed to rediscover a paper, but not to reclassify the same PMID as human
    # in one outcome and animal in another.
    _population_by_identity = {
        _stable_study_key(st): str(st.get("population") or "unknown").strip().lower()
        for st in _all_studies if _stable_study_key(st)
    }
    _screened = [x for x in base_studies
                 if _is_relevant(x, topic)
                 and _is_intervention(x, topic)
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
            "study_count": 0, "unique_human_study_count": 0, "unique_animal_study_count": 0,
            "unique_unlabelled_study_count": 0, "claims": [],
            "honesty_note": "No studies found for this topic. It may be too new, too niche, or spelled differently.",
            "generated_by": "clarity-engine", "engine_version": generate.ENGINE_VERSION,
            "schema_version": generate.PROFILE_SCHEMA_VERSION, "retrieval_version": generate.RETRIEVAL_VERSION,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sources": ["pubmed", "europe_pmc"],
            "overall_tier_basis": "best_human_supported_outcome", "reviewed_by": "auto",
        }
        return cache.put(topic, profile) if use_cache else profile

    # Keep the full pool for outcome partitioning; `base_studies` may have been
    # narrowed to screened studies for discovery purposes.
    study_pool = _all_studies
    discovered_outcomes = discover.discover(base_studies, topic)
    outcomes = indications.merge_outcomes(topic, category, discovered_outcomes, max_outcomes=5)
    if verbose:
        print(f"[generating] outcomes found: {', '.join(outcomes)}", file=sys.stderr)

    # PARALLEL: each outcome is an independent pipeline of I/O-bound PubMed and
    # LLM calls. Run sequentially this took ~5 min/compound (11 hours for the
    # catalog). The PubMed throttle is lock-guarded, so concurrency respects
    # NCBI's rate limit rather than triggering the stalls we fixed earlier.
    def _process_outcome(outcome):
        # Select from the pool we already have — no additional PubMed call.
        # Deduplicate immediately because PubMed/Europe PMC and targeted top-ups
        # can return the same paper through different retrieval paths.
        studies = _dedup_studies(
            [s for s in study_pool if discover.assign_to_outcome(s, outcome)]
        )
        if len(studies) < 8:
            # Genuinely sparse in the pool: one targeted multi-source search as a
            # top-up, so an outcome isn't graded on two papers when more exist.
            try:
                import sources as _sources
                extra = classify.classify_all(_sources.retrieve(topic, outcome, retmax=retmax, force_refresh=force_refresh))
            except Exception:
                extra = classify.classify_all(pubmed.search_topic(topic, outcome, retmax=retmax))

            # Targeted top-ups must go through the SAME population resolver as the
            # base pool. Previously a PMID could be LLM-resolved as animal in the
            # base pool but heuristically labelled human when rediscovered here.
            extra = _dedup_studies(extra)
            try:
                import llm_classify as _llm_topup
                from concurrent.futures import ThreadPoolExecutor as _TopupPool
                with _TopupPool(max_workers=min(8, max(1, len(extra)))) as _tp:
                    extra = list(_tp.map(_llm_topup.resolve, extra))
                extra = _dedup_studies(extra)
            except Exception as e:
                if verbose:
                    print(f"    [{outcome}] top-up population resolution skipped: {type(e).__name__}",
                          file=sys.stderr)

            # If the same publication already existed in the base pool, that
            # resolved label is canonical for this run. This prevents cross-outcome
            # human/animal conflicts for one PMID.
            harmonized = []
            for _st in extra:
                _st = dict(_st)
                _key = _stable_study_key(_st)
                if _key and _key in _population_by_identity:
                    _st["population"] = _population_by_identity[_key]
                elif _key:
                    _population_by_identity[_key] = str(_st.get("population") or "unknown").strip().lower()
                harmonized.append(_st)
            extra = _dedup_studies(harmonized)

            # One identity rule for both the existing pool and the top-up. This
            # also removes duplicates *within* the top-up itself.
            studies = _dedup_studies(studies + extra)
        if not studies:
            # Canonical indication seeds must never be graded from an unrelated
            # whole-compound fallback. No direct evidence means an empty claim.
            if indications.is_canonical_outcome(topic, category, outcome):
                studies = []
            else:
                studies = _dedup_studies(list(study_pool))
        # Drop narrative reviews / non-studies (keyword- or LLM-flagged).
        primary = [s for s in studies if not s.get("is_review")]
        n_reviews = len(studies) - len(primary)

        # RELEVANCE: a paper that never names the compound cannot be evidence
        # about it. PubMed relevance search returns token matches (TB-500 was
        # graded partly on tuberculosis and generic peptide-methods papers).
        before = len(primary)
        primary = [s for s in primary if _is_relevant(s, topic)]
        n_offtopic = before - len(primary)

        # INTERVENTION vs BIOMARKER: studies that merely MEASURE endogenous
        # levels are not evidence that administering the compound helps. Keep
        # them out of the human-evidence layer (MOTS-c was graded Moderate on
        # observational biomarker studies where nobody received anything).
        before = len(primary)
        primary = [s for s in primary if _is_intervention(s, topic)]
        n_biomarker = before - len(primary)

        # ANALYTICAL/ASSAY PAPERS: detection and quantification methodology
        # names the compound but says nothing about whether it works.
        before = len(primary)
        primary = [s for s in primary if not classify.is_analytical_paper(s)]
        n_analytical = before - len(primary)

        # PREPRINT POLICY FOR PUBLIC GRADES: Europe PMC preprints broaden discovery,
        # but non-peer-reviewed records do not contribute to tier promotion.
        # Keep the count as provenance so the UI/methodology can say what was excluded.
        before = len(primary)
        primary = [s for s in primary if not s.get("is_preprint")]
        n_preprints = before - len(primary)

        # FINAL PRE-GRADE DEDUP: the grade, direction check, effect extraction,
        # citation score, stored study table, and headline counts must all see
        # each publication at most once for this outcome.
        before_dedup = len(primary)
        primary = _dedup_studies(primary)
        n_duplicates = before_dedup - len(primary)

        if verbose and (n_offtopic or n_biomarker or n_analytical or n_preprints or n_duplicates):
            print(f"    [{outcome}] dropped {n_offtopic} off-topic, "
                  f"{n_biomarker} non-intervention, {n_analytical} assay-method, "
                  f"{n_preprints} preprint, {n_duplicates} duplicate")
        if not primary:
            g = grade.grade_outcome([])
            return {"outcome": outcome, "studies": [], "grade": g,
                    "reviews_excluded": n_reviews, "preprints_excluded": n_preprints,
                    "direction_status": "not_assessed", "effect_extraction_status": "not_assessed",
                    "effects": [], "pooled": {"verified": None,
                    "exploratory": None, "note": "no peer-reviewed primary studies"},
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
        effect_extraction_status = "not_requested" if not extract_effects else "unavailable"
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
            effect_extraction_status = "assessed"
          except Exception as e:
            effect_extraction_status = "failed"
            pooled["note"] = f"effect extraction failed: {type(e).__name__}"

        # DIRECTION: does the evidence actually favour the treatment? A large
        # literature concluding "no effect" must not read as Strong evidence it
        # works (the Ginkgo / Chromium / BCAA problem). One-way only: this can
        # flag a null result or cap a tier, never promote one.
        direction_status = "not_required"
        try:
            import direction as _direction
            # Direction is required before a top-tier efficacy claim can be published.
            if g.get("tier") not in ("Strong", "Moderate"):
                raise StopIteration
            direction_status = "unavailable"
            _dir = _direction.extract_direction(topic, outcome, primary)
            if _dir and _dir.get("direction") != "unclear":
                direction_status = "assessed"
                g = _direction.apply_direction(g, _dir)
                if verbose and _dir["direction"] in ("null_result", "favors_control"):
                    print(f"    [{outcome}] direction: {_dir['direction']} — tier adjusted")
            elif _dir:
                direction_status = "unclear"
        except StopIteration:
            pass
        except Exception as e:
            direction_status = "failed"
            print(f"    [{outcome}] direction step failed: {type(e).__name__}")
        g = _cap_strong_when_direction_unverified(g, direction_status)

        # WEIGHTED SCORE (0-100 + 95% CI). Supplements the tier — never replaces
        # it. Citations come from iCite (free); missing N/citations default to a
        # neutral 1.0 multiplier, never a penalty. is_supportive is taken at the
        # OUTCOME level from direction (per-study direction isn't extracted), with
        # missing-direction studies excluded from the consistency ratio.
        outcome_score = None
        try:
            import citations as _citations
            import score as _score
            _citations.enrich_studies(primary)          # attaches citation_count in place
            _study_objs, _direction = _build_study_objs(primary, g)
            if _study_objs:
                outcome_score = _score.calculate_compound_score(
                    _study_objs, single_source_bias=(len(primary) == 1),
                    direction=_direction)
        except Exception as e:
            print(f"    [{outcome}] scoring skipped: {type(e).__name__}: {e}")

        return {"outcome": outcome, "studies": primary, "grade": g,
                "reviews_excluded": n_reviews, "preprints_excluded": n_preprints,
                "direction_status": direction_status,
                "effect_extraction_status": effect_extraction_status,
                "effects": effects_list, "pooled": pooled,
                "pooled_from_meta": pooled_effects,
                "score": outcome_score}

    from concurrent.futures import ThreadPoolExecutor
    workers = min(4, max(1, len(outcomes)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_process_outcome, outcomes))
    # Preserve discovery order — it ranks outcomes by centrality.
    claim_bundles = [r for r in results if r]

    _t_grade0 = time.time()
    overall = grade.overall_score([cb["grade"] for cb in claim_bundles])
    profile = generate.build_profile(topic, category, claim_bundles, overall)
    _canon = indications.canonical_outcomes(topic, category)
    if _canon:
        profile["canonical_outcomes_checked"] = _canon
        profile["outcome_discovery_mode"] = "canonical+discovered"
    _timing["grading_s"] = round(time.time() - _t_grade0, 3)

    # --- Timing summary (per the benchmark spec) ---
    if verbose:
        tm = _timing
        print(f"[timing] {topic}:", file=sys.stderr)
        print(f"[timing]   cache_hit         = {tm.get('cache_hit')}"
              + ("  (stale)" if tm.get("stale") else ""), file=sys.stderr)
        print(f"[timing]   pubmed_s          = {tm.get('pubmed_s','—')}", file=sys.stderr)
        print(f"[timing]   europepmc_s       = {tm.get('europepmc_s','—')}", file=sys.stderr)
        print(f"[timing]   retrieval_total_s = {round(_t_retrieval,3)}", file=sys.stderr)
        print(f"[timing]   normalization_s   = {tm.get('normalization_s','—')}", file=sys.stderr)
        print(f"[timing]   grading_s         = {tm.get('grading_s','—')}", file=sys.stderr)
        print(f"[timing]   api_requests      = {tm.get('n_api_requests',0)}", file=sys.stderr)
        print(f"[timing]   unique_studies    = {tm.get('n_studies','—')}", file=sys.stderr)
    profile["_timing"] = _timing

    # Attach the weighted 0-100 scores: per-outcome onto each claim, plus the
    # compound aggregate. These SUPPLEMENT the tiers (grade.py still owns tiers);
    # they don't feed back into grading.
    try:
        _by_outcome = {cb["outcome"]: cb.get("score") for cb in claim_bundles}
        for _claim in profile.get("claims", []):
            _sc = _by_outcome.get(_claim.get("outcome"))
            if _sc:
                _claim["weighted_score"] = _sc
        _agg = _compound_aggregate(claim_bundles)
        if _agg:
            profile["weighted_score"] = _agg
    except Exception as e:
        print(f"[generating] score attach skipped: {type(e).__name__}: {e}")

    return cache.put(topic, profile) if use_cache else profile


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if not args:
        print('Usage: python run.py "<topic>" [category] [--fresh]')
        sys.exit(1)
    topic = args[0]
    category = args[1] if len(args) > 1 else "supplement"

    # --fresh bypasses BOTH the finished-profile cache and the literature
    # retrieval cache. The old profile is left intact until the new one finishes,
    # then cache.put atomically replaces it — a failed re-grade cannot erase data.
    fresh = "--fresh" in flags
    if fresh:
        print(f"[fresh] forcing PubMed + Europe PMC refresh for '{topic}'", file=sys.stderr)

    profile = research(topic, category, use_cache=True, force_refresh=fresh)
    print(json.dumps(profile, indent=2))
