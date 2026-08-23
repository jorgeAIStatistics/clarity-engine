"""
Critical appraisal agent — the "how this could be wrong" layer.

WHAT THIS IS: a methodologist's second read of each compound's evidence base.
Not more claims about what a compound does — the opposite. It looks at the
STRUCTURE of the evidence (who ran the studies, how big, how old, what designs,
whether mechanism plausibly supports the outcome) and names the weaknesses a
skeptical reviewer would raise but a tier label can't express.

WHY IT'S DIFFERENT FROM SPECULATION: every observation must be derivable from
the study records the engine already collected. "Most trials are small pilots"
is checkable against n values. "This rests on one research group" is checkable
against author/title patterns. "Mechanism is plausible but the clinical leap is
large" is a reasoning claim about material we hold. Nothing here invents a
finding, a benefit, or a study.

This is the honest version of "extra thinking per compound": it makes the
product MORE trustworthy, not less, and no consumer supplement site does it.

Cost: one Haiku call per compound, cached. ~a cent each.
Degrades to None with no API key — UI omits the section.
"""

import os
import json

_MODEL = os.environ.get("CLARITY_LLM_MODEL", "claude-haiku-4-5-20251001")
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "appraisals.json")

_SYSTEM = (
    "You are a careful research methodologist reviewing the evidence base for a "
    "supplement or peptide. Your job is ADVERSARIAL: identify how this body of "
    "evidence could be misleading, and what a skeptical expert would push back on. "
    "You are NOT evaluating whether the compound works — you are evaluating whether "
    "the EVIDENCE can support the conclusions drawn from it.\n\n"
    "You are given: the engine's grade per outcome, and the actual study records "
    "(design, year, population, sample size, title) that produced those grades.\n\n"
    "ABSOLUTE RULES:\n"
    "1. Every observation must be derivable from the study records given. If you "
    "note 'most trials are small', the sample sizes must show that. If you note "
    "'the literature is dated', the years must show that.\n"
    "2. NEVER speculate about unobserved benefits, novel mechanisms, or future "
    "applications. That is not your job and it would be dishonest.\n"
    "3. NEVER invent a study, author, funding source, or number. If you cannot "
    "verify something from the records, do not assert it. You may note that "
    "something is NOT VISIBLE in the records (e.g. 'funding sources are not "
    "available in these records') — that is honest.\n"
    "4. You see only a sample of retrieved abstracts (~40 per outcome), not the "
    "complete literature. Frame observations as about the retrieved evidence.\n"
    "5. Be specific and useful, not generically cautious. 'More research is "
    "needed' is worthless. 'Six of eight trials enrolled under 30 participants, "
    "so a single outlier study could shift the pooled result' is useful.\n"
    "6. If the evidence base is genuinely solid, SAY SO. Do not manufacture "
    "criticism. An honest appraisal of strong evidence is 'these are the residual "
    "limitations, and they are minor.'\n\n"
    "Return STRICT JSON only:\n"
    "{\n"
    '  "headline": "One sentence: the single most important caveat a reader should '
    'hold in mind about this evidence base. If the evidence is solid, say that plainly.",\n'
    '  "concerns": [ {"issue": "short label (3-6 words)", "detail": "2-3 sentences '
    'explaining the concern, citing the specific pattern in the records that shows it", '
    '"severity": "high" | "moderate" | "low"} ],\n'
    '  "mechanism_check": "2-3 sentences: does the proposed biological mechanism '
    'plausibly support the CLINICAL outcomes claimed, or is there a large inferential '
    'leap? Be specific about where the leap is, if any.",\n'
    '  "strongest_counterargument": "2-3 sentences: the best case a well-informed '
    'skeptic would make that this compound does not do what the grades suggest. Steelman it.",\n'
    '  "what_would_change_the_picture": "1-2 sentences: what specific kind of study '
    'would meaningfully resolve the uncertainty here."\n'
    "}\n"
    "Provide 2-5 concerns. Order them by severity, highest first."
)


def _evidence_fingerprint(profile):
    """
    Hash of the graded evidence. Cached prose MUST invalidate when the grades or
    study sets change — otherwise a regenerated profile re-attaches an old
    explanation describing tiers and studies that no longer exist (a Preliminary
    badge above a paragraph arguing for Moderate). Keyed on tier, counts, and
    the PMIDs actually behind each outcome.
    """
    import hashlib
    parts = []
    for c in profile.get("claims", []):
        L = c.get("layers", {})
        pmids = ",".join(sorted(str(s.get("pmid")) for s in (c.get("studies") or [])))
        parts.append(f"{c.get('outcome')}|{c.get('tier')}|{c.get('n_studies')}|"
                     f"{L.get('n_human_studies')}|{L.get('n_animal_studies')}|{pmids}")
    blob = "||".join(parts) + f"||{profile.get('tier')}"
    return hashlib.sha1(blob.encode()).hexdigest()[:10]


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


