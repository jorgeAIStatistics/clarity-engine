"""
Effect-size extraction — turns an abstract into a structured effect object, or
honestly reports "not reported". This is what feeds the forest plot.

GOVERNING PRINCIPLE: it is always better to extract NOTHING than a wrong number.
A blank is honest; a fabricated effect drawn as a crisp interval is the
forest-plot lie. Every rule below serves that principle.

Two-tier honesty (matches the agreed plot design):
  - VERIFIED effect  = metric reported directly, CI reported directly.
                       -> drawn SOLID, feeds the solid pooled diamond.
  - DERIVED effect   = metric converted from another, OR CI estimated from n.
                       -> drawn DASHED, feeds only the dashed exploratory diamond.

The extractor is an LLM call (fact extraction, not fabrication): it must return
a verbatim supporting quote copied from the abstract, or the value "not_reported".
If it can't point to the words, it can't claim the number.

The validation GATE is the product. Every extraction is checked before it is
allowed near the plot; anything that fails becomes "not_reported" and is never
drawn. Gate logic is deterministic and lives here so it can be read, tested,
and tuned with biostatistics judgment — NOT hidden inside a prompt.

Degrades safely: with no ANTHROPIC_API_KEY, extract() returns not_reported and
the engine still runs. Cached by PMID so each study is extracted once, ever.
"""

import os
import json
import math

_MODEL = os.environ.get("CLARITY_LLM_MODEL", "claude-haiku-4-5-20251001")
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "effect_sizes.json")

# Metrics the engine understands and can position on an effect axis.
# 'family' groups metrics that measure the same KIND of thing:
#   smd   = standardized mean difference scale (Cohen's d, Hedges' g, SMD, r)
#   ratio = ratio-of-risk scale (odds ratio, risk ratio, hazard ratio)
#   raw   = unit-bearing mean difference (kept, but NEVER pooled across studies
#           because the units differ — shown individually only)
_METRICS = {
    "cohen_d":     {"family": "smd",   "null": 0.0},
    "hedges_g":    {"family": "smd",   "null": 0.0},
    "smd":         {"family": "smd",   "null": 0.0},
    "correlation": {"family": "smd",   "null": 0.0},   # r, convertible to d
    "odds_ratio":  {"family": "ratio", "null": 1.0},
    "risk_ratio":  {"family": "ratio", "null": 1.0},
    "hazard_ratio":{"family": "ratio", "null": 1.0},
    "mean_diff":   {"family": "raw",   "null": 0.0},    # unit-bearing
}

# Plausibility bounds per family — anything outside is a parse error, not a
# finding, and is rejected by the gate. Deliberately generous; tune with judgment.
_PLAUSIBLE = {
    "smd":   (-10.0, 10.0),    # a Cohen's d of 47 is a parse error
    "ratio": (0.01, 100.0),    # ratios are positive; extreme values are errors
    "raw":   (-1e6, 1e6),      # unit-bearing, so only gross bounds
}

_SYSTEM = (
    "You extract the primary effect size from a biomedical study abstract for ONE "
    "named outcome. Return STRICT JSON, nothing else. Schema:\n"
    "{\n"
    '  "metric": one of [cohen_d,hedges_g,smd,correlation,odds_ratio,risk_ratio,'
    'hazard_ratio,mean_diff] or "not_reported",\n'
    '  "value": number (the point estimate) or null,\n'
    '  "ci_low": number or null,   "ci_high": number or null,\n'
    '  "comparator": short string (e.g. "vs placebo", "vs baseline") or null,\n'
    '  "direction": "benefit" | "harm" | "none" | null,\n'
    '  "unit": string for mean_diff only (e.g. "kg") or null,\n'
    '  "quote": VERBATIM substring copied from the abstract that states the number,'
    ' or null\n'
    "}\n"
    "RULES: Only report a number the abstract actually states. If the abstract "
    "gives no numeric effect for this outcome, return metric=\"not_reported\" and "
    "null everything else. NEVER invent or infer a value. The quote MUST be copied "
    "verbatim from the abstract and MUST contain the value. If you cannot copy such "
    "a quote, return not_reported."
)


_POOLED_SYSTEM = (
    "You extract the HEADLINE POOLED effect size from a systematic review or "
    "meta-analysis abstract, for ONE named outcome. Meta-analyses state their "
    "pooled result explicitly (e.g. 'pooled SMD 0.42, 95% CI 0.21 to 0.63'). "
    "Return STRICT JSON only:\n"
    "{\n"
    '  "metric": one of [cohen_d,hedges_g,smd,correlation,odds_ratio,risk_ratio,'
    'hazard_ratio,mean_diff] or "not_reported",\n'
    '  "value": number or null,   "ci_low": number or null,   "ci_high": number or null,\n'
    '  "n_studies_pooled": integer or null,\n'
    '  "comparator": short string or null,   "direction": "benefit"|"harm"|"none"|null,\n'
    '  "unit": string for mean_diff only or null,\n'
    '  "quote": VERBATIM substring from the abstract stating the pooled value, or null\n'
    "}\n"
    "RULES: Extract ONLY the pooled/summary estimate the meta-analysis reports for "
    "THIS outcome — not an individual study within it. If the abstract gives no "
    "pooled numeric effect for this outcome, return not_reported. The quote MUST be "
    "copied verbatim and MUST contain the value. Never invent or infer."
)


