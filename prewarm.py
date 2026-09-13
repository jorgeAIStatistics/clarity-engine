"""
Pre-warm the cache: generate a profile for every compound in the catalog so the
site has a full catalog on day one (then new searches generate lazily).

WHY THIS EXISTS: you asked why you should have to run each compound by hand. You
don't — this does the whole catalog in one command, unattended. It's the
autonomous version of what you were doing manually.

COST CONTROL (read this):
  - If ANTHROPIC_API_KEY is SET, each new compound runs the LLM classifier +
    effect extraction = real (small) per-compound cost. 146 compounds is real
    money, not fractions of a cent. Decide deliberately.
  - If ANTHROPIC_API_KEY is UNSET, this runs FREE (grading only, no LLM). The
    profiles are slightly less refined (no LLM population fix) but cost nothing.
  - --limit N        : only do the first N (test the waters cheaply first)
  - --free           : force zero-cost mode even if a key is set (unsets it here)
  - RESUMABLE        : already-cached compounds are skipped, so you can stop
                       (Ctrl+C) and re-run anytime; it picks up where it left off.

Usage:
    python prewarm.py --free --limit 10     # 10 compounds, zero cost, test run
    python prewarm.py --free                # all 146, zero cost
    python prewarm.py                       # all 146, WITH LLM (costs money)
    python prewarm.py --limit 20            # first 20 with LLM
"""

import sys
import os
import time

import run
import cache