def _evidence_dossier(profile, max_studies=10):
    """
    The full picture the appraiser reasons over: grades + study composition.
    Deliberately includes MORE studies per outcome than the explainer sees,
    because structural patterns (sizes, years, designs) are the whole point.
    """
    lines = []
    for c in profile.get("claims", []):
        L = c.get("layers", {})
        studies = c.get("studies") or []
        ns = [s["n"] for s in studies if s.get("n")]
        years = [int(s["year"]) for s in studies if str(s.get("year", "")).isdigit()]
        designs = {}
        for s in studies:
            designs[s.get("design", "?")] = designs.get(s.get("design", "?"), 0) + 1

        lines.append(f"\nOUTCOME: {c['outcome']} — graded {c['tier']}")
        lines.append(f"  composition: {L.get('n_human_studies', 0)} human, "
                     f"{L.get('n_animal_studies', 0)} animal, {c.get('n_studies', 0)} total")
        if designs:
            lines.append("  designs: " + ", ".join(f"{k}×{v}" for k, v in
                                                   sorted(designs.items(), key=lambda x: -x[1])))
        if ns:
            lines.append(f"  sample sizes reported: {sorted(ns)} "
                         f"(median {sorted(ns)[len(ns)//2]}, {len(ns)} of {len(studies)} studies report n)")
        else:
            lines.append("  sample sizes: none extractable from these abstracts")
        if years:
            lines.append(f"  year range: {min(years)}–{max(years)}")
        he = c.get("headline_effect")
        if he and he.get("value") is not None:
            lines.append(f"  pooled effect: {he.get('metric')} {he.get('value')} "
                         f"[{he.get('ci_low')} to {he.get('ci_high')}]")
        else:
            lines.append("  pooled effect: none extractable")
        for r in (c.get("grade_reasons") or [])[:2]:
            lines.append(f"  engine noted: {r}")
        for s in studies[:max_studies]:
            n = f", n={s['n']}" if s.get("n") else ""
            lines.append(f"  - {s.get('year','?')} [{s.get('design','?')}, "
                         f"{s.get('population','?')}{n}] {(s.get('title') or '')[:100]}")
    return "\n".join(lines) if lines else "(no gradeable outcomes)"


def appraise(profile, force=False):
    """
    Generate (or load cached) critical appraisal. Returns dict or None.
    Cached by compound + engine version.
    """
    name = (profile.get("name") or "").strip().lower()
    if not name:
        return None
    key = f"{name}::{profile.get('generated_by', 'v?')}::appraise1::{_evidence_fingerprint(profile)}"

    cache = _load_cache()
    if not force and key in cache:
        return cache[key]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    category = profile.get("category", "supplement")
    user = (
        f"Compound: {profile.get('name')} (category: {category})\n"
        f"Overall tier: {profile.get('tier')}\n"
        f"{'NOTE: injectable peptide, often obtained grey-market and not approved for human use.' if category == 'peptide' else ''}\n"
        f"\nEVIDENCE BASE:\n{_evidence_dossier(profile)}\n\n"
        "Write the critical appraisal JSON now. Ground every observation in the "
        "records above."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_MODEL, max_tokens=2500, system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text.strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        result = json.loads(raw)
        result["_generated"] = True
        result["_model"] = _MODEL
        cache[key] = result
        _save_cache(cache)
        return result
    except json.JSONDecodeError as e:
        print(f"  [appraise] {name}: JSON parse failed ({e}) — likely truncated.")
        return None
    except Exception as e:
        print(f"  [appraise] {name}: {type(e).__name__}: {e}")
        return None


if __name__ == "__main__":
    import glob
    for f in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "cache", "*.json"))):
        b = os.path.basename(f)
        if any(k in b for k in ("effect_sizes", "llm_population", "explanations",
                                "appraisals", "pubchem")):
            continue
        prof = json.load(open(f))
        print("Dossier the appraiser would see for:", prof.get("name"))
        print(_evidence_dossier(prof)[:1800])
        break
