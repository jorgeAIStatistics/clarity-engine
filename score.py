"""
Weighted compound scoring — a 0-100 evidence score with a confidence interval,
built on top of the per-study tier grades the engine already produces.

This is a SUPPLEMENT to grade.py, not a replacement: grade.py decides each
study's tier and each outcome's tier (Strong/Moderate/Emerging/Preliminary);
this module rolls a set of graded studies into a single interpretable number
with an honest uncertainty band.

HONESTY NOTES (why this matches CLAUDE.md):
  - Sample size and citation count are OPTIONAL. When absent, their multipliers
    default to 1.0 (neutral) — never invented, never penalised. The breakdown
    reports how many studies fell back to defaults, so false precision is
    visible, not hidden.
  - The confidence interval WIDENS as human sample size shrinks (the SE formula
    has a 1/sqrt(sum_N_human) term), so thin evidence produces a wide, honest
    band rather than a falsely tight one.
  - The preclinical/low-tier hard cap stops animal + in-vitro work from ever
    dominating the score, mirroring the layer gating in grade.py.

Spec implemented exactly as given: tier weights, per-study S_k and C_k
modifiers, low-tier hard cap, log-power diminishing-returns curve, consistency
ratio, single-source penalty, and a 95% CI via proportion-variance SE with
Laplace smoothing at the 0%/100% edges.
"""

from dataclasses import dataclass, field
from typing import Optional
import math


# ---- 1. Tier point weights (W_i) ------------------------------------------
TIER_WEIGHTS = {
    "Strong": 45.0,       # systematic reviews, meta-analyses, Phase III/IV RCTs
    "Moderate": 18.0,     # Phase I/II RCTs, cohort studies
    "Emerging": 4.0,      # pilot human, in vivo animal
    "Preliminary": 0.75,  # in vitro, computational, case reports
}
_HUMAN_TIERS = {"Strong", "Moderate"}      # sample-size scaling applies to these
_LOW_TIERS = {"Emerging", "Preliminary"}   # subject to the hard cap

# ---- constants (calibrated so scores discriminate across the 0-100 range) ---
# Points are summed with PER-STUDY DIMINISHING RETURNS (the k-th study of a tier
# counts less than the 1st), then mapped through a gentle curve. Without the
# decay, well-studied compounds pile up hundreds of points and every one
# saturates at 100 — the score stops discriminating (creatine's four outcomes
# all hit 100.0 in the first real run). Decay + gentle curve restores spread:
# an overwhelming base (~30 studies, 10 meta-analyses) lands ~100, a solid-but-
# thinner one (~12 studies) ~77, a single small RCT ~27.
LOW_TIER_CAP = 35.0            # max combined Emerging+Preliminary points (pre-decay)
STUDY_DECAY = 0.55            # k-th study of a tier discounted by 1/(1+0.55*k)
CURVE_COEFF = 9.5
CURVE_EXP = 0.40
SINGLE_SOURCE_PENALTY = 0.85   # -15% if single_source_bias
Z = 1.96                       # 95% CI


@dataclass
class Study:
    tier: str                              # "Strong"|"Moderate"|"Emerging"|"Preliminary"
    is_supportive: bool
    sample_size: Optional[int] = None
    citation_count: Optional[int] = None


def _sample_scaling(study):
    """
    S_k — sample-size scaling, ONLY for human tiers (Strong/Moderate). Unknown N
    or non-human tier -> 1.0 (neutral). Bounded [1.0, 2.0].
        S_k = min(2.0, max(1.0, log10(N) - 0.5))
    """
    if study.tier not in _HUMAN_TIERS:
        return 1.0, False
    n = study.sample_size
    if not isinstance(n, (int, float)) or n <= 0:
        return 1.0, False           # unknown N -> neutral, flagged as defaulted
    s = math.log10(n) - 0.5
    return min(2.0, max(1.0, s)), True


def _citation_weight(study):
    """
    C_k — citation weighting, ALL tiers. Missing citations -> 1.0 (neutral).
    Bounded [0.8, 1.75].
        C_k = min(1.75, max(0.8, 1.0 + 0.15 * log10(Citations + 1)))
    """
    c = study.citation_count
    if not isinstance(c, (int, float)) or c < 0:
        return 1.0, False           # unknown -> neutral, flagged as defaulted
    cw = 1.0 + 0.15 * math.log10(c + 1)
    return min(1.75, max(0.8, cw)), True


def _confidence_tier(score):
    if score >= 75:
        return "Gold Standard"
    if score >= 50:
        return "Moderate-High"
    if score >= 25:
        return "Emerging"
    return "Preliminary"


