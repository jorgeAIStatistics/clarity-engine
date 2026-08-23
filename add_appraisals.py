"""
Add critical appraisals to already-cached profiles (no re-grading, no PubMed).

Usage:
    python3 add_appraisals.py --limit 3     # test on 3 first
    python3 add_appraisals.py               # all cached profiles
    python3 add_appraisals.py --force       # regenerate existing ones

Peptides are flagged [CHECK] — appraisals of thin, grey-market compounds are the
ones most worth your eyes, since they're where the model has least to work with.
"""

import os
import sys
import glob
import json
import time

import appraise as appraise_mod

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
INTERNAL = {"effect_sizes", "llm_population", "explanations", "appraisals", "pubchem"}


def main():
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    force = "--force" in args

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY set — appraisals can't be generated.")
        return

    files = sorted(glob.glob(os.path.join(CACHE_DIR, "*.json")))
    files = [f for f in files
             if os.path.splitext(os.path.basename(f))[0] not in INTERNAL]
    if limit:
        files = files[:limit]

    # Each compound's prose call is independent and takes 15-20s. Sequentially
    # that is ~45 minutes for the catalog; six at a time makes it ~8.
    from concurrent.futures import ThreadPoolExecutor
    import threading
    _lock = threading.Lock()

    done = skipped = failed = 0
    checks = []
    _counts = {"done": 0, "skipped": 0, "failed": 0}

    def _bump(k):
        with _lock:
            _counts[k] += 1

    def _work(item):
        i, path = item
        try:
            prof = json.load(open(path))
        except Exception:
            return
        name = prof.get("name", os.path.basename(path))
        if not force and prof.get("appraisal"):
            _bump('skipped')
            print(f"[{i}/{len(files)}] {name:26} — already appraised, skip")
            return
        if not prof.get("claims"):
            _bump('skipped')
            return
        try:
            ap = appraise_mod.appraise(prof, force=force)
            if ap:
                prof["appraisal"] = ap
                json.dump(prof, open(path, "w"), indent=2)
                _bump('done')
                is_pep = prof.get("category") == "peptide"
                flag = "  [CHECK — peptide]" if is_pep else ""
                head = (ap.get("headline") or "")[:70]
                print(f"[{i}/{len(files)}] {name:26} — {head}{flag}")
                if is_pep:
                    checks.append(name)
            else:
                _bump('failed')
                print(f"[{i}/{len(files)}] {name:26} — no appraisal returned")
        except Exception as e:
            _bump('failed')
            print(f"[{i}/{len(files)}] {name:26} — FAILED: {type(e).__name__}")
        time.sleep(0.2)


    with ThreadPoolExecutor(max_workers=6) as _pool:
        list(_pool.map(_work, list(enumerate(files, 1))))
    done, skipped, failed = _counts["done"], _counts["skipped"], _counts["failed"]

    print(f"\nDone. appraised={done} skipped={skipped} failed={failed}")
    if checks:
        print("\nPEPTIDES TO SPOT-CHECK:")
        for c in checks:
            print("  -", c)


if __name__ == "__main__":
    main()
