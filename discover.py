"""
Outcome discovery — so you can research ANY topic without hand-listing outcomes.

Problem: the base runner needs you to say `run.py "creatine" ... "strength" "cognition"`.
For a real product, the user just types "creatine" — the engine must figure out
WHICH outcomes that substance is actually studied for.

Approach (LLM-free, transparent): scan the retrieved abstracts for known health-
outcome keywords and rank them by how often they appear. The most-mentioned
outcomes become the claims we grade. Simple, auditable, and good enough to launch;
an LLM can refine it later.
"""

import os
import re
import json
from collections import Counter

# A starter vocabulary of health outcomes and the phrases that signal them.
# Expand this over time — it's a transparent, editable asset (part of your moat).
OUTCOME_KEYWORDS = {
    "muscle strength": [r"\bstrength\b", r"\b1[- ]?rm\b", r"\bpower output\b", r"\bmuscular\b"],
    "muscle growth": [r"\bhypertroph", r"\blean (?:body )?mass\b", r"\bmuscle mass\b"],
    "endurance": [r"\bendurance\b", r"\baerobic\b", r"\bvo2\b", r"\btime to exhaustion\b"],
    # Beta-alanine, caffeine, sodium bicarbonate etc. are studied for high-intensity
    # PERFORMANCE, which fell between "endurance" (aerobic) and "muscle strength"
    # (1RM). With nowhere to land, their real outcome was never discovered.
    "exercise performance": [r"\bexercise performance\b", r"\bsports? performance\b",
                             r"\bhigh[- ]intensity\b", r"\banaerobic\b",
                             r"\bathletic performance\b", r"\bphysical performance\b",
                             r"\bergogenic\b", r"\btime trial\b", r"\bsprint\b",
                             r"\bfatigue resistance\b", r"\bwork capacity\b"],
    "cognition": [r"\bcognit", r"\bmemory\b", r"\bmental performance\b", r"\bexecutive function\b"],
    "sleep quality": [r"\bsleep\b", r"\binsomnia\b", r"\bsleep quality\b"],
    # NOT plain \bstress\b: "oxidative stress" appears in nearly every antioxidant
    # abstract and was voting for psychological anxiety on every such compound.
    "stress / anxiety": [r"(?<!oxidative )(?<!nitrosative )(?<!endoplasmic reticulum )\bstress\b",
                         r"\banxiet", r"\bcortisol\b", r"\bperceived stress\b",
                         r"\bpsychological stress\b"],
    "mood / depression": [r"\bmood\b", r"\bdepress", r"\bwell[- ]?being\b"],
    "testosterone / hormones": [r"\btestosterone\b", r"\bhormon", r"\blibido\b"],
    "tendon / tissue healing": [r"\btendon\b", r"\bligament\b", r"\bwound heal", r"\btissue repair\b", r"\bhealing\b"],
    "gut / digestion": [r"\bgut\b", r"\bintestin", r"\bgastro", r"\bmicrobiom"],
    "inflammation": [r"\binflammat", r"\bcytokine\b", r"\boxidative stress\b"],
    "cardiovascular": [r"\bblood pressure\b", r"\bcardiovascular\b", r"\bheart rate\b", r"\bcholesterol\b", r"\blipid\b"],
    "blood sugar": [r"\bglucose\b", r"\binsulin\b", r"\bglyc(?:a|e)mi", r"\bhba1c\b"],
    "immune function": [r"\bimmune\b", r"\binfection\b", r"\bimmunit"],
    # TAXONOMY GAPS — compounds whose real outcome had no category graded on
    # noise instead. Collagen (skin, joints), glucosamine (joints), biotin
    # (hair), milk thistle (liver), lutein (eye), tongkat ali (sexual function)
    # were all affected: their actual literature had nowhere to land.
    "thyroid function": [r"\bthyroid\b", r"\bTSH\b", r"\bT3\b", r"\bT4\b",
                         r"\bhypothyroid", r"\bhyperthyroid", r"\bgoiter\b",
                         r"\bthyroxine\b"],
    "anemia / iron status": [r"\banemia\b", r"\banaemia\b", r"\bferritin\b",
                             r"\bhemoglobin\b", r"\bhaemoglobin\b",
                             r"\biron deficiency\b", r"\biron status\b"],
    "skin / appearance": [r"\bskin\b", r"\bwrinkl", r"\bdermal\b", r"\belasticity\b",
                          r"\bhydration of the skin\b", r"\bphotoaging\b",
                          r"\bcollagen density\b", r"\bdermatolog"],
    "joint / arthritis": [r"\bjoint\b", r"\bosteoarthrit", r"\barthrit",
                          r"\bcartilage\b", r"\bknee pain\b", r"\bWOMAC\b",
                          r"\bjoint discomfort\b", r"\bstiffness\b"],
    "bone health": [r"\bbone mineral density\b", r"\bBMD\b", r"\bosteoporo",
                    r"\bfracture\b", r"\bbone loss\b", r"\bbone health\b"],
    "hair / nails": [r"\bhair loss\b", r"\balopecia\b", r"\bhair growth\b",
                     r"\bnail\b", r"\bhair thickness\b"],
    "liver health": [r"\bliver\b", r"\bhepat", r"\bNAFLD\b", r"\bALT\b",
                     r"\bsteatosis\b", r"\bcirrhos"],
    "kidney function": [r"\bkidney\b", r"\brenal\b", r"\beGFR\b",
                        r"\bcreatinine clearance\b", r"\bnephro"],
    "eye / vision": [r"\bvision\b", r"\bmacular\b", r"\bretina", r"\bocular\b",
                     r"\bvisual acuity\b", r"\bcataract\b", r"\bdry eye\b"],
    "sexual function": [r"\berectile\b", r"\blibido\b", r"\bsexual function\b",
                        r"\bsperm\b", r"\bfertilit", r"\bIIEF\b"],
    "recovery / soreness": [r"\bmuscle damage\b", r"\bsoreness\b", r"\bDOMS\b",
                            r"\brecovery\b", r"\bcreatine kinase\b"],
    "blood pressure": [r"\bblood pressure\b", r"\bhypertens", r"\bsystolic\b",
                       r"\bdiastolic\b"],
    "cholesterol / lipids": [r"\bcholesterol\b", r"\bLDL\b", r"\bHDL\b",
                             r"\btriglycerid", r"\blipid profile\b", r"\bdyslipid"],
    "weight / fat loss": [r"\bweight loss\b", r"\bfat mass\b", r"\bbody fat\b", r"\badipos"],
}