def extract_pooled(pmid, title, abstract, outcome):
    """
    Extract the headline pooled effect from a meta-analysis / systematic review
    abstract. Higher yield than per-study extraction because these abstracts are
    written to state their pooled result. Returns a validated effect dict; the
    pooled estimate is inherently 'verified' when it carries a reported CI (the
    synthesis already did the consistency work). Cached per pmid+outcome+pooled.
    """
    cache = _load_cache()
    key = f"{pmid}::{outcome}::pooled"
    if key in cache:
        return cache[key]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not abstract:
        return _not_reported("extractor unavailable or empty abstract")

    try:
        import anthropic
    except ImportError:
        return _not_reported("anthropic library not installed")

    user = f"Outcome: {outcome}\n\nTitle: {title}\n\nAbstract: {abstract[:2500]}"
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_MODEL, max_tokens=400, system=_POOLED_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text.strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        obj = json.loads(raw)
        result = validate(obj, abstract)
        # A pooled meta-analytic estimate WITH a reported CI is the synthesis
        # itself — mark it as a pooled source so the UI can label it correctly.
        if result.get("status") in ("verified", "derived"):
            result["source"] = "meta_analysis_pooled"
            result["n_studies_pooled"] = obj.get("n_studies_pooled")
    except Exception as e:
        result = _not_reported(f"extraction error: {type(e).__name__}")

    cache[key] = result
    _save_cache(cache)
    return result


def _load_cache():
    try:
        with open(_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def _not_reported(reason):
    return {"metric": "not_reported", "value": None, "ci_low": None, "ci_high": None,
            "comparator": None, "direction": None, "unit": None, "quote": None,
            "status": "not_reported", "reason": reason, "tier": None}


def validate(obj, abstract):
    """
    The GATE. Takes a raw extraction dict + the abstract it came from, returns a
    validated effect dict with a 'status' and 'tier':
      status: "verified" | "derived" | "not_reported"
      tier:   "solid" (verified) | "dashed" (derived) | None
    Deterministic, testable, and the single place trust is decided.
    """
    if not obj or obj.get("metric") in (None, "not_reported"):
        return _not_reported("no effect reported for this outcome")

    metric = obj.get("metric")
    if metric not in _METRICS:
        return _not_reported(f"unknown metric '{metric}'")

    value = obj.get("value")
    if not isinstance(value, (int, float)):
        return _not_reported("no numeric point estimate")

    fam = _METRICS[metric]["family"]
    lo_b, hi_b = _PLAUSIBLE[fam]
    if not (lo_b <= value <= hi_b):
        return _not_reported(f"value {value} implausible for {metric} (parse error)")

    # Quote must exist AND actually appear in the abstract AND contain a digit.
    quote = (obj.get("quote") or "").strip()
    if not quote or quote not in abstract:
        return _not_reported("supporting quote missing or not found verbatim in abstract")
    if not any(ch.isdigit() for ch in quote):
        return _not_reported("supporting quote contains no number")

    comparator = obj.get("comparator")
    ci_low, ci_high = obj.get("ci_low"), obj.get("ci_high")
    has_ci = isinstance(ci_low, (int, float)) and isinstance(ci_high, (int, float))

    # Determine tier.
    #  - VERIFIED: metric is a directly-usable SMD/ratio AND a CI was reported.
    #  - DERIVED: needs metric conversion (correlation -> d), OR CI must be
    #    estimated (point estimate but no CI). Present, but dashed.
    needs_conversion = (metric == "correlation")   # r shown on d-axis after convert
    if has_ci and not needs_conversion:
        status, tier = "verified", "solid"
    else:
        status, tier = "derived", "dashed"

    # If CI missing, estimate a rough one so the mark can be drawn — but DASHED,
    # and flagged, so it never masquerades as reported precision.
    ci_estimated = False
    if not has_ci:
        # Without n or SE we cannot compute a real CI. We draw a WIDE placeholder
        # interval and flag it — its width honestly signals "we don't know".
        null = _METRICS[metric]["null"]
        span = abs(value - null) if value != null else 0.5
        ci_low, ci_high = value - span, value + span
        ci_estimated = True

    return {
        "metric": metric,
        "family": fam,
        "value": value,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_estimated": ci_estimated,
        "converted": needs_conversion,
        "comparator": comparator,
        "direction": obj.get("direction"),
        "unit": obj.get("unit"),
        "quote": quote,
        "status": status,
        "tier": tier,
        "reason": None,
    }


def extract(pmid, title, abstract, outcome):
    """
    Extract + validate one study's effect for one outcome. Returns a validated
    dict (see validate). Cached by pmid+outcome. Degrades to not_reported with
    no key / no network / any error.
    """
    cache = _load_cache()
    key = f"{pmid}::{outcome}"
    if key in cache:
        return cache[key]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not abstract:
        return _not_reported("extractor unavailable or empty abstract")

    try:
        import anthropic
    except ImportError:
        return _not_reported("anthropic library not installed")

    user = f"Outcome: {outcome}\n\nTitle: {title}\n\nAbstract: {abstract[:2500]}"
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_MODEL, max_tokens=400, system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text.strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1]  # strip any stray prose
        obj = json.loads(raw)
        result = validate(obj, abstract)
    except Exception as e:
        result = _not_reported(f"extraction error: {type(e).__name__}")

    cache[key] = result
    _save_cache(cache)
    return result


