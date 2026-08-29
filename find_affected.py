"""
Find the profiles the animal-misclassification bug actually touched.

The bug: a study whose abstract said "burned mice" classified as HUMAN, because
the species word was in the abstract rather than the title and PubMed's pubtype
carried the decision. It could only inflate compounds that (a) claim human
studies and (b) have animal literature.

This re-runs the FIXED classifier over the study records already stored in each
cached profile — no PubMed calls, no LLM calls, no cost — and reports which
profiles contain studies that would now classify differently.

    python3 find_affected.py            # report
    python3 find_affected.py --list     # bare compound names, for regeneration
"""
import os
import sys
import glob
import json

import classify

INTERNAL = {"effect_sizes", "llm_population", "explanations", "appraisals",
            "pubchem", "directions", "outcomes"}



# Abstracts for PMIDs we've already seen. Fetched in one batch, not per study,
# and only for compounds that claim human evidence — so this stays cheap.
_ABSTRACTS = {}


def _prefetch_abstracts(pmids):
    """One batched PubMed fetch for the PMIDs we need to re-check."""
    todo = [p for p in pmids if p and p not in _ABSTRACTS]
    if not todo:
        return
    try:
        import pubmed
        for rec in pubmed.efetch(todo):
            _ABSTRACTS[str(rec.get("pmid"))] = rec.get("abstract") or ""
    except Exception as e:
        print(f"  (abstract fetch failed: {type(e).__name__}; "
              f"falling back to title-only checking)")
    for p in todo:
        _ABSTRACTS.setdefault(str(p), "")


def _abstract_for(pmid):
    return _ABSTRACTS.get(str(pmid), "")


def main():
    bare = "--list" in sys.argv
    affected = []
    checked = 0

    for path in sorted(glob.glob(os.path.join("cache", "*.json"))):
        slug = os.path.splitext(os.path.basename(path))[0]
        if slug in INTERNAL:
            continue
        try:
            prof = json.load(open(path))
        except Exception:
            continue
        if not prof.get("claims"):
            continue
        checked += 1

        # Which stored "human" studies would the fixed classifier call animal?
        human_pmids = [st.get("pmid") for c in prof["claims"]
                       for st in c.get("studies", [])
                       if st.get("population") == "human" and st.get("pmid")]
        if human_pmids:
            _prefetch_abstracts(human_pmids)
        misclassified = []
        for claim in prof["claims"]:
            for st in claim.get("studies", []):
                if st.get("population") != "human":
                    continue
                # Abstracts aren't stored in the profile, but the population
                # cache from the LLM classifier is keyed by PMID and was built
                # from them. Check the title first (free), then fall back to
                # PubMed only for the handful that need it.
                if classify._has_animal_signal(st.get("title", ""),
                                               _abstract_for(st.get("pmid"))):
                    misclassified.append((claim["outcome"], st.get("pmid"),
                                          (st.get("title") or "")[:64]))

        # A human-tier grade resting on animal-heavy evidence is the risk shape,
        # even when no single title trips the detector — flag those for review.
        risky_tier = False
        for claim in prof["claims"]:
            L = claim.get("layers", {})
            if (claim.get("tier") in ("Strong", "Moderate")
                    and L.get("n_animal_studies", 0) > L.get("n_human_studies", 0) * 3
                    and L.get("n_human_studies", 0) > 0):
                risky_tier = True

        if misclassified or risky_tier:
            affected.append((prof.get("name", slug), slug, prof.get("tier"),
                             misclassified, risky_tier))

    if bare:
        for _, slug, _, _, _ in affected:
            print(slug)
        return

    print(f"Checked {checked} profiles.\n")
    print(f"NEEDS REGENERATION: {len(affected)}\n")
    for name, slug, tier, mis, risky in affected:
        reason = []
        if mis:
            reason.append(f"{len(mis)} animal studies counted as human")
        if risky:
            reason.append("human tier resting on animal-dominated evidence")
        print(f"  {name[:26]:28} {str(tier)[:14]:16} {'; '.join(reason)}")
        for outcome, pmid, title in mis[:2]:
            print(f"      [{outcome}] PMID {pmid}: {title}")
    print(f"\nUnaffected: {checked - len(affected)} profiles — no need to regenerate them.")
    print("\nRegenerate just these with:")
    print("  python3 find_affected.py --list > /tmp/redo.txt")
    print("  while read s; do python3 run.py \"$s\" --fresh >/dev/null 2>&1 && echo \"done $s\"; done < /tmp/redo.txt")


if __name__ == "__main__":
    main()