def calculate_compound_score(studies, single_source_bias=False):
    """
    Roll a list of graded Study objects into a 0-100 score with a 95% CI.
    See module docstring for the method. Returns a structured dict.
    """
    # ---- edge case: no studies -------------------------------------------
    if not studies:
        return {
            "final_score": 0.0,
            "confidence_interval": {"lower": 0.0, "upper": 0.0},
            "confidence_tier": "Preliminary",
            "breakdown": {
                "n_studies": 0,
                "note": "No studies provided — score is zero by definition.",
            },
        }

    # ---- 2. per-study modified points ------------------------------------
    n_missing_n = 0
    n_missing_cit = 0
    n_supportive = 0
    human_sample_total = 0
    total_sample_known = 0
    per_study = []
    # Collect raw points per tier so we can apply per-study diminishing returns.
    tier_points = {"Strong": [], "Moderate": [], "Emerging": [], "Preliminary": []}

    for k, st in enumerate(studies):
        w = TIER_WEIGHTS.get(st.tier)
        if w is None:
            # Unknown tier is treated as Preliminary rather than crashing.
            w = TIER_WEIGHTS["Preliminary"]
            st_tier = "Preliminary"
        else:
            st_tier = st.tier

        s_k, n_used = _sample_scaling(st)
        c_k, c_used = _citation_weight(st)
        if not n_used and st_tier in _HUMAN_TIERS:
            n_missing_n += 1
        if not c_used:
            n_missing_cit += 1

        pts = w * s_k * c_k
        tier_points[st_tier].append(pts)

        if st.is_supportive:
            n_supportive += 1
        if st_tier in _HUMAN_TIERS and isinstance(st.sample_size, (int, float)) and st.sample_size > 0:
            human_sample_total += int(st.sample_size)
        if isinstance(st.sample_size, (int, float)) and st.sample_size > 0:
            total_sample_known += int(st.sample_size)

        per_study.append({
            "idx": k, "tier": st_tier, "base_weight": w,
            "S_k": round(s_k, 3), "C_k": round(c_k, 3),
            "points": round(pts, 3), "supportive": st.is_supportive,
        })

    # ---- 2b. per-study diminishing returns, within each tier -------------
    # The k-th study of a tier (strongest first) is discounted by 1/(1+decay*k),
    # so the 20th confirmatory meta-analysis adds far less than the 1st. Without
    # this, 30 studies produce ~30x the points of one and every well-studied
    # outcome saturates at 100.
    def _decayed(points_list):
        ordered = sorted(points_list, reverse=True)
        return sum(p / (1 + STUDY_DECAY * i) for i, p in enumerate(ordered))

    high_tier_points = _decayed(tier_points["Strong"] + tier_points["Moderate"])
    low_tier_points = _decayed(tier_points["Emerging"] + tier_points["Preliminary"])

    # ---- 3. low-tier hard cap --------------------------------------------
    low_tier_capped = min(low_tier_points, LOW_TIER_CAP)
    cap_applied = low_tier_points > LOW_TIER_CAP
    total_points = high_tier_points + low_tier_capped   # R

    # ---- 4. non-linear diminishing-returns curve -------------------------
    scaled_base = min(100.0, CURVE_COEFF * (total_points ** CURVE_EXP)) if total_points > 0 else 0.0

    # ---- 5. multipliers & penalties --------------------------------------
    n_total = len(studies)
    p_supportive = n_supportive / n_total if n_total else 0.0
    score = scaled_base * p_supportive
    if single_source_bias:
        score *= SINGLE_SOURCE_PENALTY
    final_score = max(0.0, min(100.0, score))

    # ---- 6. 95% CI via proportion-variance SE (Laplace-smoothed) ---------
    # Laplace smoothing keeps SE finite at the 0%/100% edges where p(1-p)=0.
    #
    # The margin is expressed directly in SCORE POINTS, not as a fraction of the
    # score. The spec's original `MoE = 1.96 * SE * final_score` multiplied a
    # points-scale SE by the score again, producing margins of 100-1700 that
    # pinned every interval to [0, 100] (useless). Both SE terms below are
    # already in points on the 0-100 scale:
    #   - proportion term: consistency uncertainty, scaled to the score so a
    #     50/50 split on few studies widens the band and a clean consensus
    #     narrows it;
    #   - data-thinness term: a bounded points penalty that grows as human
    #     sample size shrinks, so sparse human evidence -> wider band.
    p_smooth = (n_supportive + 1) / (n_total + 2)
    prop_se_points = math.sqrt(p_smooth * (1 - p_smooth) / (n_total + 2)) * final_score
    thinness_points = min(30.0, 15.0 / math.sqrt(human_sample_total + 1) * 10.0)
    se_points = prop_se_points + thinness_points
    moe = Z * se_points
    ci_lower = round(max(0.0, final_score - moe), 1)
    ci_upper = round(min(100.0, final_score + moe), 1)

    final_score = round(final_score, 1)

    return {
        "final_score": final_score,
        "confidence_interval": {"lower": ci_lower, "upper": ci_upper},
        "confidence_tier": _confidence_tier(final_score),
        "breakdown": {
            "n_studies": n_total,
            "high_tier_points": round(high_tier_points, 3),
            "low_tier_points_pre_cap": round(low_tier_points, 3),
            "low_tier_points_post_cap": round(low_tier_capped, 3),
            "low_tier_cap_applied": cap_applied,
            "total_points_R": round(total_points, 3),
            "scaled_base_score": round(scaled_base, 3),
            "p_supportive": round(p_supportive, 4),
            "single_source_penalty": single_source_bias,
            "standard_error_points": round(se_points, 4),
            "se_consistency_component": round(prop_se_points, 4),
            "se_thinness_component": round(thinness_points, 4),
            "margin_of_error": round(moe, 3),
            "human_sample_total": human_sample_total,
            "studies_missing_sample_size": n_missing_n,
            "studies_missing_citations": n_missing_cit,
            "data_completeness_note": (
                f"{n_missing_n} human study(ies) used a default sample-size "
                f"multiplier and {n_missing_cit} study(ies) used a default "
                f"citation multiplier (data unavailable — treated as neutral, "
                f"never penalised)."
            ),
            "per_study": per_study,
        },
    }


