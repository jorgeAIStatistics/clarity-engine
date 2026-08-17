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
import json
import pubmed
import classify
import grade
import generate
import discover
import cache


def research(topic, category="supplement", use_cache=True, retmax=40, verbose=True):
    if use_cache:
        cached = cache.get(topic)
        if cached:
            if verbose:
                print("[cache hit] served instantly", file=sys.stderr)
            return cached

    if verbose:
        print(f"[generating] pulling studies for '{topic}'...", file=sys.stderr)

    base_studies = classify.classify_all(pubmed.search_topic(topic, None, retmax=retmax))
    if not base_studies:
        profile = {
            "name": topic, "category": category, "overall_score": 0, "tier": "Unknown",
            "study_count": 0, "claims": [],
            "honesty_note": "No studies found for this topic. It may be too new, too niche, or spelled differently.",
            "generated_by": "clarity-engine-v2", "reviewed_by": "auto",
        }
        return cache.put(topic, profile) if use_cache else profile

    outcomes = discover.discover_outcomes(base_studies)
    if verbose:
        print(f"[generating] outcomes found: {', '.join(outcomes)}", file=sys.stderr)

    claim_bundles = []
    for outcome in outcomes:
        studies = classify.classify_all(pubmed.search_topic(topic, outcome, retmax=retmax))
        if not studies:
            studies = [s for s in base_studies]
        # LLM last-mile pass: resolve ONLY the low-confidence studies (keyword
        # rules unsure or conflicted). No-op when ANTHROPIC_API_KEY is unset, so
        # the engine still runs fully LLM-free if you want. Cached by PMID.
        try:
            import llm_classify
            studies = [llm_classify.resolve(s) for s in studies]
        except Exception:
            pass  # any failure -> keep keyword classifications
        # Drop narrative reviews / non-studies (keyword- or LLM-flagged).
        primary = [s for s in studies if not s.get("is_review")]
        n_reviews = len(studies) - len(primary)
        if not primary:
            g = grade.grade_outcome([])
            claim_bundles.append({"outcome": outcome, "studies": [], "grade": g,
                                  "reviews_excluded": n_reviews,
                                  "effects": [], "pooled": {"verified": None,
                                  "exploratory": None, "note": "no primary studies"}})
            continue
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

        claim_bundles.append({"outcome": outcome, "studies": primary, "grade": g,
                              "reviews_excluded": n_reviews,
                              "effects": effects_list, "pooled": pooled,
                              "pooled_from_meta": pooled_effects})

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
    use_cache = "--fresh" not in flags
    profile = research(topic, category, use_cache=use_cache)
    print(json.dumps(profile, indent=2))
