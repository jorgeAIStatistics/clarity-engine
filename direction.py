"""
Effect + direction extraction.

Two gaps this closes:
  1. Effect sizes are almost never extractable, so the product can say HOW
     CONFIDENT to be but never HOW MUCH benefit.
  2. The tier measures certainty, not direction — so Ginkgo, Chromium, BCAAs
     and Biotin grade Strong on large literatures that mostly say "no effect".
     A reader sees "Strong" and concludes it works. That is the single most
     misleading output in the catalog.

`direction_of_conclusion` is the fix for (2): a meta-analysis abstract that
says "no significant difference" reports direction even when no number is
extractable. That lets the engine flag WELL-STUDIED NULL RESULTS — a category
no consumer supplement site publishes.

ANTI-FABRICATION IS ENFORCED IN CODE, NOT THE PROMPT. The model is asked for a
verbatim quote; Python then verifies that quote actually appears in the abstract
and contains the number claimed. A prompt rule the model promises to follow is
weaker than one the code checks.

DIRECTION NEVER RAISES A GRADE. It can flag a null result or cap a tier, never
promote one — extraction informs, it does not grade.
"""

import os
import json
import re

_MODEL = os.environ.get("CLARITY_LLM_MODEL", "claude-haiku-4-5-20251001")
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "directions.json")

_NULL_VALUE = {"odds_ratio": 1.0, "risk_ratio": 1.0, "hazard_ratio": 1.0}

_SYSTEM = (
    "You are an expert clinical data extractor. Parse the provided PubMed abstracts "
    "and extract quantitative effect sizes, confidence intervals, and the overall "
    "direction of findings for the named health outcome.\n\n"
    "RULES:\n"
    "1. Never invent data. If an abstract does not report exact quantitative "
    "metrics, leave those fields null and rely on the qualitative conclusion.\n"
    "2. Always include a VERBATIM quote from the abstract supporting your "
    "extraction. Copy it exactly — do not paraphrase, reformat, or correct it. "
    "The quote will be checked character-for-character against the source.\n"
    "3. Determine whether the reported 95% CI crosses the null threshold "
    "(0 for mean differences and standardized effects, 1.0 for risk/odds ratios).\n"
    "4. Determine the direction of the conclusion: does it favor the treatment, "
    "favor the control, show a null/neutral result, or is it unclear? A study "
    "stating 'no significant difference', 'did not improve', or 'failed to "
    "demonstrate' is a null_result, NOT unclear.\n"
    "5. Prefer pooled/meta-analytic results over individual studies when present.\n"
    "6. Output ONLY valid JSON matching the schema. No markdown, no commentary.\n\n"
    "SCHEMA:\n"
    "{\n"
    '  "outcome": string,\n'
    '  "headline_effect": {\n'
    '    "metric": "smd|cohen_d|mean_diff|odds_ratio|risk_ratio|hazard_ratio|none_reported",\n'
    '    "value": number or null, "ci_low": number or null, "ci_high": number or null,\n'
    '    "n_studies_pooled": number or null,\n'
    '    "comparator": "placebo|active|baseline|none",\n'
    '    "is_estimated": boolean\n'
    "  },\n"
    '  "crosses_null": true | false | null,\n'
    '  "direction_of_conclusion": "favors_treatment|null_result|favors_control|unclear",\n'
    '  "conclusion_quote": string (VERBATIM from an abstract)\n'
    "}"
)


def _parse_first_object(raw):
    """
    Parse the first valid JSON object in the response.

    The model sometimes returns several objects back-to-back (one per outcome)
    or wraps them in {"extractions": [...]}. A naive first-brace-to-last-brace
    slice then yields invalid JSON ("Extra data"), which silently killed every
    direction extraction. raw_decode stops at the end of the first object.
    """
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()
    start = raw.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError:
        return None
    # tolerate an {"extractions": [...]} wrapper
    if isinstance(obj, dict) and "extractions" in obj:
        items = obj.get("extractions") or []
        return items[0] if items else None
    return obj


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