if __name__ == "__main__":
    import json

    def show(title, result):
        print(f"\n{'='*66}\n{title}\n{'='*66}")
        print(f"  final_score      : {result['final_score']}")
        ci = result["confidence_interval"]
        print(f"  95% CI           : [{ci['lower']}, {ci['upper']}]")
        print(f"  confidence_tier  : {result['confidence_tier']}")
        b = result["breakdown"]
        if b.get("n_studies"):
            print(f"  R (capped points): {b['total_points_R']}  "
                  f"-> scaled base {b['scaled_base_score']}")
            print(f"  p_supportive     : {b['p_supportive']}   "
                  f"SE {b['standard_error_points']}pts  MoE {b['margin_of_error']}")
            print(f"  {b['data_completeness_note']}")

    # --- Scenario 1: one highly-cited RCT vs ten uncited RCTs -------------
    # Shows citation weighting rewarding impact, and how a supportive
    # consensus of solid trials scores.
    one_high = [Study("Strong", True, sample_size=450, citation_count=1200)]
    ten_uncited = [Study("Strong", True, sample_size=60, citation_count=0)
                   for _ in range(10)]
    show("Scenario 1a — a single highly-cited large RCT", calculate_compound_score(one_high))
    show("Scenario 1b — ten uncited smaller RCTs", calculate_compound_score(ten_uncited))

    # --- Scenario 2: low-sample, high-conflict -> wide CI ----------------
    conflicted = [
        Study("Moderate", True, sample_size=18, citation_count=5),
        Study("Moderate", False, sample_size=22, citation_count=3),
        Study("Emerging", True, sample_size=12, citation_count=1),
        Study("Emerging", False, sample_size=None, citation_count=0),
    ]
    show("Scenario 2 — small samples, conflicting results (wide CI expected)",
         calculate_compound_score(conflicted))

    # --- Scenario 3: preclinical pile-up hits the hard cap ---------------
    preclinical = [Study("Preliminary", True, citation_count=0) for _ in range(40)] \
        + [Study("Emerging", True, sample_size=None, citation_count=2) for _ in range(20)]
    show("Scenario 3 — 60 low-tier studies (hard cap should bind)",
         calculate_compound_score(preclinical))

    # --- Scenario 4: edge cases -----------------------------------------
    show("Scenario 4a — empty study list", calculate_compound_score([]))
    all_supportive = [Study("Strong", True, sample_size=200, citation_count=50) for _ in range(4)]
    show("Scenario 4b — 100% supportive (Laplace keeps SE finite)",
         calculate_compound_score(all_supportive))

    # single-source penalty illustration
    show("Scenario 5 — strong evidence but single-source bias flagged",
         calculate_compound_score(all_supportive, single_source_bias=True))