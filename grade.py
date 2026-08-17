"""
Stage 4 — GRADE the evidence for one outcome (claim).

This is the MOAT. It implements the GRADE framework's logic:
  - RCTs start at "high" certainty; observational starts "low".
  - Downgrade across 5 domains: risk of bias, inconsistency, indirectness,
    imprecision, publication bias.
  - Result maps to one of four certainty levels -> your 0-100 score + tier.

This is a defensible, transparent v1. A biostatistician (you) refines the
downgrade heuristics over time — that refinement IS the competitive advantage.
Reference: GRADE Working Group (adopted by Cochrane, WHO, NICE, CDC).
"""

# GRADE's four certainty levels -> your tiers + score bands (midpoints used).
CERTAINTY = {
    "high":     {"tier": "Strong",      "band": (80, 100), "score": 90},
    "moderate": {"tier": "Moderate",    "band": (60, 79),  "score": 70},
    "low":      {"tier": "Emerging",    "band": (35, 59),  "score": 47},
    "very_low": {"tier": "Preliminary", "band": (0, 34),   "score": 22},
}
_ORDER = ["very_low", "low", "moderate", "high"]


# Precision thresholds. These are HONEST heuristics, not measured CIs — the
# engine reads abstracts, it does not compute effect sizes. So the rule is:
# unmeasured precision is treated as a real limitation, never as reassurance.
# (Refine these with your biostatistics judgment; they are deliberately explicit.)
_ADEQUATE_TOTAL_N = 400   # rough floor below which imprecision is a concern
_MODERATE_TOTAL_N = 100   # below this, imprecision is serious


# ---------------------------------------------------------------------------
# THREE-LAYER SCORING (holistic but honest)
#
# Every compound is scored on three stacked layers:
#   1. mechanistic  — is there a plausible theoretical pathway?  (cheap, low ceiling)
#   2. preclinical  — how strong/reproducible is cell + animal data?  (HARD-CAPPED)
#   3. human        — does it hold in people?  (the GRADE certainty above)
#
# The RULE that keeps this honest: the human layer GATES the overall score.
# Mechanistic and preclinical strength fill in UNDERNEATH that ceiling — they can
# never lift the headline past what human evidence supports. This is because
# preclinical strength is a weak predictor of human success (most compounds that
# work in animals fail in humans), so animal data must never substitute for proof.
#
# _PRECLINICAL_CAP is the single most important judgment call here: the highest
# overall score a compound with GREAT theory + GREAT animal data but ZERO human
# evidence may receive. It sits inside the "Emerging" band on purpose — visibly
# promising, explicitly unproven. THIS IS A BIOSTATS JUDGMENT CALL — move it and
# re-run; do not let it drift up into the human-proven bands.
_PRECLINICAL_CAP = 55          # ceiling for animal/cell-only compounds (top of Emerging)
_MECHANISTIC_CAP = 30          # ceiling for "plausible pathway, ~nothing else"
_PRECLINICAL_STRONG_N = 3      # animal/cell studies for "strong" preclinical signal