# All 146 catalog compounds (name, category), extracted from Clarity.jsx.
CATALOG = [
    ["Creatine Monohydrate", "supplement"], ["Beta-Alanine", "supplement"], ["Caffeine", "supplement"],
    ["Whey Protein", "supplement"], ["Citrulline Malate", "supplement"], ["HMB", "supplement"],
    ["Sodium Bicarbonate", "supplement"], ["Beetroot", "supplement"], ["Electrolytes", "supplement"],
    ["Collagen", "supplement"], ["Glucosamine", "supplement"], ["Turmeric", "supplement"],
    ["CoQ10", "supplement"], ["Melatonin", "supplement"], ["Glutamine", "supplement"],
    ["ZMA", "supplement"], ["Tart Cherry", "supplement"], ["Apple Cider Vinegar", "supplement"],
    ["BPC-157", "peptide"], ["TB-500", "peptide"], ["GHK-Cu", "peptide"], ["Semaglutide", "peptide"],
    ["Tirzepatide", "peptide"], ["Ipamorelin", "peptide"], ["CJC-1295", "peptide"], ["MOTS-c", "peptide"],
    ["Melanotan II", "peptide"], ["Thymosin Alpha-1", "peptide"], ["Sermorelin", "peptide"],
    ["PT-141", "peptide"], ["Epithalon", "peptide"], ["AOD-9604", "peptide"],
    ["L-Theanine", "nootropic"], ["Caffeine + L-Theanine", "nootropic"], ["Bacopa Monnieri", "nootropic"],
    ["Lion's Mane", "nootropic"], ["Alpha-GPC", "nootropic"], ["Modafinil", "nootropic"],
    ["Rhodiola Rosea", "nootropic"], ["Phosphatidylserine", "nootropic"], ["Ginkgo Biloba", "nootropic"],
    ["Noopept", "nootropic"], ["Piracetam", "nootropic"], ["Citicoline", "nootropic"],
    ["Vitamin D3", "vitamin"], ["Vitamin B12", "vitamin"], ["Vitamin C", "vitamin"],
    ["Vitamin K2", "vitamin"], ["Folate", "vitamin"], ["Vitamin A", "vitamin"], ["Vitamin E", "vitamin"],
    ["Vitamin B6", "vitamin"], ["Biotin", "vitamin"], ["Niacin", "vitamin"], ["Thiamine", "vitamin"],
    ["Magnesium", "mineral"], ["Zinc", "mineral"], ["Iron", "mineral"], ["Selenium", "mineral"],
    ["Iodine", "mineral"], ["Calcium", "mineral"], ["Potassium", "mineral"], ["Copper", "mineral"],
    ["Chromium", "mineral"], ["Boron", "mineral"], ["Manganese", "mineral"],
    ["Ashwagandha", "herb"], ["Ginseng", "herb"], ["Tongkat Ali", "herb"], ["Fenugreek", "herb"],
    ["Milk Thistle", "herb"], ["Berberine", "herb"], ["Saffron", "herb"], ["St. John's Wort", "herb"],
    ["Valerian Root", "herb"], ["Maca Root", "herb"], ["Cordyceps", "herb"], ["Reishi", "herb"],
    ["Holy Basil", "herb"], ["Ginger", "herb"], ["Garlic Extract", "herb"],
    ["L-Citrulline", "amino"], ["L-Arginine", "amino"], ["BCAAs", "amino"], ["EAAs", "amino"],
    ["L-Tyrosine", "amino"], ["Taurine", "amino"], ["Glycine", "amino"], ["L-Carnitine", "amino"],
    ["Betaine", "amino"], ["Beta-Alanine", "amino"], ["NAC", "amino"], ["L-Glutamine", "amino"],
    ["NMN", "longevity"], ["NR", "longevity"], ["Resveratrol", "longevity"], ["Spermidine", "longevity"],
    ["Fisetin", "longevity"], ["Quercetin", "longevity"], ["Metformin", "longevity"],
    ["Rapamycin", "longevity"], ["Ca-AKG", "longevity"], ["Urolithin A", "longevity"],
    ["Sulforaphane", "longevity"], ["Astaxanthin", "longevity"],
    ["Testosterone", "hormonal"], ["DHEA", "hormonal"], ["Pregnenolone", "hormonal"],
    ["Vitamin D", "hormonal"], ["Boron", "hormonal"], ["Zinc", "hormonal"], ["Progesterone", "hormonal"],
    ["Melatonin", "hormonal"], ["Thyroid", "hormonal"],
    ["Omega-3", "fat"], ["Fish Oil", "fat"], ["Krill Oil", "fat"], ["Algae Oil", "fat"],
    ["MCT Oil", "fat"], ["CLA", "fat"], ["Flaxseed", "fat"], ["Evening Primrose Oil", "fat"],
    ["Probiotics", "gut"], ["Lactobacillus rhamnosus", "gut"], ["Saccharomyces boulardii", "gut"],
    ["Prebiotics", "gut"], ["Psyllium Fiber", "gut"], ["Digestive Enzymes", "gut"],
    ["L-Glutamine", "gut"], ["Butyrate", "gut"], ["Betaine HCl", "gut"],
    ["Fat Loss", "goal"], ["Muscle Gain", "goal"], ["Better Sleep", "goal"], ["Anxiety Relief", "goal"],
    ["Focus & Productivity", "goal"], ["Joint Pain", "goal"], ["Gut Health", "goal"],
    ["Testosterone Support", "goal"], ["Immune Support", "goal"], ["Blood Sugar Control", "goal"],
    ["Heart Health", "goal"], ["Skin & Anti-Aging", "goal"], ["Energy & Fatigue", "goal"],
    ["Migraine Prevention", "goal"], ["Hair Loss", "goal"],
    # --- Research peptides in commercial circulation (added Aug 2026) ---------
    # These are widely sold grey-market and the population buying them is exactly
    # who benefits most from an honest grade. Most will land Preliminary with zero
    # human trials — that IS the useful answer.
    # Multi-compound BLENDS are deliberately excluded: they aren't single
    # interventions, so grading them produces meaningless scores (same reason
    # goals and "Electrolytes" are excluded).
    ["Tesamorelin", "peptide"], ["KPV", "peptide"], ["IGF-1 LR3", "peptide"],
    ["Semax", "peptide"], ["Selank", "peptide"], ["Kisspeptin", "peptide"],
    ["Pinealon", "peptide"], ["Cartalax", "peptide"], ["Vesugen", "peptide"],
    ["Crystagen", "peptide"], ["LL-37", "peptide"], ["Snap-8", "peptide"],
    ["Vasoactive intestinal peptide", "peptide"], ["Survodutide", "peptide"],
    ["Cagrilintide", "peptide"], ["Cibinetide", "peptide"], ["Oxytocin", "peptide"],
    ["Delta sleep-inducing peptide", "peptide"], ["Hexarelin", "peptide"],
    ["Melanotan-1", "peptide"], ["Glutathione", "supplement"],
    ["Nicotinamide adenine dinucleotide", "longevity"], ["5-Amino-1MQ", "longevity"],
]


