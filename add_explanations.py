"""
Add grounded explanations to already-cached profiles WITHOUT re-grading.

Re-running the full engine on 120 compounds just to add explanations would be
slow (PubMed calls) and pointless — the grades are already computed and cached.
This reads each cached profile, generates its explanation (cheap Haiku call,
grounded in the grades already there), writes it back, and moves on.

Cost: ~half a cent per compound, once. Resumable — skips profiles that already
have an explanation. Peptides are printed with a [CHECK] flag so you can eyeball
the thin-evidence ones after.

Usage:
    python3 add_explanations.py            # all cached profiles
    python3 add_explanations.py --limit 5  # test on 5 first
"""

import os
import sys
import glob
import json
import time

import explain as explain_mod

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
INTERNAL = {"effect_sizes", "llm_population", "explanations", "effect-sizes"}


def main():
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    force = "--force" in args

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY set — explanations can't be generated. Set the key and re-run.")
        return

    files = sorted(glob.glob(os.path.join(CACHE_DIR, "*.json")))
    files = [f for f in files if os.path.splitext(os.path.basename(f))[0] not in INTERNAL]
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
        if not force and prof.get("explanation"):
            _bump('skipped')
            print(f"[{i}/{len(files)}] {name:26} — already has explanation, skip")
            return
        try:
            ex = explain_mod.explain(prof, force=force)
            if ex:
                prof["explanation"] = ex
                json.dump(prof, open(path, "w"), indent=2)
                _bump('done')
                flag = "  [CHECK — peptide]" if prof.get("category") == "peptide" else ""
                print(f"[{i}/{len(files)}] {name:26} — explained{flag}")
                if prof.get("category") == "peptide":
                    checks.append(name)
            else:
                _bump('failed')
                print(f"[{i}/{len(files)}] {name:26} — no explanation returned")
        except Exception as e:
            _bump('failed')
            print(f"[{i}/{len(files)}] {name:26} — FAILED: {type(e).__name__}")
        time.sleep(0.2)


    with ThreadPoolExecutor(max_workers=6) as _pool:
        list(_pool.map(_work, list(enumerate(files, 1))))
    done, skipped, failed = _counts["done"], _counts["skipped"], _counts["failed"]

    print(f"\nDone. explained={done} skipped={skipped} failed={failed}")
    if checks:
        print("\nPEPTIDES TO SPOT-CHECK (thin evidence, higher hallucination risk):")
        for c in checks:
            print("  -", c)


if __name__ == "__main__":
    main()
