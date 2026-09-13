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
    "Your reader has NO medical or biology background — assume they don't know what "
    "ATP, a receptor, a peptide, or a cytokine is. Your job is to make the science "
    "genuinely understandable to that person, while keeping it accurate.\n\n"
    "WRITING FOR A NON-EXPERT (this is the core skill):\n"
    "- LEAD WITH PLAIN ENGLISH. Say what it does in everyday terms FIRST, then add "
    "the scientific detail. Bad: 'It upregulates eNOS, increasing NO-mediated "
    "vasodilation.' Good: 'It helps blood vessels relax and widen, so blood flows "
    "more easily — it does this by boosting a signal molecule called nitric oxide.'\n"
    "- EXPLAIN EVERY TECHNICAL TERM the first time you use it, in a few words, in "
    "plain language: 'ATP (the molecule your cells burn for quick energy)', "
    "'receptors (the docking points on cells that a molecule plugs into)'. Never "
    "assume prior knowledge.\n"
    "- USE ANALOGIES for mechanisms where they help — a lock and key, a thermostat, "
    "a delivery truck — as long as the analogy is accurate, not misleading.\n"
    "- Keep the real science present (the reader can handle depth if it's anchored), "
    "but a smart 16-year-old with no biology class should follow every sentence.\n"
    "- Short sentences. Avoid stacking three technical terms in one clause.\n\n"
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
    "as fact. It is better to say 'we don't yet know' than to guess.\n"
    "6. TONE — LEAD WITH THE SCIENCE, NOT THE CAVEAT. Make the writing engaging and "
    "mechanism-forward: open with how the compound works and what the animal/cell data "
    "actually show, because that is what the reader wants. State the evidence level "
    "ONCE, clearly, where it's most relevant (usually in what_studies_show / "
    "why_this_grade) — do NOT repeat 'no human evidence' or 'not proven in humans' in "
    "every field. The tier badge already shows it; you don't need to hammer it. "
    "Redundant caveats make the writing tedious.\n"
    "7. TRANSLATION FRAMING (important). When animal/preclinical data is promising, you "
    "MAY discuss how it *might* translate to humans — but ALWAYS as an OPEN QUESTION "
    "awaiting testing, never as an implied outcome. Correct: 'in rodent models it "
    "accelerated tendon healing; whether that translates to people has not yet been "
    "tested.' Incorrect: 'it heals tendons and should work in humans too.' The "
    "difference is a hypothesis vs. a promise — stay on the hypothesis side. This lets "
    "you be forward-looking and exciting without overstating.\n"
    "6. SAFETY IS THE HIGHEST-RISK SECTION. Never assert something is safe. Frame it as "
    "what the retrieved trials reported, and flag unknowns as unknowns "
    "('no adequately powered studies retrieved'; 'excluded from nearly every trial, so "
    "untested') — NEVER 'safe'. Absence of a reported harm is not evidence of safety.\n\n"
    "Return STRICT JSON only. Each explainer section has a SHORT one-line summary (for a "
    "collapsed card, ~10-16 words, plain and punchy) AND a longer detail (shown on expand). "
    "Both must be truthful and grounded; the line must say the same true thing as the detail.\n"
    "{\n"
    '  "what_it_is_line": "one line ~10-16 words: what it is, simplest true terms",\n'
    '  "what_it_is": "3-4 sentences: what it is chemically/biologically, where it comes from, what form people take",\n'
    '  "how_it_works_line": "one line ~10-16 words: the core mechanism, plain",\n'
    '  "how_it_works": "4-6 sentences: the mechanism — pathways, what it binds/affects, why that plausibly matters. Real biochemistry, plain terms. If a mechanism is unestablished, say so.",\n'
    '  "safety_line": "one line ~10-16 words: honest safety headline (never the word safe)",\n'
    '  "safety_detail": "2-3 sentences on what retrieved trials reported about tolerability/side effects and their limits (short duration, narrow populations). Never claim safety.",\n'
    '  "safety_bullets": [ "3-4 short items on specific UNKNOWNS/cautions — drug interactions, excluded populations (kidney disease, pregnancy, adolescence) — each framed as untested/unknown, not safe" ],\n'
    '  "chem_meaning": "2-3 sentences interpreting the chemistry (size, polarity/XLogP, solubility) in plain terms — why it behaves as it does in the body. Only if chemistry facts are provided; else empty string.",\n'
    '  "outcome_detail": [ {"outcome": str (exact given name), "grade": str, "what_studies_show": "2-4 sentences on what the studies found and in whom — real designs/populations/years from the data. Never invent a study.", "why_this_grade": "1-2 plain sentences on why this grade."} ],\n'
    '  "evidence_base": "3-4 sentences: human vs animal, dominant study types, recency, what that means for confidence.",\n'
    '  "open_questions": "2-3 sentences on gaps VISIBLE IN THE RECORDS GIVEN — which populations appear and which do not, whether durations are short, whether outcomes rest on few trials. You see only a SAMPLE (~40 abstracts/outcome), so NEVER claim understudied in the field at large — only what is or is not in the records provided."\n'
    "}\n"
    "outcome_detail MUST include one entry per outcome given, using exact outcome names. "
    "Ground every claim in the records provided — cite a study's design, year, population, or "
    "sample size because those are given. NEVER invent a study, author, or number not in the data."
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
    cache_key = f"{name}::{profile.get('generated_by', 'v?')}::rich7::{_evidence_fingerprint(profile)}"

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
        if chem.get("xlogp") is not None: bits.append(f"XLogP {chem['xlogp']} (lipophilicity; negative = water-loving)")
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
