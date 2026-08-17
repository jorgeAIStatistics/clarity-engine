"""
Stage 2 — Classify each study by evidence weight.

This is deterministic, rule-based classification from PubMed metadata + abstract
text. No LLM needed for the core signal (publication type is the strongest cue).
An LLM can LATER refine population/outcome extraction, but the evidence-hierarchy
logic below is the backbone and is fully transparent + auditable.

Evidence hierarchy (strongest -> weakest):
  systematic_review / meta_analysis  >  rct  >  cohort/observational
  >  case_report  >  animal / in_vitro
"""

import re

# Map PubMed PublicationType strings to our internal design categories.
_DESIGN_BY_PUBTYPE = {
    "meta-analysis": "meta_analysis",
    "systematic review": "systematic_review",
    "randomized controlled trial": "rct",
    "controlled clinical trial": "rct",
    "clinical trial": "trial",
    "observational study": "observational",
    "cohort studies": "observational",
    "case reports": "case_report",
}

# Rank used for sorting / picking the strongest evidence in a cluster.
DESIGN_RANK = {
    "meta_analysis": 6,
    "systematic_review": 6,
    "rct": 5,
    "trial": 4,
    "observational": 3,
    "case_report": 2,
    "animal": 1,
    "in_vitro": 1,
    "unknown": 0,
}

_ANIMAL_HINTS = re.compile(r"\b(rat|rats|mice|mouse|rodent|murine|canine|porcine|feline|bovine|equine|in vitro|in-vitro|cell line|cells?|zebrafish|drosophila|xenograft|explant)\b", re.I)
_HUMAN_HINTS = re.compile(r"\b(patients?|participants?|adults?|men|women|subjects?|volunteers?|humans?|children|infants?)\b", re.I)
# High-signal markers that a study was actually conducted IN humans (not just
# mentioning them). These outweigh a stray "human" reference in an animal paper.
_HUMAN_TRIAL_MARKERS = re.compile(r"\b(randomi[sz]ed|double-blind|placebo-controlled|enrolled|recruited|informed consent|clinical trial|healthy volunteers|in patients with)\b", re.I)
# High-signal markers that the SUBJECTS were animals/models, regardless of any
# human words in the discussion section.
_ANIMAL_MODEL_MARKERS = re.compile(r"\b(male|female)?\s?(wistar|sprague-dawley|c57|balb|nude)\b|\b(animal model|induced in (rats|mice)|(rats|mice) were|administered to (rats|mice)|per kg body weight|intraperitoneal|gastric lesion|paw edema)\b", re.I)