def _normalize(t):
    """Whitespace/dash-insensitive comparison for quote verification."""
    t = (t or "").lower()
    t = t.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    t = t.replace("\u2018", "'").replace("\u2019", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", t).strip()


def validate(obj, abstracts_blob):
    """
    The gate. Returns a cleaned extraction, or a null-effect record explaining
    why it was rejected. Enforced here rather than trusted to the prompt.
    """
    out = {
        "metric": None, "value": None, "ci_low": None, "ci_high": None,
        "n_studies_pooled": None, "comparator": None, "is_estimated": False,
        "crosses_null": None, "direction": "unclear", "quote": None,
        "rejected_reason": None,
    }
    if not isinstance(obj, dict):
        out["rejected_reason"] = "no extraction returned"
        return out

    direction = obj.get("direction_of_conclusion")
    if direction not in ("favors_treatment", "null_result", "favors_control", "unclear"):
        direction = "unclear"

    quote = (obj.get("conclusion_quote") or "").strip()
    blob_n = _normalize(abstracts_blob)

    # A direction claim still needs a supporting quote that really exists.
    if not quote or _normalize(quote) not in blob_n:
        out["rejected_reason"] = "supporting quote not found verbatim in abstracts"
        return out
    out["quote"] = quote
    out["direction"] = direction

    he = obj.get("headline_effect") or {}
    metric = he.get("metric")
    value = he.get("value")
    if metric in (None, "none_reported") or not isinstance(value, (int, float)):
        # Direction without numbers is still valuable — that's the whole point.
        return out

    # If a number is claimed, the quote must contain it.
    q_n = _normalize(quote)
    if not any(str(round(float(value), p)) in q_n for p in (0, 1, 2, 3)):
        out["rejected_reason"] = f"quote does not contain the claimed value {value}"
        return out

    lo, hi = he.get("ci_low"), he.get("ci_high")
    has_ci = isinstance(lo, (int, float)) and isinstance(hi, (int, float))

    out.update({
        "metric": metric, "value": float(value),
        "ci_low": float(lo) if has_ci else None,
        "ci_high": float(hi) if has_ci else None,
        "n_studies_pooled": he.get("n_studies_pooled"),
        "comparator": he.get("comparator"),
        "is_estimated": bool(he.get("is_estimated")),
    })

    # Compute crosses_null ourselves rather than trusting the model.
    if has_ci:
        null_v = _NULL_VALUE.get(metric, 0.0)
        out["crosses_null"] = bool(lo < null_v < hi)
    else:
        out["crosses_null"] = obj.get("crosses_null") if isinstance(
            obj.get("crosses_null"), bool) else None

    # A CI crossing null IS a null result, whatever the model called it.
    if out["crosses_null"] is True and direction == "favors_treatment":
        out["direction"] = "null_result"
        out["rejected_reason"] = None

    return out


def extract_direction(topic, outcome, studies, force=False):
    """
    Extract effect + direction for ONE outcome from its abstracts.
    Prefers meta-analyses/systematic reviews, which state pooled conclusions.
    Cached by topic+outcome+study set.
    """
    import hashlib
    pmids = sorted(str(s.get("pmid")) for s in studies if s.get("pmid"))
    key = f"{topic}::{outcome}::" + hashlib.sha1(",".join(pmids).encode()).hexdigest()[:10]

    cache = _load_cache()
    if not force and key in cache:
        return cache[key]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not studies:
        return validate(None, "")

    # Syntheses first — they report pooled direction explicitly.
    ranked = sorted(studies, key=lambda s: 0 if s.get("design") in
                    ("Meta-analysis", "Systematic review", "meta_analysis",
                     "systematic_review") else 1)
    chosen = [s for s in ranked if s.get("abstract")][:6]
    if not chosen:
        return validate(None, "")

    blob = "\n\n".join(
        f"[PMID {s.get('pmid')}] {s.get('title','')}\n{(s.get('abstract') or '')[:1800]}"
        for s in chosen)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_MODEL, max_tokens=900, system=_SYSTEM,
            messages=[{"role": "user",
                       "content": f"Compound: {topic}\nOutcome: {outcome}\n\n"
                                  f"ABSTRACTS:\n{blob}\n\nExtract the JSON now."}],
        )
        raw = resp.content[0].text.strip()
        result = validate(_parse_first_object(raw), blob)
    except json.JSONDecodeError as e:
        print(f"  [direction] {topic}/{outcome}: JSON parse failed ({e})")
        result = validate(None, "")
    except Exception as e:
        print(f"  [direction] {topic}/{outcome}: {type(e).__name__}: {e}")
        result = validate(None, "")

    cache[key] = result
    _save_cache(cache)
    return result


