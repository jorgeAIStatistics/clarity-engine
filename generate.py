"""
Stage 5 — Generate the profile.

CRITICAL DESIGN: the LLM is only allowed to write PROSE from the graded,
structured evidence we hand it. It never invents facts, scores, or studies.
Every claim carries the PMIDs it came from (citation binding). If a claim has
no bound studies, it is dropped — not softened. This is the anti-fabrication core.

The LLM call is isolated in `_write_prose()`. To run WITHOUT any paid API,
leave LLM_API_KEY unset and it uses a deterministic template writer (still honest,
just less fluent). Set LLM_API_KEY + LLM_MODEL to enable real prose.
"""

import os
import json
import re
from datetime import datetime, timezone
import grade as grade_mod

ENGINE_VERSION = os.environ.get("CLARITY_ENGINE_VERSION", "2026.09-launch.2")
PROFILE_SCHEMA_VERSION = 3
RETRIEVAL_VERSION = "pubmed+europepmc-v2"

LLM_API_KEY = os.environ.get("LLM_API_KEY")       # e.g. your Anthropic/OpenAI key
LLM_MODEL = os.environ.get("LLM_MODEL", "")        # e.g. a cheap fast model id


def _study_identity(study):
    """Stable identity for compound-level deduplication across outcomes/sources."""
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


def _unique_evidence_counts(claim_bundles):
    """Count unique papers once across outcomes; outcome memberships remain separate."""
    unique = {}
    memberships = 0
    for cb in claim_bundles:
        for st in cb.get("studies") or []:
            ident = _study_identity(st)
            if not ident:
                continue
            memberships += 1
            # Prefer a record with a known population if duplicate copies differ.
            old = unique.get(ident)
            if old is None or (old.get("population") in (None, "", "unknown") and st.get("population") not in (None, "", "unknown")):
                unique[ident] = st
    vals = list(unique.values())

    def _pop(st):
        return str(st.get("population") or "").strip().lower()

    return {
        "unique": len(vals),
        "human": sum(1 for st in vals if _pop(st) == "human"),
        "animal": sum(1 for st in vals if _pop(st) == "animal"),
        "unlabelled": sum(1 for st in vals if _pop(st) not in ("human", "animal")),
        "memberships": memberships,
        "sources": sorted({str(st.get("retrieved_from") or st.get("source")) for st in vals if (st.get("retrieved_from") or st.get("source"))}),
    }


def _tier_metadata(claims, fallback_tier):
    rank = {"Preliminary": 0, "Emerging": 1, "Moderate": 2, "Strong": 3}
    human = [c for c in claims if (c.get("layers") or {}).get("n_human_studies", 0) > 0]
    candidates = human or claims
    best = max(candidates, key=lambda c: (rank.get(c.get("tier"), -1), (c.get("layers") or {}).get("human", 0), c.get("score", 0)), default=None)
    tiers = sorted({c.get("tier") for c in human if c.get("tier") in rank}, key=lambda t: rank[t])
    spread = (rank[tiers[-1]] - rank[tiers[0]]) if len(tiers) > 1 else 0
    return {
        "best_outcome": best.get("outcome") if best else None,
        "best_tier": best.get("tier") if best else fallback_tier,
        "human_outcome_tiers": tiers,
        # A two-level spread is materially different; vitamins may override this
        # in indications.catalog_meta for classic deficiency-vs-wellness contexts.
        "outcome_dependent": spread >= 2,
    }


