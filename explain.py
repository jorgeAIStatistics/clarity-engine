"""
Grounded compound explanations.

Generates the rich editorial content users want — what the compound is, how it
works in the body, main/secondary/emerging benefits — but with EVERY efficacy
claim constrained by the engine's REAL grades. The model is told exactly which
outcomes graded Strong/Moderate/Emerging and which are animal-only, and must
write consistent with that. It cannot say "proven for anxiety" if the engine
graded anxiety Emerging.

Why this is cheap AND safer than the mock brochure:
  - Haiku, ~500 words out => ~half a cent per compound.
  - Generated ONCE, cached by compound in cache/explanations.json => free after.
  - Efficacy claims are grounded in the grades (guardrail against hype).
  - Mechanism/biochem is stable textbook content a small model gets right.

Honesty structure the prompt enforces:
  - "what_it_is" + "how_it_works": stable science, safe to explain.
  - "benefits": SPLIT into proven (Strong/Moderate human), promising
    (Emerging / animal-only), and each tagged with the engine's tier so the
    reader always sees the evidence level next to the claim.
  - A required "caveats" line for anything injected / research-chemical.

Degrades safely: no key => returns None, UI just omits the explanation section.
"""

import os
import json

_MODEL = os.environ.get("CLARITY_LLM_MODEL", "claude-haiku-4-5-20251001")
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "explanations.json")

