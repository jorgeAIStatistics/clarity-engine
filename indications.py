"""Canonical indication seeds and search aliases for indication-dependent nutrients.

This module does NOT assign grades. It only makes sure outcome discovery asks the
clinically relevant questions instead of depending entirely on whatever topics
happen to dominate a generic literature search.
"""
import re


def _norm(name):
    s = str(name or "").lower().strip()
    s = re.sub(r"\s*\([^)]*\)\s*", " ", s)
    return " ".join(s.split())


# Search aliases are factual naming variants, not evidence claims.
_ALIASES = {
    "vitamin d3": ["vitamin d3", "cholecalciferol", "vitamin d"],
    "vitamin b12": ["vitamin b12", "cobalamin", "cyanocobalamin", "methylcobalamin"],
    "vitamin c": ["vitamin c", "ascorbic acid", "ascorbate"],
    "vitamin k2": ["vitamin k2", "menaquinone", "menaquinone-7", "mk-7"],
    "folate": ["folate", "folic acid", "vitamin b9"],
    "vitamin a": ["vitamin a", "retinol", "retinoid"],
    "vitamin e": ["vitamin e", "alpha-tocopherol", "tocopherol"],
    "vitamin b6": ["vitamin b6", "pyridoxine", "pyridoxal phosphate"],
    "biotin": ["biotin", "vitamin b7"],
    "niacin": ["niacin", "nicotinic acid", "vitamin b3"],
    "thiamine": ["thiamine", "thiamin", "vitamin b1"],
}


# These are outcome QUESTIONS the engine must examine. They do not preset the
# answer or tier; the ordinary retrieval, relevance, intervention and grading
# pipeline still decides what the evidence supports.
_CANONICAL = {
    "vitamin d3": [
        "vitamin D deficiency / repletion",
        "bone health / fractures",
    ],
    "vitamin b12": [
        "vitamin B12 deficiency / megaloblastic anemia",
        "neurologic function / neuropathy",
    ],
    "vitamin c": [
        "vitamin C deficiency / scurvy",
        "common cold / respiratory infection",
    ],
    "vitamin k2": [
        "bone health / bone mineral density",
        "vascular calcification / cardiovascular health",
    ],
    "folate": [
        "folate deficiency / megaloblastic anemia",
        "neural tube defects / pregnancy",
    ],
    "vitamin a": [
        "vitamin A deficiency / xerophthalmia",
        "vision / eye health",
    ],
    "vitamin e": [
        "vitamin E deficiency",
        "cardiovascular prevention",
    ],
    "vitamin b6": [
        "vitamin B6 deficiency",
        "homocysteine / cardiovascular biomarkers",
    ],
    "biotin": [
        "biotin deficiency",
        "hair / nails",
    ],
    "niacin": [
        "niacin deficiency / pellagra",
        "lipids / cholesterol",
    ],
    "thiamine": [
        "thiamine deficiency / beriberi",
        "Wernicke encephalopathy / neurologic deficiency",
    ],
}

# Frontend display names that clean to the same canonical key.
_KEY_ALIASES = {
    "folate b9": "folate",
    "folic acid": "folate",
    "vitamin b9": "folate",
    "biotin b7": "biotin",
    "vitamin b7": "biotin",
    "niacin b3": "niacin",
    "vitamin b3": "niacin",
    "thiamine b1": "thiamine",
    "vitamin b1": "thiamine",
}


def key_for(topic):
    k = _norm(topic).replace("(", " ").replace(")", " ")
    k = " ".join(k.split())
    return _KEY_ALIASES.get(k, k)


def search_aliases(topic):
    k = key_for(topic)
    aliases = list(_ALIASES.get(k, []))
    raw = _norm(topic)
    if raw and raw not in aliases:
        aliases.insert(0, raw)
    # longest first helps exact phrase checks before short generic variants
    out = []
    for a in aliases:
        a = str(a).strip().lower()
        if a and a not in out:
            out.append(a)
    return out


def canonical_outcomes(topic, category=None):
    if category and str(category).lower() != "vitamin":
        return []
    return list(_CANONICAL.get(key_for(topic), []))


def merge_outcomes(topic, category, discovered, max_outcomes=5):
    """Canonical questions first, then engine-discovered outcomes, deduped."""
    out = []
    for value in canonical_outcomes(topic, category) + list(discovered or []):
        if not value:
            continue
        sig = re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()
        if any(re.sub(r"[^a-z0-9]+", " ", x.lower()).strip() == sig for x in out):
            continue
        out.append(str(value))
        if len(out) >= max_outcomes:
            break
    return out


def is_canonical_outcome(topic, category, outcome):
    return str(outcome) in canonical_outcomes(topic, category)


def catalog_meta(profile):
    """Outcome-aware catalog metadata without altering scientific grades.

    Vitamins are marked outcome-dependent whenever their human outcome tiers
    differ, because deficiency/repletion and general-use questions are often
    fundamentally different. Other categories use a stricter two-tier spread
    so a trivial Strong-vs-Moderate difference does not clutter the catalog.
    """
    profile = profile or {}
    claims = list(profile.get("claims") or [])
    rank = {"Preliminary": 0, "Emerging": 1, "Moderate": 2, "Strong": 3}
    human = [c for c in claims if c.get("has_human_evidence") or (c.get("layers") or {}).get("n_human_studies", 0) > 0]
    candidates = human or claims
    best = max(
        candidates,
        key=lambda c: (
            rank.get(c.get("tier"), -1),
            (c.get("layers") or {}).get("human", 0),
            c.get("score", 0),
            c.get("n_studies", 0),
        ),
        default=None,
    )
    tiers = []
    for c in human:
        t = c.get("tier")
        if t in rank and t not in tiers:
            tiers.append(t)
    spread = (max((rank[t] for t in tiers), default=0) - min((rank[t] for t in tiers), default=0)) if len(tiers) > 1 else 0
    is_vitamin = str(profile.get("category") or "").lower() == "vitamin"
    outcome_dependent = bool(profile.get("outcome_dependent")) or (len(tiers) > 1 and (is_vitamin or spread >= 2))
    return {
        "display_tier": "Outcome-dependent" if outcome_dependent else profile.get("tier"),
        "outcome_dependent": outcome_dependent,
        "best_outcome": best.get("outcome") if best else profile.get("best_outcome"),
        "best_tier": best.get("tier") if best else (profile.get("best_tier") or profile.get("tier")),
        "outcome_tiers": tiers,
        "overall_tier_basis": profile.get("overall_tier_basis", "best_human_supported_outcome"),
    }