def grade_outcome(studies_for_outcome):
    """
    Given the studies addressing ONE outcome, return a GRADE assessment.
    studies_for_outcome: list of classified study dicts (from classify.py).

    Design note: every path that reaches "high" must EARN it by clearing each
    GRADE domain. The absence of a measurable problem is NOT the same as the
    presence of good evidence — so unmeasured precision caps at moderate rather
    than upgrading to high. This is the anti-hype core.
    """
    if not studies_for_outcome:
        return _assess("very_low", ["No studies found for this outcome."], 0)

    # 1) Baseline by best available design ---------------------------------
    best_rank = max(s.get("design_rank", 0) for s in studies_for_outcome)
    has_human = any(s.get("population") == "human" for s in studies_for_outcome)
    only_animal = all(s.get("population") == "animal" for s in studies_for_outcome)

    if best_rank >= 5:            # RCT or higher (incl. meta-analysis of RCTs)
        level_idx = _ORDER.index("high")
    elif best_rank >= 3:          # non-randomised trials / observational
        level_idx = _ORDER.index("moderate")
    else:                          # case reports / animal / unknown
        level_idx = _ORDER.index("very_low")

    n_studies = len(studies_for_outcome)
    # total_n is best-effort from abstract regex; treat 0 as "unknown", not "small".
    measured_n = [s.get("sample_size") for s in studies_for_outcome if s.get("sample_size")]
    total_n = sum(measured_n)
    have_precision_signal = len(measured_n) > 0

    reasons = []
    downgrades = 0

    def downgrade(msg):
        nonlocal level_idx, downgrades
        level_idx = max(0, level_idx - 1)
        downgrades += 1
        reasons.append(msg)

    # 2) Downgrade domains -------------------------------------------------

    # (a) Indirectness — animal-only is a hard floor (the BPC-157 lesson).
    if only_animal:
        level_idx = _ORDER.index("very_low")
        reasons.append("Indirectness: evidence is animal-only; does not reliably translate to humans.")
        # Nothing below can rescue animal-only evidence; return early.
        return _assess(_ORDER[level_idx], reasons, n_studies, total_n, best_rank, has_human)
    elif not has_human:
        downgrade("Indirectness: no clearly human-population evidence detected.")

    # (b) Imprecision — the honest version.
    #     - If we could not measure sample size at all, we CANNOT claim precision.
    #       Cap at moderate and flag it, rather than silently passing to high.
    #     - If we could measure it, judge against explicit thresholds.
    if not have_precision_signal:
        if level_idx > _ORDER.index("moderate"):
            level_idx = _ORDER.index("moderate")
        reasons.append("Imprecision: sample sizes could not be verified from the abstracts; "
                       "precision is unconfirmed, so certainty is capped below the top tier.")
    elif total_n < _MODERATE_TOTAL_N:
        downgrade(f"Imprecision: small verified sample (~{total_n} participants across measured studies).")
    elif total_n < _ADEQUATE_TOTAL_N:
        downgrade(f"Imprecision: modest verified sample (~{total_n} participants); effect estimate may be unstable.")

    # (c) Inconsistency — the honest version.
    #     The engine can't read effect DIRECTION from free-text abstracts. But a
    #     META-ANALYSIS *is* a formal consistency assessment someone already did.
    #     So:
    #       - A human meta-analysis (rank 6) with a VERIFIED adequate sample keeps
    #         high certainty; unverified consistency is recorded as a soft note.
    #       - A single study can't be assessed for consistency -> downgrade.
    #       - Several individual studies we merely COUNTED (no pooled analysis) can't
    #         be confirmed to agree -> hold at moderate rather than sail to high.
    is_meta = best_rank >= 6
    adequate_precision = have_precision_signal and total_n >= _ADEQUATE_TOTAL_N

    if n_studies < 2:
        downgrade("Inconsistency: only one study addresses this outcome; consistency cannot be assessed.")
    elif is_meta and has_human and adequate_precision:
        # Earned the top tier: pooled human evidence, adequately powered.
        reasons.append("Consistency: based on a pooled meta-analysis / systematic review "
                       "(formal consistency assessment); effect-direction agreement assumed from the pooled result.")
    elif level_idx >= _ORDER.index("high"):
        # Multiple individual studies, no pooled analysis, agreement unverified.
        level_idx = _ORDER.index("moderate")
        reasons.append("Inconsistency: several studies exist but no pooled analysis confirms they agree; "
                       "held at moderate pending review.")

    # 3) Floor: human evidence should not collapse below "low" from stacked
    #    heuristic downgrades alone. Real GRADE rarely drops RCT evidence two
    #    full levels without specific, serious reasons.
    if has_human and best_rank >= 5 and level_idx < _ORDER.index("low"):
        level_idx = _ORDER.index("low")
        reasons.append("Floor applied: human trial evidence retained at least 'emerging' "
                       "certainty absent a specific serious flaw.")

    if not reasons:
        # Only reachable when nothing at all was flagged — which, given the
        # imprecision/inconsistency checks above, means a genuinely clean,
        # multi-study, adequately-powered human body of evidence.
        reasons.append("No serious concerns detected across assessed GRADE domains.")

    level = _ORDER[level_idx]
    return _assess(level, reasons, n_studies, total_n, best_rank, has_human)


