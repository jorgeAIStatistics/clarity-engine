"""Re-grade the entire stored Clarity catalog with the current launch engine.

This is intentionally cache-safe: the existing profile is left in place until a
fresh run succeeds. Use this after any retrieval / grading / schema change and
before a public release.

Examples:
    python3 regrade_all.py --limit 5
    python3 regrade_all.py --category vitamin
    python3 regrade_all.py --only creatine
    python3 regrade_all.py
    python3 regrade_all.py --force-current   # deliberately rebuild even current profiles

Completed profiles are skipped on the next run, so an interrupted catalog refresh resumes cleanly.

If your production database is the source of truth, either set DATABASE_URL so
this script can discover it, or run `python3 db.py --pull` first.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

import cache
import generate
import run

_INTERNAL = {
    "effect_sizes", "llm_population", "effect-sizes", "llm-population",
    "explanations", "appraisals", "translations", "pubchem", "directions",
    "outcomes", "citations", "pharmacokinetics", "ask_events",
}


@dataclass(frozen=True)
class Entry:
    slug: str
    name: str
    category: str


def _get_profile(key):
    try:
        return cache.get(key)
    except Exception:
        return None


def _discover_entries():
    """Prefer the production DB catalog; fall back to local cache files."""
    found = {}
    try:
        import db
        if db.available():
            for row in db.list_catalog() or []:
                slug = str(row.get("slug") or "").strip()
                if not slug or slug in _INTERNAL:
                    continue
                p = db.get(slug, max_age_days=100000) or {}
                name = str(p.get("name") or row.get("name") or slug).strip()
                cat = str(p.get("category") or row.get("category") or "supplement").strip()
                if p.get("claims"):
                    found[slug] = Entry(slug, name, cat)
    except Exception as e:
        print(f"[regrade] database discovery unavailable: {type(e).__name__}: {e}", file=sys.stderr)

    if not found:
        for slug in cache.list_cached():
            if slug in _INTERNAL:
                continue
            p = _get_profile(slug) or {}
            if not p.get("claims"):
                continue
            name = str(p.get("name") or slug).strip()
            cat = str(p.get("category") or "supplement").strip()
            found[slug] = Entry(slug, name, cat)

    return sorted(found.values(), key=lambda x: x.name.lower())


def _summary(p):
    if not p:
        return "no profile"
    return (f"{p.get('tier','?')} · {p.get('study_count','?')} unique studies · "
            f"{p.get('unique_human_study_count','?')} unique human · "
            f"engine {p.get('engine_version','legacy')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, help="Only process the first N matches")
    ap.add_argument("--only", type=str, help="Substring match on compound name or slug")
    ap.add_argument("--category", type=str, help="Only process one category")
    ap.add_argument("--force-current", action="store_true",
                    help="Re-grade profiles already on the current engine/schema too")
    ap.add_argument("--continue-on-error", action="store_true",
                    help="Continue after failures (default already continues; retained for clarity)")
    args = ap.parse_args()

    items = _discover_entries()
    if args.only:
        q = args.only.lower().strip()
        items = [x for x in items if q in x.name.lower() or q in x.slug.lower()]
    if args.category:
        q = args.category.lower().strip()
        items = [x for x in items if x.category.lower() == q]
    if args.limit:
        items = items[:max(0, args.limit)]

    if not items:
        print("No stored compound profiles matched.")
        return 2

    print(f"Clarity engine: {generate.ENGINE_VERSION} · schema {generate.PROFILE_SCHEMA_VERSION}")
    print(f"Freshly re-grading {len(items)} compound(s). Old profiles remain until replacements succeed.\n")

    ok = failed = skipped = 0
    started = time.time()
    for i, item in enumerate(items, 1):
        old = _get_profile(item.name) or _get_profile(item.slug) or {}
        print(f"[{i}/{len(items)}] {item.name} ({item.category})")
        print(f"  before: {_summary(old)}")
        current = (old.get("engine_version") == generate.ENGINE_VERSION
                   and int(old.get("schema_version") or 0) >= generate.PROFILE_SCHEMA_VERSION)
        if current and not args.force_current:
            skipped += 1
            print("  skip  : already current (use --force-current to rebuild)\n")
            continue
        t0 = time.time()
        try:
            fresh = run.research(
                item.name,
                item.category,
                use_cache=True,
                force_refresh=True,
                verbose=True,
            )
            print(f"  after : {_summary(fresh)}")
            print(f"  saved : {time.time() - t0:.1f}s\n")
            ok += 1
        except KeyboardInterrupt:
            print("\nStopped. Successfully completed profiles are already saved; rerun to continue.")
            return 130
        except Exception as e:
            failed += 1
            print(f"  FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            print("  Existing profile was not intentionally deleted.\n", file=sys.stderr)

    elapsed = time.time() - started
    print(f"Done in {elapsed/60:.1f} min. updated={ok} skipped_current={skipped} failed={failed}")
    if ok:
        print("\nRegenerate derived prose after the evidence refresh:")
        print("  python3 add_explanations.py --force")
        print("  python3 add_appraisals.py --force")
        print("  python3 add_translations.py --force")
        print("  python3 add_ask_context.py")
        print("\nIf local files are your generation source and Postgres serves production:")
        print("  python3 db.py --sync")
        print("\nFinally:")
        print("  python3 launch_audit.py")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