_SYSTEM = (
    "You are a careful biomedical explainer for a supplement/peptide evidence app. "
    "You write clear, engaging explanations for a general but intelligent reader — "
    "enough biological/chemical detail to actually understand what the compound does "
    "in the body, without jargon walls.\n\n"
    "CRITICAL HONESTY RULES:\n"
    "1. You are GIVEN the app's evidence grades per outcome. Your efficacy claims "
    "MUST match them. Never call something 'proven' or 'effective' unless its grade "
    "is Strong or Moderate with human evidence. Emerging/animal-only outcomes must be "
    "described as preliminary, promising, or unproven in humans — never as established.\n"
    "2. Mechanism/biochemistry (what it is, how it works) is fine to explain from "
    "established science, but do NOT invent specific clinical effects.\n"
    "3. For injectable peptides or research chemicals, include a brief safety caveat.\n"
    "4. You are shown only a SAMPLE of retrieved abstracts (~40 per outcome), NOT the "
    "complete literature. Never make claims about what research does or does not exist "
    "in the field overall. Describe only what the provided records show.\n"
    "5. If evidence is thin, say so plainly. Do not fill gaps with speculation stated "
    "as fact. It is better to say 'we don't yet know' than to guess.\n\n"
    "Return STRICT JSON only:\n"
    "{\n"
    '  "what_it_is": "3-4 sentences: what the compound is chemically/biologically, where it comes from, what form people take",\n'
    '  "how_it_works": "4-6 sentences: the mechanism in the body — pathways, what it binds or affects, why that would plausibly matter. Plain terms, real biochemistry.",\n'
    '  "outcome_detail": [ {"outcome": str (must match a given outcome name exactly), "grade": str, "what_studies_show": "2-4 sentences describing what the actual studies found and in whom — reference real study designs/populations/years from the data given (e.g. \'a 2024 meta-analysis of 16 randomized trials in older adults\'). Never invent a study.", "why_this_grade": "1-2 sentences explaining, in plain language, why the evidence earned this grade — use the limitations given."} ],\n'
    '  "evidence_base": "3-4 sentences characterizing the research overall: how much is human vs animal, what kinds of studies dominate, how recent, and what that means for confidence.",\n'
    '  "emerging_research": "3-4 sentences on recent/novel directions, clearly framed as early",\n'
    '  "open_questions": "2-3 sentences on gaps VISIBLE IN THE STUDY RECORDS GIVEN TO YOU — e.g. which populations appear in the retrieved studies and which do not, whether trial durations shown are short, whether outcomes rest on few trials. You are seeing only a SAMPLE of the literature (about 40 abstracts per outcome), so you CANNOT know what research exists globally. NEVER claim something is understudied, unknown, or lacking long-term data in the field at large — only describe what is or is not present in the records provided, and say so explicitly (e.g. \'among the studies retrieved here, none followed participants beyond 12 weeks\').",\n'
    '  "caveats": "2-3 sentences: safety, quality, interactions, or who should be cautious"\n'
    "}\n"
    "outcome_detail MUST include one entry per outcome given, using the exact outcome names. "
    "Ground every specific claim in the study records provided — you may cite a study's design, "
    "year, population, or sample size because those are given to you. NEVER invent a study, "
    "author, or number that is not in the data."
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


def _save_cache(cache):
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def _grades_summary(profile, max_studies_per_outcome=6):
    """
    Grounding text fed to the model. Now includes the ACTUAL study records
    (design, year, population, sample size, title) — this is what lets the prose
    be specific ("a 2024 meta-analysis of 16 RCTs") instead of generic. Studies
    are already sorted human-first, strongest-design-first by _study_records.
    """
    lines = []
    for c in profile.get("claims", []):
        he = c.get("headline_effect")
        eff = ""
        if he and he.get("value") is not None:
            ci = ""
            if he.get("ci_low") is not None and he.get("ci_high") is not None:
                ci = f" [{he['ci_low']} to {he['ci_high']}]"
            eff = f", pooled effect {he.get('metric')} {he.get('value')}{ci}"
        L = c.get("layers", {})
        lines.append(
            f"\nOUTCOME: {c['outcome']} — graded {c['tier']} "
            f"({L.get('n_human_studies', 0)} human, {L.get('n_animal_studies', 0)} animal "
            f"of {c.get('n_studies', 0)} studies{eff})"
        )
        for r in (c.get("grade_reasons") or [])[:2]:
            lines.append(f"  limitation: {r}")
        for s in (c.get("studies") or [])[:max_studies_per_outcome]:
            n = f", n={s['n']}" if s.get("n") else ""
            yr = f" {s['year']}" if s.get("year") else ""
            lines.append(
                f"  study:{yr} [{s.get('design','?')}, {s.get('population','?')}{n}] "
                f"{(s.get('title') or '')[:110]}"
            )
    return "\n".join(lines) if lines else "(no gradeable outcomes found)"


def explain(profile, force=False):
    """
    Generate (or load cached) explanation for a compound profile.
    Returns the explanation dict, or None if unavailable.
    Cached by compound name + generated_by (so a re-graded compound re-explains).
    """
    name = profile.get("name", "").strip().lower()
    if not name:
        return None
    cache_key = f"{name}::{profile.get('generated_by', 'v?')}::rich4::{_evidence_fingerprint(profile)}"

    cache = _load_cache()
    if not force and cache_key in cache:
        return cache[cache_key]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        return None

    category = profile.get("category", "supplement")
    grades = _grades_summary(profile)
    is_injectable = category in ("peptide",)

    chem = profile.get("chemistry") or {}
    chem_block = ""
    if chem:
        bits = []
        if chem.get("formula"): bits.append(f"molecular formula {chem['formula']}")
        if chem.get("weight"): bits.append(f"molecular weight {chem['weight']}")
        if chem.get("iupac_name"): bits.append(f"IUPAC name {chem['iupac_name']}")
        if chem.get("synonyms"): bits.append("also known as " + ", ".join(chem["synonyms"][:4]))
        if bits:
            chem_block = ("\nVERIFIED CHEMISTRY (from PubChem — use these exact facts, "
                          "do not contradict or invent alternatives):\n  " + "; ".join(bits) + "\n")

    user = (
        f"Compound: {profile.get('name')}\n"
        f"{chem_block}"
        f"Category: {category}"
        f"{' (injectable peptide / often research-chemical — include safety caveat)' if is_injectable else ''}\n\n"
        f"The app's evidence grades for this compound (your efficacy claims MUST match these):\n"
        f"{grades}\n\n"
        f"Overall tier: {profile.get('tier')}. "
        f"Write the explanation JSON now, keeping every efficacy claim consistent with the grades above."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_MODEL, max_tokens=4000, system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text.strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        result = json.loads(raw)
        # tag provenance so the UI can label it clearly
        result["_generated"] = True
        result["_model"] = _MODEL
        cache[cache_key] = result
        _save_cache(cache)
        return result
    except json.JSONDecodeError as e:
        # Almost always means the response hit max_tokens and the JSON is cut off.
        print(f"  [explain] {name}: JSON parse failed ({e}). "
              f"Response was {len(raw) if 'raw' in dir() else 0} chars — likely truncated.")
        return None
    except Exception as e:
        print(f"  [explain] {name}: {type(e).__name__}: {e}")
        return None


if __name__ == "__main__":
    # Smoke test against a cached profile if present.
    import glob
    files = glob.glob(os.path.join(os.path.dirname(__file__), "cache", "*.json"))
    prof = None
    for f in files:
        if "explanations" in f or "effect" in f or "llm_" in f:
            continue
        try:
            prof = json.load(open(f)); break
        except Exception:
            pass
    if prof:
        print("Explaining:", prof.get("name"))
        out = explain(prof)
        print(json.dumps(out, indent=2) if out else "(no key set — would generate with ANTHROPIC_API_KEY)")
    else:
        print("No cached profile found to test.")