def _pick_headline_effect(pooled_from_meta):
    """
    Choose the single best pooled effect to headline an outcome: prefer a
    verified (reported-CI) meta-analytic estimate; among those, prefer the one
    pooling the most studies. Returns None if no usable pooled effect exists —
    in which case the UI shows the certainty view alone (honest: no magnitude
    the synthesis reported that we could extract).
    """
    if not pooled_from_meta:
        return None
    verified = [e for e in pooled_from_meta if e.get("status") == "verified"]
    pool_set = verified or pooled_from_meta
    best = max(pool_set, key=lambda e: (e.get("n_studies_pooled") or 0))
    return {
        "metric": best.get("metric"),
        "value": best.get("value"),
        "ci_low": best.get("ci_low"),
        "ci_high": best.get("ci_high"),
        "ci_estimated": best.get("ci_estimated", False),
        "n_studies_pooled": best.get("n_studies_pooled"),
        "comparator": best.get("comparator"),
        "direction": best.get("direction"),
        "status": best.get("status"),
        "source": "meta_analysis",
        "pmid": best.get("pmid"),
        "quote": best.get("quote"),
    }


def _study_records(studies):
    """
    Compact per-study records for the trials table. Everything here was parsed
    from PubMed or classified upstream — nothing synthesized. Honest-gaps rule:
    sample_size is included ONLY when it was verified from the abstract (None
    otherwise, rendered as an em-dash by the UI, never guessed). Sorted human
    evidence first, then by design strength, then recency.
    """
    _DESIGN_LABEL = {
        "meta_analysis": "Meta-analysis", "systematic_review": "Systematic review",
        "rct": "RCT", "trial": "Clinical trial", "observational": "Observational",
        "case_report": "Case report", "animal": "Animal", "in_vitro": "In vitro",
        "unknown": "Unclassified",
    }
    recs = []
    for s in studies:
        ident = _study_identity(s)
        if not ident:
            continue
        n = s.get("sample_size")
        pmid = str(s.get("pmid") or "").strip() or None
        doi = str(s.get("doi") or "").strip() or None
        epmc_id = str(s.get("epmc_id") or "").strip() or None
        if pmid:
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        elif epmc_id and ":" in epmc_id:
            src, eid = epmc_id.split(":", 1)
            url = f"https://europepmc.org/article/{src.upper()}/{eid}" if eid else None
        elif doi:
            url = f"https://doi.org/{doi}"
        else:
            url = None
        recs.append({
            "id": ident,
            "pmid": pmid,
            "title": (s.get("title") or "").strip()[:160],
            "year": s.get("year") or "",
            "design": _DESIGN_LABEL.get(s.get("design"), "Unclassified"),
            "population": str(s.get("population") or "unknown").strip().lower(),
            "n": int(n) if isinstance(n, (int, float)) and n > 0 else None,
            "doi": doi,
            "epmc_id": epmc_id,
            "url": url,
            "source": s.get("retrieved_from"),
            "is_preprint": bool(s.get("is_preprint")),
            # Ask Clarity needs the actual study text to answer specific questions.
            # Keep a bounded abstract in the profile so retrieval can be local and fast;
            # never synthesize text here. Journal is useful context and also source-derived.
            "abstract": (s.get("abstract") or "").strip()[:3000] or None,
            "journal": (s.get("journal") or "").strip()[:180] or None,
        })
    _rank = {"Meta-analysis": 0, "Systematic review": 1, "RCT": 2, "Clinical trial": 3,
             "Observational": 4, "Case report": 5, "Animal": 6, "In vitro": 7, "Unclassified": 8}
    recs.sort(key=lambda r: (0 if r["population"] == "human" else 1,
                             _rank.get(r["design"], 9),
                             -(int(r["year"]) if r["year"].isdigit() else 0)))
    return recs


def _format_effects(effects_list):
    """
    Shape effects for the profile JSON. Only effects that passed the gate
    (status verified or derived) are surfaced with plot data; not_reported ones
    are counted but carry no drawable values (honest: nothing to plot).
    """
    plottable = []
    n_not_reported = 0
    for e in effects_list:
        if e.get("status") in ("verified", "derived"):
            plottable.append({
                "pmid": e.get("pmid"),
                "metric": e.get("metric"),
                "value": e.get("value"),
                "ci_low": e.get("ci_low"),
                "ci_high": e.get("ci_high"),
                "ci_estimated": e.get("ci_estimated", False),
                "converted": e.get("converted", False),
                "tier": e.get("tier"),           # "solid" | "dashed"
                "status": e.get("status"),
                "comparator": e.get("comparator"),
                "direction": e.get("direction"),
                "quote": e.get("quote"),
            })
        else:
            n_not_reported += 1
    return {"plottable": plottable, "n_not_reported": n_not_reported,
            "n_total": len(effects_list)}


