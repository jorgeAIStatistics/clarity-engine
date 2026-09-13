"""
Spanish translation of already-generated profile prose.

APPROACH: translate the ENGLISH prose that already exists — do NOT regenerate.
Grades, scores, study counts, PMIDs, effect sizes are language-neutral and stay
untouched. Only the generated text fields (explanation, appraisal, per-outcome
prose) are translated to Spanish and stored alongside the English as `*_es`.
Runs once per profile, cached, so it's paid a single time.

HONESTY IS PRESERVED IN THE PROMPT: medical/evidence nuance must survive
translation. Tier words, numbers, PMIDs, and hedging ("no clear benefit",
"preliminary", "may worsen") must map to Spanish phrasings that carry the SAME
careful meaning — never softened, never overstated. Numbers and units are copied
verbatim. This is translation, not reinterpretation.

Degrades safely: no API key -> returns None, nothing stored, UI falls back to
English.
"""

import os
import json

_MODEL = os.environ.get("CLARITY_LLM_MODEL", "claude-haiku-4-5-20251001")
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "translations.json")

_SYSTEM = (
    "You are a professional medical/scientific translator, English to Spanish "
    "(neutral Latin American Spanish). You translate supplement-evidence content "
    "for a general but intelligent audience.\n\n"
    "CRITICAL RULES:\n"
    "1. Preserve MEANING EXACTLY, especially evidence hedging. 'No clear benefit' "
    "-> 'sin beneficio claro', 'preliminary' -> 'preliminar', 'may worsen' -> "
    "'podría empeorar', 'well-tolerated in short trials' keeps its caution. NEVER "
    "make a claim stronger or weaker than the English.\n"
    "2. Copy ALL numbers, units, percentages, CIs, PMIDs, chemical formulas, and "
    "study designs (RCT, meta-analysis) VERBATIM — do not translate or alter them "
    "(you may translate 'meta-analysis' -> 'metanálisis' but keep any counts).\n"
    "3. Keep tier words consistent: Strong->Fuerte, Moderate->Moderada, "
    "Emerging->Emergente, Preliminary->Preliminar. Gold Standard->Estándar de oro.\n"
    "4. Return the SAME JSON structure with the SAME keys — translate only the "
    "string VALUES, never the keys. Preserve arrays and nesting exactly.\n"
    "5. Natural, clear Spanish — not word-for-word calque. But accuracy over "
    "fluency where they conflict.\n"
    "6. Output ONLY the translated JSON. No commentary, no markdown fences."
)


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
            json.dump(c, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _fingerprint(obj):
    import hashlib
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def _translate_json(payload):
    """Translate a JSON-serializable dict of English strings to Spanish."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not payload:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_MODEL, max_tokens=4000, system=_SYSTEM,
            messages=[{"role": "user", "content":
                       "Translate the string values in this JSON to Spanish, "
                       "keeping keys and structure identical:\n\n"
                       + json.dumps(payload, ensure_ascii=False, indent=2)}],
        )
        raw = resp.content[0].text.strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        return json.loads(raw)
    except Exception as e:
        print(f"  [translate] {type(e).__name__}: {e}")
        return None


def translate_profile(profile, force=False):
    """
    Translate a profile's prose to Spanish, storing `*_es` fields IN PLACE:
      - explanation_es      (mirror of explanation)
      - appraisal_es        (mirror of appraisal)
      - claims[i].summary_es and outcome_detail translations via explanation_es
    Grades/numbers/PMIDs untouched. Returns the profile. Cached by content hash.
    """
    name = (profile.get("name") or "").lower().strip()
    if not name:
        return profile

    cache = _load_cache()

    # --- explanation ---
    ex = profile.get("explanation")
    if ex and (force or not profile.get("explanation_es")):
        key = f"{name}::explanation::{_fingerprint(ex)}"
        if not force and key in cache:
            profile["explanation_es"] = cache[key]
        else:
            tr = _translate_json(ex)
            if tr:
                # Keep provenance flags from the original, don't translate them.
                for meta in ("_generated", "_model"):
                    if meta in ex:
                        tr[meta] = ex[meta]

                # IMPORTANT: `outcome` is also the frontend lookup identifier. A raw
                # translation pass used to translate that value (e.g. "sleep quality"
                # -> "calidad del sueño"), which meant the ES object could no longer
                # be matched back to the engine's English claim key. Preserve a stable
                # English `outcome_key` and keep the translated text in `outcome_es`.
                src_details = ex.get("outcome_detail") or []
                dst_details = tr.get("outcome_detail") or []
                if isinstance(src_details, list) and isinstance(dst_details, list):
                    for src, dst in zip(src_details, dst_details):
                        if not isinstance(src, dict) or not isinstance(dst, dict):
                            continue
                        src_outcome = src.get("outcome")
                        translated_outcome = dst.get("outcome")
                        if src_outcome:
                            dst["outcome_key"] = src_outcome
                            dst["outcome"] = src_outcome
                            if translated_outcome and translated_outcome != src_outcome:
                                dst["outcome_es"] = translated_outcome

                profile["explanation_es"] = tr
                cache[key] = tr

    # --- appraisal ---
    ap = profile.get("appraisal")
    if ap and (force or not profile.get("appraisal_es")):
        key = f"{name}::appraisal::{_fingerprint(ap)}"
        if not force and key in cache:
            profile["appraisal_es"] = cache[key]
        else:
            tr = _translate_json(ap)
            if tr:
                profile["appraisal_es"] = tr
                cache[key] = tr

    # --- per-claim one-line summaries (the template prose in each claim) ---
    claims = profile.get("claims") or []
    summaries = {c.get("outcome"): c.get("summary") for c in claims if c.get("summary")}
    if summaries and (force or not any(c.get("summary_es") for c in claims)):
        key = f"{name}::summaries::{_fingerprint(summaries)}"
        tr = cache[key] if (not force and key in cache) else _translate_json(summaries)
        if tr:
            cache[key] = tr
            for c in claims:
                if c.get("outcome") in tr:
                    c["summary_es"] = tr[c["outcome"]]

    _save_cache(cache)
    return profile


if __name__ == "__main__":
    # Smoke test against a cached profile if a key is set.
    import glob
    files = [f for f in glob.glob(os.path.join(os.path.dirname(__file__), "cache", "*.json"))
             if not any(k in f for k in ("explanations", "effect", "llm_", "directions",
                                          "outcomes", "pubchem", "appraisals", "citations",
                                          "translations", "pharmaco"))]
    prof = None
    for f in files:
        try:
            p = json.load(open(f))
            if p.get("explanation"):
                prof = p; break
        except Exception:
            pass
    if not prof:
        print("No profile with an explanation found to test.")
    elif not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY to test translation. Structure looks ready.")
    else:
        print("Translating:", prof.get("name"))
        translate_profile(prof, force=True)
        es = prof.get("explanation_es") or {}
        print("what_it_is (ES):", (es.get("what_it_is") or "")[:160])
