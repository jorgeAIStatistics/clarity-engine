"""
Preflight check — run BEFORE any catalog generation.

Stale files have been this project's most reliable failure mode: a fix is
written, the copy silently doesn't happen, and a 30-minute run produces
contaminated data. This verifies every engine file actually contains its
latest fix, then runs the regression suite.

    python3 preflight.py && python3 prewarm.py --no-effects

The `&&` matters: prewarm only runs if preflight passes.
"""
import sys
import subprocess

# (file, marker that must be present, what it fixes)
REQUIRED = [
    ("classify.py", "_greek_fold",
     "Greek-letter normalisation — without it '\u03b2-Alanine' papers are rejected as off-topic"),
    ("classify.py", "_FORM_SUFFIXES",
     "salt-suffix stripping — without it 'creatine monohydrate' misses 'creatine supplementation'"),
    ("classify.py", "_ANIMAL_TEXT_SIGNALS",
     "species detection — without it rat/chicken studies count as human"),
    ("classify.py", "is_intervention_study",
     "biomarker-vs-intervention filter"),
    ("classify.py", "is_analytical_paper",
     "assay/detection paper exclusion"),
    ("classify.py", "design_from_metadata",
     "text-inferred designs must not imply human population"),
    ("grade.py", "_MIN_PRIMARY_HUMAN",
     "minimum evidence floor for the top tier"),
    ("grade.py", "typical_trial_ok",
     "median trial size requirement"),
    ("grade.py", "est_total_n",
     "coverage-aware precision"),
    ("explain.py", "_evidence_fingerprint",
     "prose cache invalidation when grades change"),
    ("appraise.py", "_evidence_fingerprint",
     "appraisal cache invalidation when grades change"),
    ("direction.py", "_parse_first_object",
     "robust JSON parsing for direction extraction"),
    ("direction.py", "well_studied",
     "'no clear benefit' tier requires a real evidence base, not 5 studies"),
    ("direction.py", "apply_direction",
     "null-result tier handling"),
    ("pubmed.py", "_EFETCH_BATCH",
     "efetch batched — a single 150-abstract request timed out and burned retries"),
    ("pubmed.py", "MeSH subheading syntax",
     "outcome names with ' / ' expanded to OR — a bare slash is MeSH subheading syntax"),
    ("pubmed.py", "_CLINICAL_SCOPE",
     "ROOT FIX: every query scoped to intervention research, not hand-mapped per compound"),
    ("discover.py", "CANONICAL_OUTCOMES",
     "shared outcome vocabulary so grades stay comparable across compounds"),
    ("discover.py", "_DISCOVER_CACHE",
     "discovery caching — otherwise every regeneration re-pays for it"),
    ("discover.py", "discover_outcomes_llm",
     "ROOT FIX: outcomes read from titles, not matched against a hand-written taxonomy"),
    ("generate.py", "CLARITY_INLINE_PROSE",
     "explanation+appraisal excluded from generation (was 52% of wall time, and regenerated later anyway)"),
    ("add_explanations.py", "ThreadPoolExecutor",
     "prose pass parallelised"),
    ("add_appraisals.py", "ThreadPoolExecutor",
     "appraisal pass parallelised"),
    ("run.py", "pool_size = max(retmax, 150)",
     "retrieval pool sized for coverage — PubMed is ~2% of runtime, shrinking it cost caffeine a tier"),
    ("run.py", "population-resolved",
     "LLM population pass runs ONCE on the deduped pool, not per outcome (was the top cost)"),
    ("run.py", "assign_to_outcome",
     "single retrieval partitioned locally — five PubMed searches per compound was the bottleneck"),
    ("discover.py", "def assign_to_outcome",
     "local outcome partitioning"),
    ("run.py", "ThreadPoolExecutor",
     "outcomes processed in parallel — sequential was ~5 min/compound"),
    ("pubmed.py", "_throttle_lock",
     "thread-safe throttle — REQUIRED before parallelism or NCBI rate limits trip"),
    ("run.py", "discover.discover(",
     "run.py uses the LLM discovery entry point"),
    ("pubmed.py", "SEARCH_TERMS",
     "supplement-specific search terms — 'collagen' alone returns structural biology, 0 trials"),
    ("discover.py", "thyroid function",
     "thyroid/anemia categories — iodine and selenium graded on noise without them"),
    ("discover.py", "title_counts",
     "title-first outcome ranking — generic terms buried the real primary outcome"),
    ("prewarm.py", "DUPLICATES",
     "duplicate compounds removed (Betaine/Betaine HCl gave contradictory grades)"),
    ("discover.py", "skin / appearance",
     "outcome taxonomy gaps — skin/joint/bone/liver/eye categories"),
    ("discover.py", "n_abstracts >= 3",
     "outcome accepted by title OR three abstracts (title-only was too strict)"),
    ("discover.py", "in_title",
     "outcome must be the SUBJECT of a paper, not merely mentioned"),
    ("discover.py", "exercise performance",
     "performance outcome category — without it beta-alanine graded on gut/blood sugar"),
    ("discover.py", "oxidative ",
     "oxidative-stress exclusion from the psychological stress pattern"),
    ("run.py", "is_intervention_study",
     "filters wired into the pipeline"),
    ("run.py", "relevant intervention studies for outcome discovery",
     "outcome discovery runs on screened studies, not raw retrieval"),
    ("run.py", "cache.invalidate",
     "--fresh actually clears the cache before regenerating"),
    ("cache.py", "def _db",
     "Postgres-backed cache with file fallback — Render's disk is ephemeral"),
    ("db.py", "sync_from_files",
     "local catalog can be uploaded to the deployed database"),
    ("cache.py", "def invalidate",
     "cache invalidation helper"),
]

EXPECTED_TESTS = 31


def main():
    failures = []
    for path, marker, why in REQUIRED:
        try:
            content = open(path).read()
        except FileNotFoundError:
            failures.append((path, marker, "FILE MISSING", why))
            continue
        if marker not in content:
            failures.append((path, marker, "MARKER ABSENT", why))

    if failures:
        print("PREFLIGHT FAILED — stale or missing files:\n")
        for path, marker, problem, why in failures:
            print(f"  {path:16} {problem:14} missing '{marker}'")
            print(f"                   fixes: {why}\n")
        print("Copy the current versions in, then re-run preflight.")
        return 1

    print(f"All {len(REQUIRED)} file markers present.")

    r = subprocess.run([sys.executable, "test_engine.py"],
                       capture_output=True, text=True)
    tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    print(tail)
    if r.returncode != 0:
        print("\nPREFLIGHT FAILED — regression tests failing. Do not generate.")
        return 1
    if str(EXPECTED_TESTS) not in tail:
        print(f"\nPREFLIGHT FAILED — expected {EXPECTED_TESTS} tests; test_engine.py "
              "is stale. Copy the current version in.")
        return 1

    print("\nPREFLIGHT PASSED — safe to generate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