def build_profile(topic, category, claim_bundles, overall):
    """
    claim_bundles: list of dicts, each:
        { "outcome": str, "studies": [classified study dicts], "grade": grade dict }
    overall: (score, tier) tuple
    Returns the profile JSON matching the app's schema.
    """
    score, tier = overall

    claims = []
    for cb in claim_bundles:
        g = cb["grade"]
        # CITATION BINDING: every study that contributes to a claim must carry
        # a stable source identifier. Europe PMC can contain peer-reviewed papers
        # without PMIDs, so DOI/EPMC identifiers are valid citation bindings too.
        study_ids = []
        for st in cb["studies"]:
            if st.get("pmid"):
                study_ids.append(f"PMID:{st['pmid']}")
            elif st.get("doi"):
                study_ids.append(f"DOI:{st['doi']}")
            elif st.get("epmc_id"):
                study_ids.append(f"EPMC:{st['epmc_id']}")
        if not study_ids:
            continue  # anti-fabrication: no source-bound evidence -> claim dropped

        # THREE-LAYER VIEW: mechanistic / preclinical / human, with the human
        # layer gating the overall so animal data can't inflate the headline.
        layers = grade_mod.score_layers(cb["studies"], g)

        claims.append({
            "outcome": cb["outcome"],
            "tier": g["tier"],
            "certainty": g["certainty"],
            "score": g["score"],
            "has_human_evidence": g["has_human_evidence"],
            "n_studies": g["n_studies"],
            "grade_reasons": g["reasons"],
            "direction_status": cb.get("direction_status", "not_assessed"),
            "effect_extraction_status": cb.get("effect_extraction_status", "not_assessed"),
            "preprints_excluded": int(cb.get("preprints_excluded", 0) or 0),
            "layers": {
                "mechanistic": layers["mechanistic"],
                "preclinical": layers["preclinical"],
                "human": layers["human"],
                "overall": layers["overall"],
                "ceiling": layers["ceiling"],
                "n_human_studies": layers.get("n_human_studies", 0),
                "n_animal_studies": layers.get("n_animal_studies", 0),
                "note": layers["note"],
            },
            "study_ids": study_ids,
            "studies": _study_records(cb["studies"]),
            "effects": _format_effects(cb.get("effects", [])),
            "pooled": cb.get("pooled", {"verified": None, "exploratory": None}),
            "headline_effect": _pick_headline_effect(cb.get("pooled_from_meta", [])),
            "summary": _write_prose(topic, cb),  # prose constrained to this evidence
        })

    # Split by the GATED layer score: "established" requires real human evidence
    # clearing moderate. A high preclinical score alone never counts as established.
    established = [c for c in claims
                  if c["layers"]["human"] >= 60 and c["layers"]["n_human_studies"] > 0]
    promising = [c for c in claims
                 if c not in established and c["layers"]["overall"] >= 35]
    emerging = [c for c in claims if c not in established and c not in promising]

    evidence_counts = _unique_evidence_counts(claims)
    tier_meta = _tier_metadata(claims, tier)

    profile = {
        "name": topic,
        "category": category,
        "overall_score": score,
        "tier": tier,
        # Compound-level counts are UNIQUE papers, not the sum of outcome memberships.
        "study_count": evidence_counts["unique"],
        "unique_human_study_count": evidence_counts["human"],
        "unique_animal_study_count": evidence_counts["animal"],
        "unique_unlabelled_study_count": evidence_counts["unlabelled"],
        "outcome_study_memberships": evidence_counts["memberships"],
        "claims": claims,
        "effects_established": [c["outcome"] for c in established],
        "effects_promising": [c["outcome"] for c in promising],
        "effects_emerging": [c["outcome"] for c in emerging],
        "honesty_note": (
            "No outcomes reached the well-established tier — human evidence is limited. "
            "Some outcomes show promising mechanistic or animal data (see 'promising'), "
            "but this is not proof of a human effect."
            if not established else None
        ),
        "generated_by": "clarity-engine",
        "engine_version": ENGINE_VERSION,
        "schema_version": PROFILE_SCHEMA_VERSION,
        "retrieval_version": RETRIEVAL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": evidence_counts["sources"] or ["pubmed", "europe_pmc"],
        "overall_tier_basis": "best_human_supported_outcome",
        "best_outcome": tier_meta["best_outcome"],
        "best_tier": tier_meta["best_tier"],
        "outcome_dependent": tier_meta["outcome_dependent"],
        "human_outcome_tiers": tier_meta["human_outcome_tiers"],
        "reviewed_by": "auto",  # flip to "expert" after your review
    }
    # Grounded explanation (rich prose, efficacy tied to the grades). Cached by
    # compound; costs ~half a cent once, free after. None if no API key.
    # PubChem: hard factual chemistry (formula, weight, IUPAC name, structure).
    # Anchors the "what it is" section with verifiable facts instead of relying
    # entirely on generated prose. None for mixtures (whey, collagen) — honest.
    try:
        import pubchem as _pubchem
        _chem = _pubchem.fetch(topic)
        if _chem:
            profile["chemistry"] = _chem
    except Exception as e:
        print(f"  [generate] pubchem lookup skipped: {type(e).__name__}")

    # Curated, cited PK lives in one backend source of truth. Missing record means
    # the UI omits PK rather than guessing from general model knowledge.
    try:
        import pharmacokinetics as _pk
        _pk_record = _pk.get(topic)
        if _pk_record:
            profile["pharmacokinetics"] = _pk_record
    except Exception as e:
        print(f"  [generate] pharmacokinetics lookup skipped: {type(e).__name__}")

    # Skipped by default during catalog generation: these two calls are ~52% of
    # wall time and the add_explanations.py / add_appraisals.py passes produce
    # them anyway. Set CLARITY_INLINE_PROSE=1 for a single-command full profile.
    _inline_prose = os.environ.get("CLARITY_INLINE_PROSE", "") == "1"
    try:
        if not _inline_prose:
            raise StopIteration
        import explain as _explain
        _ex = _explain.explain(profile)
        if _ex:
            profile["explanation"] = _ex
        else:
            print("  [generate] no explanation attached (see [explain] message above, "
                  "or ANTHROPIC_API_KEY not set)")
    except StopIteration:
        pass
    except Exception as e:
        print(f"  [generate] explanation step failed: {type(e).__name__}: {e}")

    # Critical appraisal — the "how this could be wrong" layer. Adversarial read
    # of the evidence STRUCTURE, grounded in the study records. Never speculative.
    try:
        if not _inline_prose:
            raise StopIteration
        import appraise as _appraise
        _ap = _appraise.appraise(profile)
        if _ap:
            profile["appraisal"] = _ap
    except StopIteration:
        pass
    except Exception as e:
        print(f"  [generate] appraisal step failed: {type(e).__name__}: {e}")

    return profile


def _write_prose(topic, claim_bundle):
    """Deterministic one-line claim summary derived only from the computed grade.

    Richer prose is generated in the separate explanation/appraisal passes. Keeping
    this core summary deterministic prevents a missing/misconfigured LLM provider
    from ever putting placeholder or hallucinated text into a published profile.
    """
    g = claim_bundle["grade"]
    outcome = claim_bundle["outcome"]
    strength = {
        "Strong": "is well-supported by human trials",
        "Moderate": "has moderate human evidence",
        "Emerging": "shows early but unsettled human evidence",
        "Preliminary": "has only preliminary, sparse-human, or preclinical evidence",
    }.get(g.get("tier"), "has limited evidence")
    return f"For {outcome}, {topic} {strength} ({g.get('n_studies', 0)} graded studies)."
