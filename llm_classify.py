"""
LLM population classifier — the last-mile fix for cases keyword rules can't
resolve (animal studies with human background-prose; human studies with no
trial-marker keywords).

Design principles (matching the engine's anti-hype architecture):
  - FACT EXTRACTION, NOT FABRICATION. The model is asked exactly one closed
    question: what population was this study performed in? It reads the real
    abstract and returns one label. It never writes claims or prose.
  - FIRES ONLY ON AMBIGUITY. Called only for studies classify.py marked
    population_confidence == "low". Obvious rat studies and obvious RCTs never
    hit the API, so cost and latency stay near zero.
  - CACHED BY PMID. Each study is classified once, ever. Re-runs are free.
  - DEGRADES SAFELY. If no API key, no network, or any error, it returns None
    and the caller keeps the keyword result. The engine still runs LLM-free.

Cost: ~300 input + ~5 output tokens per call on claude-haiku-4-5 ($1/$5 per
MTok) ≈ $0.0004 per ambiguous study, then cached. Pennies total.
"""

import os
import json
import time

_MODEL = os.environ.get("CLARITY_LLM_MODEL", "claude-haiku-4-5-20251001")
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "llm_population.json")

_VALID = {"human", "animal", "in_vitro", "not_a_study", "unknown"}

_SYSTEM = (
    "You classify biomedical study abstracts by the population the study was "
    "actually PERFORMED IN. Answer with exactly one word, no punctuation:\n"
    "  human       - the study's own subjects were human participants/patients\n"
    "  animal      - the study was done in animals (rats, mice, etc.)\n"
    "  in_vitro    - cells, tissue, or molecular only; no living subjects\n"
    "  not_a_study - review, editorial, commentary, or opinion (no original data)\n"
    "Judge by where the DATA came from, not by background mentions. A rat study "
    "whose intro says 'safe in healthy volunteers' is still 'animal'. A paper "
    "titled '...in rats' is 'animal' even if it discusses human implications."
)


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
        pass  # cache is an optimization; never fatal


def classify_population(pmid, title, abstract):
    """
    Return one of _VALID for this study, or None if the LLM is unavailable/errored
    (caller should then fall back to the keyword result).

    Cached by PMID on disk.
    """
    cache = _load_cache()
    key = str(pmid)
    if key in cache and cache[key] in _VALID:
        return cache[key]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None  # LLM-free fallback

    try:
        import anthropic
    except ImportError:
        return None

    text = f"Title: {title}\n\nAbstract: {abstract[:1500]}"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_MODEL,
            max_tokens=5,
            system=_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        raw = resp.content[0].text.strip().lower()
        # Normalize: take the first recognizable label token.
        label = "unknown"
        for w in raw.replace("-", "_").split():
            if w in _VALID:
                label = w
                break
        if label != "unknown":
            cache[key] = label
            _save_cache(cache)
        return label if label in _VALID else None
    except Exception:
        return None  # network/auth/rate error -> safe fallback


def resolve(study):
    """
    Given a classified study dict, upgrade its population field using the LLM
    ONLY when keyword confidence was low. Maps not_a_study -> is_review=True.
    Mutates and returns the study. No-op (returns unchanged) if the LLM is off
    or the case was high-confidence.
    """
    if study.get("population_confidence") != "low":
        return study
    pmid = study.get("pmid")
    if not pmid:
        return study

    verdict = classify_population(pmid, study.get("title", ""), study.get("abstract", ""))
    if verdict is None:
        return study  # keep keyword result

    if verdict == "not_a_study":
        study["is_review"] = True
    elif verdict in ("human", "animal", "in_vitro"):
        study["population"] = "animal" if verdict == "in_vitro" else verdict
        # in_vitro is treated as non-human for grading (animal-tier floor)
        if verdict == "in_vitro":
            study["design"] = "in_vitro"
            study["design_rank"] = 1
    study["population_confidence"] = "llm_resolved"
    return study


if __name__ == "__main__":
    # Offline smoke test (no API call unless key present).
    samples = [
        ("1", "Clopidogrel-Induced Gastric Injury in Rats Attenuated by BPC 157",
         "Although clopidogrel is safe in healthy volunteers, it can induce ulcers. "
         "We investigated the protective effect in rats."),
        ("2", "Effect of BPC-157 on Symptoms in Patients with Interstitial Cystitis",
         "We enrolled patients with interstitial cystitis in this pilot study."),
    ]
    for pid, t, a in samples:
        print(pid, "->", classify_population(pid, t, a))
