"""Re-grade the vitamin catalog with canonical clinical indication coverage.

This forces fresh PubMed + Europe PMC retrieval but does NOT delete the previous
profile before the new one succeeds. Safe to stop/re-run.

Usage:
    python3 regrade_vitamins.py --limit 2
    python3 regrade_vitamins.py
    python3 regrade_vitamins.py --only "Vitamin B12"
"""
import argparse
import sys
import time

import cache
import run

VITAMINS = [
    ("Vitamin D3", "vitamin"),
    ("Vitamin B12", "vitamin"),
    ("Vitamin C", "vitamin"),
    ("Vitamin K2", "vitamin"),
    ("Folate", "vitamin"),
    ("Vitamin A", "vitamin"),
    ("Vitamin E", "vitamin"),
    ("Vitamin B6", "vitamin"),
    ("Biotin", "vitamin"),
    ("Niacin", "vitamin"),
    ("Thiamine", "vitamin"),
]


def _tier_summary(profile):
    claims = profile.get("claims") or []
    return ", ".join(f"{c.get('outcome')}: {c.get('tier')}" for c in claims) or "no claims"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", type=str)
    args = ap.parse_args()

    items = VITAMINS
    if args.only:
        q = args.only.lower().strip()
        items = [x for x in items if q in x[0].lower()]
    if args.limit:
        items = items[:args.limit]
    if not items:
        print("No matching vitamin.")
        return 2

    ok = failed = 0
    for i, (name, cat) in enumerate(items, 1):
        old = cache.get(name) or {}
        print(f"\n[{i}/{len(items)}] {name}")
        if old:
            print(f"  before: {old.get('tier')} — {_tier_summary(old)}")
        try:
            t0 = time.time()
            new = run.research(name, cat, use_cache=True, force_refresh=True, verbose=True)
            print(f"  after : {new.get('tier')} — {_tier_summary(new)}")
            checked = new.get("canonical_outcomes_checked") or []
            if checked:
                print("  canonical outcomes checked:")
                for outcome in checked:
                    print(f"    - {outcome}")
            print(f"  saved in {time.time()-t0:.1f}s")
            ok += 1
        except KeyboardInterrupt:
            print("\nStopped. Previously completed vitamins are already saved; rerun to continue.")
            return 130
        except Exception as e:
            failed += 1
            print(f"  FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            print("  Previous cached profile was not intentionally deleted.", file=sys.stderr)

    print(f"\nDone. updated={ok} failed={failed}")
    if ok:
        print("\nBecause outcome structure changed, refresh generated prose afterward:")
        print("  python3 add_explanations.py --force")
        print("  python3 add_appraisals.py --force")
        print("  python3 add_translations.py --force")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