def classify(study):
    """Add design, population, sample_size, and is_review fields to a study dict."""
    types_lower = [t.lower() for t in study.get("publication_types", [])]

    # ---- Non-study / non-evidence detection ---------------------------------
    # PubMed "Review" that is NOT systematic/meta is a narrative review: a POINTER
    # to evidence, not evidence. Editorials, comments, letters, news, biographies,
    # etc. are likewise NOT primary studies. All are tagged is_review so the
    # pipeline drops them from primary grading. Systematic reviews / meta-analyses
    # are KEPT (top evidence tier) even though they also carry "review" in PubMed.
    is_high_tier_review = ("meta-analysis" in types_lower
                           or "systematic review" in types_lower)
    _NON_STUDY_TYPES = {
        "review", "editorial", "comment", "letter", "news", "newspaper article",
        "biography", "historical article", "interview", "published erratum",
        "retraction of publication", "expression of concern", "address",
        "congress", "consensus development conference", "guideline",
        "practice guideline", "patient education handout", "personal narrative",
    }
    has_non_study = any(t in _NON_STUDY_TYPES for t in types_lower)
    is_narrative_review = has_non_study and not is_high_tier_review

    design = "unknown"
    for t in types_lower:
        if t in _DESIGN_BY_PUBTYPE:
            cand = _DESIGN_BY_PUBTYPE[t]
            if DESIGN_RANK[cand] > DESIGN_RANK[design]:
                design = cand

    text = f"{study.get('title','')} {study.get('abstract','')}"
    title_only = study.get("title", "")

    # ---- Population: decide by WEIGHT of signal, not all-or-nothing ----------
    # The old logic marked animal only if NO human word appeared anywhere — but
    # animal abstracts routinely say "adults", "men", or "implications for humans",
    # so almost every animal study was mis-tagged human. Instead, score both sides.
    animal_generic = len(_ANIMAL_HINTS.findall(text))
    human_generic = len(_HUMAN_HINTS.findall(text))
    has_human_trial = bool(_HUMAN_TRIAL_MARKERS.search(text))
    has_animal_model = bool(_ANIMAL_MODEL_MARKERS.search(text))

    # TITLE OVERRIDE: a species/model term in the TITLE is near-decisive for
    # animal. Papers performed in humans are not titled "...in rats" / "...in a
    # murine model". This beats human BACKGROUND prose in the abstract body
    # (e.g. a rat study whose intro says "safe in healthy volunteers"), which was
    # the residual mis-tagging after reviews/editorials were excluded.
    _TITLE_ANIMAL = re.compile(
        r"\b(rat|rats|mouse|mice|murine|rodent|rabbit|rabbits|dog|dogs|canine|"
        r"porcine|swine|zebrafish|in vitro|in-vitro|cell line|cells)\b", re.I)
    title_is_animal = bool(_TITLE_ANIMAL.search(title_only))

    # Publication type is a strong human signal: RCTs/meta-analyses are human
    # unless the abstract is explicitly an animal model.
    pubtype_is_human = design in ("rct", "trial", "observational",
                                  "meta_analysis", "systematic_review")

    if title_is_animal and not pubtype_is_human:
        # Species in the title, not an explicitly human study design -> animal.
        population = "animal"
    elif has_animal_model and not has_human_trial:
        # Explicit animal-model language with no human-trial structure -> animal.
        population = "animal"
    elif has_human_trial and not title_is_animal:
        # Human-trial structure AND no animal species in the title -> human.
        population = "human"
    elif pubtype_is_human and not has_animal_model:
        population = "human"
    elif animal_generic > human_generic and not has_human_trial:
        # More animal than human signal, no trial structure -> animal.
        population = "animal"
    elif human_generic > 0:
        population = "human"
    else:
        population = "unknown"

    # If we concluded animal, an otherwise-generic design should reflect that.
    if population == "animal" and design in ("unknown", "trial"):
        design = "animal"

    # Confidence flag: mark cases the keyword logic is genuinely unsure about, so
    # an optional LLM pass can resolve ONLY these (keeping cost/latency minimal).
    # Low-confidence when: population is unknown, OR the two sides conflict
    # (animal-model language AND human-trial language both present), OR there's
    # human generic wording but no strong human OR animal structural signal.
    conflict = has_animal_model and has_human_trial
    weak_human = (population == "human" and not has_human_trial
                  and not pubtype_is_human and not title_is_animal)
    low_confidence = (population == "unknown") or conflict or weak_human

    study["design"] = design
    study["population"] = population
    study["sample_size"] = _extract_sample_size(text)
    study["design_rank"] = DESIGN_RANK.get(design, 0)
    study["is_review"] = is_narrative_review
    study["population_confidence"] = "low" if low_confidence else "high"
    return study


def _extract_sample_size(text):
    """
    Best-effort participant count from an abstract.

    PubMed abstracts report N inconsistently, so this is deliberately layered:
      1. Prefer high-signal enrollment phrasings (N=, randomized/assigned to,
         enrolled, a total of N) — these almost always denote the study sample.
      2. Fall back to 'N <noun>' but only for HUMAN nouns, and take the LARGEST
         plausible match, not the first (the first is often a subgroup, a number
         of trials, a dose, or a duration).
      3. Return None when nothing trustworthy is found — None means 'unknown',
         which the grader treats as unverified precision, NOT as 'small'.

    This will still miss many abstracts (they simply don't state N parseably).
    That honest gap is why 'reviewed_by' exists and why an LLM extraction pass is
    a legitimate later upgrade — extraction from the real text, not fabrication.
    """
    # 1) High-signal enrollment patterns. Collect all, take the max plausible.
    strong = re.findall(
        r"(?:n\s*=\s*|randomi[sz]ed\s+(?:to\s+)?|assigned\s+to\s+|enroll(?:ed|ing)?\s+"
        r"|recruited\s+|a\s+total\s+of\s+|sample\s+of\s+)(\d{2,6})",
        text, re.I,
    )
    candidates = [int(x) for x in strong]

    # 2) Weaker 'N <human-noun>' fallback (humans only — avoid rats/mice inflating n).
    weak = re.findall(
        r"\b(\d{2,6})\s+(?:participants|subjects|patients|adults|men|women|"
        r"volunteers|individuals|healthy\s+(?:adults|volunteers|men|women))\b",
        text, re.I,
    )
    candidates += [int(x) for x in weak]

    # 3) Filter to a plausible human-study range; drop years, doses, p-values, etc.
    candidates = [n for n in candidates if 5 <= n <= 500000]
    if not candidates:
        return None
    # Largest plausible enrollment is the best single estimate of study size.
    return max(candidates)


def classify_all(studies):
    return [classify(s) for s in studies]


if __name__ == "__main__":
    import pubmed
    studies = pubmed._parse_articles(open("tests/sample_pubmed.xml").read())
    for s in classify_all(studies):
        print(f"PMID {s['pmid']}: design={s['design']:18} pop={s['population']:8} n={s['sample_size']}")