def discover_outcomes(studies, top_n=5, min_hits=2):
    """
    Given retrieved studies, return the most-studied outcomes for this topic.
    Returns a list of outcome names, most-supported first.
    """
    # Count how many STUDIES support each outcome, not raw word occurrences.
    # Counting occurrences in one merged blob let a single paper repeating
    # "insulin" outrank ten papers each mentioning performance once — which is
    # how beta-alanine ended up graded on gut, blood sugar and inflammation
    # instead of exercise performance. Title matches count double: an outcome in
    # the title is what the paper is ABOUT, not something it mentions in passing.
    counts = Counter()
    for outcome, patterns in OUTCOME_KEYWORDS.items():
        supporting = 0
        for st in studies:
            title = (st.get("title") or "").lower()
            body = f"{title} {(st.get('abstract') or '').lower()}"
            if any(re.search(p, title) for p in patterns):
                supporting += 2
            elif any(re.search(p, body) for p in patterns):
                supporting += 1
        # An outcome must be the SUBJECT of at least one paper (title match),
        # not merely mentioned in passing. Beta-alanine kept "blood sugar"
        # because two abstracts said "insulin" incidentally — then 27 of 31
        # retrieved papers for that outcome were rejected as off-topic, because
        # the outcome never existed for this compound.
        # Accept an outcome if EITHER a paper is titled about it, OR at least
        # three separate abstracts discuss it. Requiring a title match alone was
        # too strict — it stripped legitimate secondary outcomes (beta-alanine
        # lost muscle strength). Phantom outcomes typically have only one or two
        # incidental mentions, so a three-abstract floor still excludes them.
        in_title = any(any(re.search(p, (st.get("title") or "").lower())
                           for p in patterns) for st in studies)
        n_abstracts = sum(
            1 for st in studies
            if any(re.search(p, (st.get("abstract") or "").lower()) for p in patterns))
        if supporting >= min_hits and (in_title or n_abstracts >= 3):
            counts[outcome] = supporting
    # Rank primarily by how many papers are TITLED about the outcome. Generic
    # terms ("inflammation", "cardiovascular", "blood sugar") appear in almost
    # every abstract, so abstract-weighted totals buried the specific outcome
    # each compound is actually taken for. A title is what a paper is ABOUT.
    title_counts = {}
    for outcome in counts:
        patterns = OUTCOME_KEYWORDS[outcome]
        title_counts[outcome] = sum(
            1 for st in studies
            if any(re.search(p, (st.get("title") or "").lower()) for p in patterns))
    ranked = [o for o, _ in sorted(
        counts.items(), key=lambda kv: (-title_counts.get(kv[0], 0), -kv[1]))][:top_n]
    # Fallback: if nothing matched (rare/novel compound), return a generic bucket
    # so the profile still generates honestly ("general effects, limited data").
    return ranked or ["general / emerging effects"]


if __name__ == "__main__":
    import pubmed, classify
    studies = classify.classify_all(pubmed._parse_articles(open("tests/sample_pubmed.xml").read()))
    print("Discovered outcomes:", discover_outcomes(studies))

# ---------------------------------------------------------------------------
# ROOT FIX: LLM-read outcome discovery.
#
# The keyword taxonomy required anticipating every compound's use case in
# advance. Collagen graded on gut and mood because no skin or joint category
# existed; iodine on testosterone because no thyroid category existed; melatonin
# on inflammation because that word appears in nearly every abstract. Each fix
# was per-compound or per-category, and there was always another one.
#
# Reading the titles answers the question directly: what are these studies
# actually measuring? No taxonomy to maintain, no category to forget.
#
# Falls back to keyword discovery with no API key, so the engine still runs.
# ---------------------------------------------------------------------------