def score_layers(studies_for_outcome, human_assessment):
    """
    Produce the three-layer view for one outcome, with a HARD CAP so that
    preclinical/mechanistic strength can never lift the headline past the ceiling
    the human evidence supports.

    Returns a dict with per-layer scores and a gated `overall`.
    """
    if not studies_for_outcome:
        return {"mechanistic": 0, "preclinical": 0, "human": 0,
                "overall": 0, "ceiling": 0,
                "note": "No studies for this outcome."}

    human_studies = [s for s in studies_for_outcome if s.get("population") == "human"]
    animal_studies = [s for s in studies_for_outcome if s.get("population") == "animal"]
    n_animal = len(animal_studies)

    # Layer 1 — mechanistic: any real study implies a studied, plausible pathway.
    # Necessary but unimpressive, so it is deliberately cheap and low-ceilinged.
    mechanistic = min(_MECHANISTIC_CAP, 15 + 5 * min(len(studies_for_outcome), 3))

    # Layer 2 — preclinical: graded on volume/reproducibility of non-human data,
    # then HARD-CAPPED. No amount of animal data crosses into the proven bands.
    if n_animal == 0:
        preclinical = 0
    else:
        preclinical = min(_PRECLINICAL_CAP,
                          25 + 10 * min(n_animal, _PRECLINICAL_STRONG_N))

    # Layer 3 — human: reuse the GRADE certainty score already computed.
    human = human_assessment["score"] if human_studies else 0

    # ---- The gate ---------------------------------------------------------
    # If there is NO human evidence, the overall is capped at the preclinical
    # ceiling — however good theory/animal data are. If there IS human evidence,
    # the human certainty score sets the ceiling and becomes the headline; the
    # lower layers are shown for context but cannot raise it.
    if not human_studies:
        ceiling = _PRECLINICAL_CAP
        overall = min(max(mechanistic, preclinical), ceiling)
        note = ("No human evidence: score is capped in the 'promising but unproven' "
                "range regardless of how strong the theory or animal data are.")
    else:
        ceiling = human
        overall = human   # human certainty governs; lower layers are context only
        note = "Human evidence present: human certainty sets the overall score."

    return {
        "mechanistic": mechanistic,
        "preclinical": preclinical,
        "human": human,
        "overall": overall,
        "ceiling": ceiling,
        "n_human_studies": len(human_studies),
        "n_animal_studies": n_animal,
        "note": note,
    }


def _assess(level, reasons, n_studies, total_n=0, best_rank=0, has_human=False):
    c = CERTAINTY[level]
    return {
        "certainty": level,
        "tier": c["tier"],
        "score": c["score"],
        "score_band": c["band"],
        "reasons": reasons,
        "n_studies": n_studies,
        "total_participants": total_n,
        "best_design_rank": best_rank,
        "has_human_evidence": has_human,
    }


def overall_score(claim_assessments):
    """
    Derive a substance-level 0-100 score from its graded claims.

    Gated: the headline is anchored on the best HUMAN-supported outcome. A
    substance with only animal/mechanistic support (no human evidence on any
    outcome) is capped in the promising-but-unproven range — it cannot reach the
    established bands on preclinical strength alone. This mirrors the per-outcome
    gate and is what keeps a peptide from showing a reassuring headline number.
    """
    if not claim_assessments:
        return 0, "Preliminary"

    human_claims = [a for a in claim_assessments if a.get("has_human_evidence")]

    if human_claims:
        best = max(human_claims, key=lambda a: a["score"])
        score = best["score"]
        solid = [a for a in human_claims if a["score"] >= 70]
        if len(solid) >= 2:
            score = min(score + 3 * (len(solid) - 1), 95)
    else:
        # No human evidence on ANY outcome -> capped, promising-but-unproven.
        score = min(_PRECLINICAL_CAP, max((a["score"] for a in claim_assessments), default=0))

    for lvl in CERTAINTY.values():
        lo, hi = lvl["band"]
        if lo <= score <= hi:
            return score, lvl["tier"]
    return score, "Preliminary"


if __name__ == "__main__":
    import pubmed, classify
    studies = classify.classify_all(pubmed._parse_articles(open("tests/sample_pubmed.xml").read()))

    # Cluster: all three sample studies address "strength"
    strength_studies = studies  # in real pipeline these are grouped by outcome
    human_only = [s for s in studies if s["population"] != "animal"]
    animal_only = [s for s in studies if s["population"] == "animal"]

    print("=== Outcome: STRENGTH (human RCT + meta-analysis present) ===")
    a1 = grade_outcome(human_only)
    print(f"  {a1['tier']} ({a1['score']}/100), certainty={a1['certainty']}")
    for r in a1["reasons"]:
        print(f"   - {r}")

    print("\n=== Outcome: MUSCLE FIBER (animal-only evidence) ===")
    a2 = grade_outcome(animal_only)
    print(f"  {a2['tier']} ({a2['score']}/100), certainty={a2['certainty']}")
    for r in a2["reasons"]:
        print(f"   - {r}")

    print("\n=== Overall substance score ===")
    score, tier = overall_score([a1, a2])
    print(f"  {tier} ({score}/100)")
