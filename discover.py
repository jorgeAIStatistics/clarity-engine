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

import re
from collections import Counter

# A starter vocabulary of health outcomes and the phrases that signal them.
# Expand this over time — it's a transparent, editable asset (part of your moat).
OUTCOME_KEYWORDS = {
    "muscle strength": [r"\bstrength\b", r"\b1[- ]?rm\b", r"\bpower output\b", r"\bmuscular\b"],
    "muscle growth": [r"\bhypertroph", r"\blean (?:body )?mass\b", r"\bmuscle mass\b"],
    "endurance": [r"\bendurance\b", r"\baerobic\b", r"\bvo2\b", r"\btime to exhaustion\b"],
    "cognition": [r"\bcognit", r"\bmemory\b", r"\bmental performance\b", r"\bexecutive function\b"],
    "sleep quality": [r"\bsleep\b", r"\binsomnia\b", r"\bsleep quality\b"],
    "stress / anxiety": [r"\bstress\b", r"\banxiet", r"\bcortisol\b"],
    "mood / depression": [r"\bmood\b", r"\bdepress", r"\bwell[- ]?being\b"],
    "testosterone / hormones": [r"\btestosterone\b", r"\bhormon", r"\blibido\b"],
    "tendon / tissue healing": [r"\btendon\b", r"\bligament\b", r"\bwound heal", r"\btissue repair\b", r"\bhealing\b"],
    "gut / digestion": [r"\bgut\b", r"\bintestin", r"\bgastro", r"\bmicrobiom"],
    "inflammation": [r"\binflammat", r"\bcytokine\b", r"\boxidative stress\b"],
    "cardiovascular": [r"\bblood pressure\b", r"\bcardiovascular\b", r"\bheart rate\b", r"\bcholesterol\b", r"\blipid\b"],
    "blood sugar": [r"\bglucose\b", r"\binsulin\b", r"\bglyc(?:a|e)mi", r"\bhba1c\b"],
    "immune function": [r"\bimmune\b", r"\binfection\b", r"\bimmunit"],
    "weight / fat loss": [r"\bweight loss\b", r"\bfat mass\b", r"\bbody fat\b", r"\badipos"],
}


def discover_outcomes(studies, top_n=5, min_hits=2):
    """
    Given retrieved studies, return the most-studied outcomes for this topic.
    Returns a list of outcome names, most-supported first.
    """
    text = " ".join(f"{s.get('title','')} {s.get('abstract','')}" for s in studies).lower()
    counts = Counter()
    for outcome, patterns in OUTCOME_KEYWORDS.items():
        hits = sum(len(re.findall(p, text)) for p in patterns)
        if hits >= min_hits:
            counts[outcome] = hits
    ranked = [o for o, _ in counts.most_common(top_n)]
    # Fallback: if nothing matched (rare/novel compound), return a generic bucket
    # so the profile still generates honestly ("general effects, limited data").
    return ranked or ["general / emerging effects"]


if __name__ == "__main__":
    import pubmed, classify
    studies = classify.classify_all(pubmed._parse_articles(open("tests/sample_pubmed.xml").read()))
    print("Discovered outcomes:", discover_outcomes(studies))