def apply_direction(claim, direction_rec):
    """
    Fold direction into a graded claim. STRICTLY ONE-WAY: may flag a null result
    or cap a tier, never promote one. A compound with a large literature that
    concludes "no effect" should NOT read as Strong evidence it works.
    """
    if not direction_rec:
        return claim
    d = direction_rec.get("direction")
    claim["direction"] = d
    claim["direction_quote"] = direction_rec.get("quote")
    if direction_rec.get("metric"):
        claim["headline_effect"] = {
            "metric": direction_rec["metric"], "value": direction_rec["value"],
            "ci_low": direction_rec["ci_low"], "ci_high": direction_rec["ci_high"],
            "n_studies_pooled": direction_rec["n_studies_pooled"],
            "comparator": direction_rec["comparator"],
            "direction": d,
            "ci_estimated": direction_rec["is_estimated"],
            "crosses_null": direction_rec["crosses_null"],
            "quote": direction_rec["quote"],
        }

    if d in ("null_result", "favors_control"):
        # THE KEY BEHAVIOUR: well-studied + null is its own answer, not "Strong".
        claim["null_result"] = True
        original = claim.get("tier")
        # "WELL STUDIED — no clear benefit" is itself a strong claim: it asserts
        # the research is solid AND shows nothing. Milk thistle triggered it on
        # five studies, which cannot support that. A thin null result is just
        # thin evidence — flag it, but don't dress it as a settled finding.
        L = claim.get("layers", {}) or {}
        well_studied = L.get("n_human_studies", 0) >= 5
        if not well_studied:
            claim.setdefault("grade_reasons", []).append(
                "Direction: the retrieved evidence does not show a benefit, but "
                "too few human studies exist to call this settled.")
            return claim
        if original in ("Strong", "Moderate"):
            claim["tier_certainty"] = original      # keep: evidence IS strong
            claim["tier"] = "Well studied — no clear benefit"
            claim.setdefault("grade_reasons", []).append(
                "Direction: the pooled evidence does not show a benefit"
                + (" (confidence interval crosses the null)."
                   if direction_rec.get("crosses_null") else ".")
                + " Certainty in this finding is "
                + {"Strong": "high", "Moderate": "moderate"}[original] + ".")
    return claim


if __name__ == "__main__":
    A = ("Ginkgo biloba did not reduce the incidence of dementia (hazard ratio 1.12, "
         "95% CI 0.94 to 1.33). We found no significant difference between groups.")
    obj = {"outcome": "cognition",
           "headline_effect": {"metric": "hazard_ratio", "value": 1.12,
                               "ci_low": 0.94, "ci_high": 1.33,
                               "n_studies_pooled": 1, "comparator": "placebo",
                               "is_estimated": False},
           "crosses_null": True, "direction_of_conclusion": "null_result",
           "conclusion_quote": "hazard ratio 1.12, 95% CI 0.94 to 1.33"}
    r = validate(obj, A)
    print("validated:", json.dumps(r, indent=2))
    claim = {"outcome": "cognition", "tier": "Strong", "grade_reasons": []}
    print("\nafter apply_direction:", json.dumps(apply_direction(claim, r), indent=2))
