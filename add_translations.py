"""
Add Spanish translations to already-cached profiles WITHOUT re-grading.

Reads each cached profile, translates its existing English prose to Spanish
(explanation, appraisal, per-claim summaries), stores `*_es` fields back, moves
on. Grades/scores/PMIDs are language-neutral and untouched.

Cost: translation only (cheaper than generation), paid once, cached. Resumable —
skips profiles already translated unless --force.

Usage:
    python3 add_translations.py --limit 5     # test on 5 first (recommended)
    python3 add_translations.py               # all cached profiles
    python3 add_translations.py --force       # retranslate everything
"""

import os
import sys
import glob
import json
import time

import translate as translate_mod

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
INTERNAL = {"effect_sizes", "llm_population", "explanations", "appraisals",
            "pubchem", "directions", "outcomes", "citations", "translations",
            "pharmacokinetics"}


def main():
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    force = "--force" in args

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY set — translations can't be generated.")
        return

    files = sorted(glob.glob(os.path.join(CACHE_DIR, "*.json")))
    files = [f for f in files
             if os.path.splitext(os.path.basename(f))[0] not in INTERNAL]
    if limit:
        files = files[:limit]

    from concurrent.futures import ThreadPoolExecutor
    import threading
    _lock = threading.Lock()
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
        if not prof.get("explanation") and not prof.get("appraisal"):
            _bump("skipped")
            print(f"[{i}/{len(files)}] {name:26} — no prose to translate, skip")
            return
        if not force and prof.get("explanation_es"):
            _bump("skipped")
            print(f"[{i}/{len(files)}] {name:26} — already translated, skip")
            return
        try:
            translate_mod.translate_profile(prof, force=force)
            if prof.get("explanation_es") or prof.get("appraisal_es"):
                json.dump(prof, open(path, "w"), indent=2, ensure_ascii=False)
                _bump("done")
                print(f"[{i}/{len(files)}] {name:26} — translated ✓")
            else:
                _bump("failed")
                print(f"[{i}/{len(files)}] {name:26} — nothing returned")
        except Exception as e:
            _bump("failed")
            print(f"[{i}/{len(files)}] {name:26} — FAILED: {type(e).__name__}")
        time.sleep(0.2)

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(_work, list(enumerate(files, 1))))

    d, s, f = _counts["done"], _counts["skipped"], _counts["failed"]
    print(f"\nDone. translated={d} skipped={s} failed={f}")


if __name__ == "__main__":
    main()
