"""
Post-generation audit — flags suspicious profiles for human review.

Two bugs today were invisible in the code and only caught by eye in a scrolling
terminal: beta-alanine graded on gut/blood-sugar (phantom outcomes) and creatine
losing two-thirds of its studies (name-matching miss). Both had a clear
statistical signature. This finds them automatically.

    python3 audit_catalog.py

Flags are SUSPICIONS, not errors — high rejection is sometimes correct (TB-500
genuinely pulls tuberculosis papers). The point is to direct your attention.
"""
import os
import glob
import json

INTERNAL = {"effect_sizes", "llm_population", "explanations", "appraisals",
            "pubchem", "directions"}

# Compounds whose grades you know cold — a canary set.
EXPECTED = {
    "creatine monohydrate": "Strong", "caffeine": "Strong", "whey protein": "Strong",
    "vitamin d3": "Strong", "omega-3": "Strong", "melatonin": "Strong",
    "bpc-157": "Preliminary", "tb-500": "Preliminary", "ghk-cu": "Preliminary",
    "mots-c": "Preliminary", "pinealon": "Preliminary", "epithalon": "Preliminary",
}

TIER_RANK = {"Preliminary": 0, "Emerging": 1, "Moderate": 2, "Strong": 3,
             "Well studied — no clear benefit": 2}


def main():
    flags = []
    tiers = {}
    files = sorted(glob.glob(os.path.join("cache", "*.json")))
    n = 0
    for f in files:
        if os.path.splitext(os.path.basename(f))[0] in INTERNAL:
            continue
        try:
            p = json.load(open(f))
        except Exception:
            continue
        if not p.get("claims"):
            continue
        n += 1
        name = (p.get("name") or "").lower()
        tiers[p.get("tier", "?")] = tiers.get(p.get("tier", "?"), 0) + 1

        # 1. Thin evidence behind a confident grade
        for c in p["claims"]:
            L = c.get("layers", {})
            if c.get("tier") == "Strong" and L.get("n_human_studies", 0) < 5:
                flags.append((name, "Strong on <5 human studies",
                              f"{c['outcome']}: {L.get('n_human_studies')} human"))
            if c.get("tier") in ("Strong", "Moderate") and L.get("n_human_studies", 0) == 0:
                flags.append((name, "human-tier grade with no human studies",
                              f"{c['outcome']}"))

        # 2a. Coverage floor: any compound this thin is a retrieval problem,
        #     not a genuine absence of literature. Caffeine dropped from 71
        #     studies to 16 when the pool was shrunk, and lost a tier with it.
        if p.get("study_count", 0) < 12 and p.get("category") != "peptide":
            flags.append((name, "thin retrieval (likely a search/pool problem)",
                          f"{p.get('study_count')} studies"))

        # 2. Suspiciously few studies for a well-known compound
        if p.get("study_count", 0) < 15 and name in EXPECTED and EXPECTED[name] == "Strong":
            flags.append((name, "very few studies for a well-studied compound",
                          f"{p.get('study_count')} studies"))

        # 3. Canary mismatch
        if name in EXPECTED:
            want, got = EXPECTED[name], p.get("tier")
            if got in TIER_RANK and TIER_RANK.get(got, 9) != TIER_RANK.get(want, 9):
                flags.append((name, "tier differs from expectation",
                              f"got {got}, expected {want}"))

    print(f"Audited {n} profiles.\n")
    print("TIER DISTRIBUTION")
    for t, c in sorted(tiers.items(), key=lambda x: -x[1]):
        print(f"  {t:34} {c:4}  ({100*c/max(n,1):.0f}%)")

    if not tiers.get("Strong"):
        print("\n  WARNING: no compound reached Strong. The engine may have "
              "overcorrected — a catalog where nothing is proven is as useless "
              "as one where everything is.")

    print(f"\nFLAGS ({len(flags)})")
    if not flags:
        print("  none — nothing obviously suspicious.")
    for name, issue, detail in flags[:40]:
        print(f"  {name:26} {issue:42} {detail}")
    if len(flags) > 40:
        print(f"  ... and {len(flags)-40} more")


if __name__ == "__main__":
    main()
