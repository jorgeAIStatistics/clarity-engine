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
import grade as grade_mod

LLM_API_KEY = os.environ.get("LLM_API_KEY")       # e.g. your Anthropic/OpenAI key
LLM_MODEL = os.environ.get("LLM_MODEL", "")        # e.g. a cheap fast model id


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
        if not s.get("pmid"):
            continue
        n = s.get("sample_size")
        recs.append({
            "pmid": str(s["pmid"]),
            "title": (s.get("title") or "").strip()[:160],
            "year": s.get("year") or "",
            "design": _DESIGN_LABEL.get(s.get("design"), "Unclassified"),
            "population": s.get("population") or "unknown",
            "n": int(n) if isinstance(n, (int, float)) and n > 0 else None,
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
        # CITATION BINDING: only include PMIDs that actually exist for this claim.
        pmids = [s["pmid"] for s in cb["studies"] if s.get("pmid")]
        if not pmids:
            continue  # anti-fabrication: no evidence -> claim dropped entirely

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
            "study_ids": [f"PMID:{p}" for p in pmids],
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

    total_studies = sum(c["n_studies"] for c in claims)

    profile = {
        "name": topic,
        "category": category,
        "overall_score": score,
        "tier": tier,
        "study_count": total_studies,
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
        "generated_by": "clarity-engine-v2",
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
    """
    Write a one-line, plain-language summary of ONE claim, grounded ONLY in the
    provided studies. Uses the LLM if configured, else a safe template.
    """
    g = claim_bundle["grade"]
    outcome = claim_bundle["outcome"]

    if not (LLM_API_KEY and LLM_MODEL):
        # Deterministic, honest fallback — no API needed.
        strength = {
            "Strong": "is well-supported by human trials",
            "Moderate": "has moderate human evidence",
            "Emerging": "shows early but unsettled evidence",
            "Preliminary": "has only preliminary or animal evidence",
        }.get(g["tier"], "has limited evidence")
        return f"For {outcome}, {topic} {strength} ({g['n_studies']} studies)."

    # --- Real LLM path (grounded prompt). Pseudocode-safe; wire to your provider. ---
    evidence_blob = json.dumps([
        {"pmid": s["pmid"], "title": s["title"], "design": s["design"],
         "population": s["population"], "year": s["year"]}
        for s in claim_bundle["studies"]
    ], indent=2)

    system = (
        "You are a scientific summarizer. Write ONE plain-language sentence about "
        "the effect of the topic on the given outcome. Use ONLY the provided studies. "
        "Do NOT invent numbers, effects, or citations. If evidence is weak, say so plainly."
    )
    user = (
        f"Topic: {topic}\nOutcome: {outcome}\n"
        f"GRADE certainty: {g['certainty']} ({g['tier']})\n"
        f"Studies (the ONLY allowed source):\n{evidence_blob}\n\n"
        "Write the one-sentence summary."
    )
    return _call_llm(system, user)


def _call_llm(system, user):
    """
    Isolated LLM call. Fill in for your provider. Example shape for Anthropic:

        import anthropic
        client = anthropic.Anthropic(api_key=LLM_API_KEY)
        msg = client.messages.create(
            model=LLM_MODEL, max_tokens=120,
            system=system, messages=[{"role": "user", "content": user}])
        return msg.content[0].text.strip()

    Kept as a stub so the engine runs with zero paid dependencies by default.
    """
    return "[LLM prose would appear here — configure LLM_API_KEY + LLM_MODEL]"