# Canonical vocabulary. The LLM is asked to PREFER these names so outcomes stay
# consistent across the catalog — otherwise one compound says "sleep quality",
# another "sleep", a third "insomnia", and you can never answer "which compounds
# help sleep?" (the goal-pages feature). It may coin a new name when nothing
# fits, which is what removes the old requirement to anticipate every use case.
CANONICAL_OUTCOMES = sorted(OUTCOME_KEYWORDS.keys())

_DISCOVER_SYSTEM = (
    "You identify what health outcomes a body of research measures.\n\n"
    "Given study titles for one compound, return the 3-5 outcomes those studies "
    "actually investigate — the endpoints being measured, not the mechanisms.\n\n"
    "RULES:\n"
    "1. Return outcomes SUPPORTED BY THE TITLES. Do not add outcomes the "
    "compound is popularly claimed to help if the studies do not measure them.\n"
    "2. PREFER a name from this list when one fits, so outcomes stay consistent "
    "across compounds:\n" + ", ".join(CANONICAL_OUTCOMES) + "\n"
    "   If none fits, coin a short consumer-readable name "
    "(e.g. 'menopausal symptoms', 'allergy symptoms'). Never use jargon.\n"
    "3. Order by how central each outcome is — what most titles are ABOUT first.\n"
    "4. Merge near-duplicates into one outcome.\n"
    "5. Skip outcomes mentioned only once in passing.\n"
    "6. Output ONLY a JSON array of strings. No commentary.\n\n"
    'Example: ["sleep quality", "stress / anxiety", "inflammation"]'
)


_DISCOVER_CACHE = os.path.join(os.path.dirname(__file__), "cache", "outcomes.json")


def _dcache_load():
    try:
        with open(_DISCOVER_CACHE) as f:
            return json.load(f)
    except Exception:
        return {}


def _dcache_save(c):
    try:
        os.makedirs(os.path.dirname(_DISCOVER_CACHE), exist_ok=True)
        with open(_DISCOVER_CACHE, "w") as f:
            json.dump(c, f, indent=2)
    except Exception:
        pass


def discover_outcomes_llm(studies, topic="", max_titles=40):
    """Read the titles and return the outcomes they measure. None on failure."""
    import json as _json
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not studies:
        return None

    # Cache on the study set: same papers -> same outcomes, no repeat cost.
    import hashlib
    pmids = ",".join(sorted(str(s.get("pmid")) for s in studies if s.get("pmid")))
    ckey = f"{topic}::" + hashlib.sha1(pmids.encode()).hexdigest()[:12]
    cache = _dcache_load()
    if ckey in cache:
        return cache[ckey]
    titles = [(s.get("title") or "").strip() for s in studies if s.get("title")]
    titles = [t for t in titles if t][:max_titles]
    if len(titles) < 3:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=os.environ.get("CLARITY_LLM_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=300, system=_DISCOVER_SYSTEM,
            messages=[{"role": "user", "content":
                       f"Compound: {topic}\n\nSTUDY TITLES:\n"
                       + "\n".join(f"- {t}" for t in titles)}],
        )
        raw = resp.content[0].text.strip()
        start, end = raw.find("["), raw.rfind("]")
        if start < 0 or end < 0:
            return None
        outs = _json.loads(raw[start:end + 1])
        outs = [str(o).strip().lower() for o in outs if str(o).strip()][:4]
        if not outs:
            return None
        cache[ckey] = outs
        _dcache_save(cache)
        return outs
    except Exception as e:
        print(f"  [discover] {topic}: {type(e).__name__}: {e}")
        return None


def discover(studies, topic="", top_n=4, min_hits=2):
    """
    Preferred entry point: LLM-read outcomes, keyword matching as fallback.
    """
    outs = discover_outcomes_llm(studies, topic)
    if outs:
        return outs
    return discover_outcomes(studies, top_n=top_n, min_hits=min_hits)

def assign_to_outcome(study, outcome):
    """
    Does this study address this outcome? Used to partition ONE retrieval across
    outcomes locally, instead of running a separate PubMed search per outcome.

    Five searches per compound (one to discover outcomes, one per outcome) meant
    ~15 PubMed round-trips and ~55s per compound. The retrievals overlapped
    heavily anyway. One broad fetch plus local partitioning gets the same studies
    for a fifth of the work.

    Uses the canonical keyword patterns when the outcome is one of ours, and
    falls back to token matching for outcomes the LLM coined.
    """
    blob = f"{study.get('title','')} {study.get('abstract','')}".lower()
    patterns = OUTCOME_KEYWORDS.get(outcome)
    if patterns:
        return any(re.search(p, blob) for p in patterns)
    # LLM-coined outcome ("menopausal symptoms"): require the meaningful tokens.
    stop = {"and", "or", "the", "of", "in", "for", "function", "health", "/"}
    tokens = [t for t in re.split(r"[^a-z0-9]+", outcome.lower())
              if t and t not in stop and len(t) > 3]
    if not tokens:
        return False
    return any(t in blob for t in tokens)