def main():
    args = sys.argv[1:]
    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    if "--free" in args:
        os.environ.pop("ANTHROPIC_API_KEY", None)  # force zero-cost mode
    if "--no-effects" in args:
        # Keep the (cheap, fast, valuable) population classifier, but SKIP the
        # slow, low-yield per-study effect extraction that made some compounds
        # take hours. Recommended for catalog pre-warming.
        os.environ["CLARITY_NO_EFFECTS"] = "1"

    # NON-GRADEABLE ENTRIES: goals and vague multi-substance categories are not
    # single interventions, so grading them produces meaningless inflated scores
    # ("Strong evidence for Fat Loss" means nothing). Skip them here. These need
    # a different kind of page ("top compounds for this goal"), built separately.
    # DUPLICATES: the same molecule listed twice produced two profiles with
    # different study counts and contradictory grades (Betaine 100/Strong vs
    # Betaine HCl 80/Strong; Glutamine 86 vs L-Glutamine 19; Vitamin D 6 vs
    # Vitamin D3 36). Two entries for one compound destroys trust immediately.
    # Keep the canonical name, skip the alias.
    DUPLICATES = {
        "betaine hcl",        # same as betaine (TMG)
        "l-glutamine",        # same as glutamine
        "l-citrulline",       # covered by citrulline malate
        "vitamin d",          # same as vitamin d3
        "fish oil",           # same as omega-3
        "n-acetyl semax amidate", "n-acetyl selank amidate", "n-acetyl epithalon",
        "caffeine + l-theanine",   # a stack, not a single compound
    }

    SKIP = {
        # goals (outcomes, not compounds)
        "fat loss", "muscle gain", "better sleep", "anxiety relief",
        "focus & productivity", "joint pain", "gut health",
        "testosterone support", "immune support", "blood sugar control",
        "heart health", "skin & anti-aging", "energy & fatigue",
        "migraine prevention", "hair loss",
        # vague multi-substance categories (not one gradeable intervention)
        "electrolytes", "probiotics", "prebiotics", "digestive enzymes",
        # multi-compound peptide blends — not single interventions
        "klow", "glow", "wolverine", "coremend", "mitoprime", "illumineuro",
        "glp-2",   # vendor name, not a standard single compound

        "thyroid", "testosterone",
    }

    key_on = bool(os.environ.get("ANTHROPIC_API_KEY"))
    mode = "WITH LLM (costs money per new compound)" if key_on else "FREE (grading only, no LLM)"

    # De-duplicate (some compounds appear in multiple categories); keep first.
    # Also drop non-gradeable entries (goals / vague categories).
    seen, items = set(), []
    for name, cat in CATALOG:
        k = name.lower()
        if k in SKIP or k in DUPLICATES:
            continue
        if k not in seen:
            seen.add(k)
            items.append((name, cat))
    if limit:
        items = items[:limit]

    print(f"Pre-warming {len(items)} compounds — mode: {mode}")
    print(f"(Already-cached compounds are skipped; safe to stop and re-run.)\n")

    # PARALLEL across compounds. Each compound's PubMed + LLM calls are I/O-bound
    # (network waits), so running several at once is a near-linear speedup. The
    # PubMed throttle in pubmed.py is lock-guarded, so NCBI's rate limit is still
    # respected; Haiku's limits comfortably handle a few concurrent streams.
    # Tune with --workers N (default 4). Use 1 to force the old sequential mode.
    workers = 4
    if "--workers" in args:
        workers = max(1, int(args[args.index("--workers") + 1]))

    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    _lock = threading.Lock()
    _counts = {"done": 0, "skipped": 0, "failed": 0}

    def _bump(k):
        with _lock:
            _counts[k] += 1

    def _work(item):
        i, (name, cat) = item
        if cache.get(name):
            _bump("skipped")
            print(f"[{i}/{len(items)}] {name:28} — already cached, skip")
            return
        try:
            t0 = time.time()
            profile = run.research(name, cat, use_cache=True, verbose=False)
            dt = time.time() - t0
            tier = profile.get("tier", "?")
            n = profile.get("study_count", 0)
            _bump("done")
            print(f"[{i}/{len(items)}] {name:28} — {tier:11} ({n} studies, {dt:.0f}s)")
        except Exception as e:
            _bump("failed")
            print(f"[{i}/{len(items)}] {name:28} — FAILED: {type(e).__name__}: {e}")

    if workers == 1:
        for it in enumerate(items, 1):
            _work(it)
    else:
        print(f"Running {workers} compounds in parallel.\n")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_work, it) for it in enumerate(items, 1)]
            for _ in as_completed(futures):
                pass

    done, skipped, failed = _counts["done"], _counts["skipped"], _counts["failed"]
    print(f"\nDone. generated={done}  skipped={skipped}  failed={failed}")
    print(f"Total cached now: {len(cache.list_cached())}")


if __name__ == "__main__":
    main()