def pool(effects):
    """
    Inverse-variance pooled estimate for a list of VALIDATED effects that share
    an effect family. Returns two diamonds:
      verified   = pooled over solid (verified) effects only  -> headline
      exploratory= pooled over verified + derived             -> sensitivity check
    Only pools within a single family; mixed families return None (can't pool).
    correlation is converted to d before pooling into the smd family.
    """
    usable = [e for e in effects if e.get("status") in ("verified", "derived")]
    if not usable:
        return {"verified": None, "exploratory": None, "note": "no usable effects"}

    fams = set(e["family"] for e in usable)
    if "raw" in fams or len(fams) > 1:
        # Unit-bearing or mixed families can't be honestly pooled onto one axis.
        return {"verified": None, "exploratory": None,
                "note": "effects not poolable (mixed or unit-bearing metrics)"}

    def to_d(e):
        v = e["value"]
        if e["metric"] == "correlation":
            r = max(-0.999, min(0.999, v))
            return 2 * r / math.sqrt(1 - r * r)   # r -> d
        return v

    def iv_pool(subset):
        if not subset:
            return None
        num = den = 0.0
        for e in subset:
            d = to_d(e)
            se = (e["ci_high"] - e["ci_low"]) / (2 * 1.96)
            if se <= 0:
                continue
            w = 1.0 / (se * se)
            num += w * d
            den += w
        if den == 0:
            return None
        d = num / den
        se = math.sqrt(1.0 / den)
        return {"value": round(d, 3), "ci_low": round(d - 1.96 * se, 3),
                "ci_high": round(d + 1.96 * se, 3), "n_studies": len(subset)}

    verified = iv_pool([e for e in usable if e["status"] == "verified"])
    exploratory = iv_pool(usable)
    return {"verified": verified, "exploratory": exploratory, "note": None}


if __name__ == "__main__":
    # Offline gate tests — no API call. Verifies the GATE logic, which is the
    # part that matters most and needs no key.
    A = ("In this randomized trial, creatine improved strength versus placebo "
         "(Cohen's d = 0.55, 95% CI 0.30 to 0.80).")
    tests = [
        ("good verified", {"metric":"cohen_d","value":0.55,"ci_low":0.30,"ci_high":0.80,
                           "comparator":"vs placebo","direction":"benefit","unit":None,
                           "quote":"Cohen's d = 0.55, 95% CI 0.30 to 0.80"}, A, "verified"),
        ("no CI -> derived", {"metric":"cohen_d","value":0.55,"ci_low":None,"ci_high":None,
                              "comparator":"vs placebo","direction":"benefit","unit":None,
                              "quote":"Cohen's d = 0.55"}, "creatine Cohen's d = 0.55 vs placebo", "derived"),
        ("correlation -> derived", {"metric":"correlation","value":0.3,"ci_low":0.1,"ci_high":0.5,
                                    "comparator":None,"direction":"benefit","unit":None,
                                    "quote":"r = 0.3 (0.1-0.5)"}, "association r = 0.3 (0.1-0.5)", "derived"),
        ("implausible -> rejected", {"metric":"cohen_d","value":47.0,"ci_low":40.0,"ci_high":54.0,
                                     "comparator":None,"direction":None,"unit":None,
                                     "quote":"d = 47"}, "d = 47", "not_reported"),
        ("quote not in abstract -> rejected", {"metric":"cohen_d","value":0.55,"ci_low":0.3,"ci_high":0.8,
                                               "comparator":None,"direction":None,"unit":None,
                                               "quote":"d = 0.55 fabricated"}, A, "not_reported"),
        ("nothing reported", {"metric":"not_reported"}, "creatine may help strength.", "not_reported"),
    ]
    ok = 0
    for name, obj, ab,  exp in tests:
        r = validate(obj, ab)
        got = r["status"]
        mark = "OK " if got == exp else "XX "
        if got == exp: ok += 1
        print(f"{mark} {got:13} (exp {exp:13}) tier={r.get('tier')} | {name}")
    print(f"{ok}/{len(tests)} gate tests pass")

    print("\nPooling test:")
    effs = [
        {"status":"verified","family":"smd","metric":"cohen_d","value":0.55,"ci_low":0.30,"ci_high":0.80},
        {"status":"verified","family":"smd","metric":"cohen_d","value":0.48,"ci_low":0.22,"ci_high":0.74},
        {"status":"derived","family":"smd","metric":"cohen_d","value":0.72,"ci_low":0.34,"ci_high":1.10},
    ]
    print(json.dumps(pool(effs), indent=2))
