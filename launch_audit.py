"""Fail-fast scientific/data integrity audit for a Clarity release.

This does not judge whether every scientific conclusion is substantively right;
it catches structural states that should never be published: mixed engine
versions, duplicate headline counts, graded preprints, uncited claims, Strong
claims without a completed direction check, missing provenance, and placeholder
LLM prose.

Run after the complete fresh regrade + prose/translation passes:
    python3 launch_audit.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys

import cache
import generate

_INTERNAL = {
    "effect_sizes", "llm_population", "effect-sizes", "llm-population",
    "explanations", "appraisals", "translations", "pubchem", "directions",
    "outcomes", "citations", "pharmacokinetics", "ask_events",
}
_PLACEHOLDER = "[LLM prose would appear here"


def _norm_title(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _study_key(s):
    pmid = str(s.get("pmid") or "").strip()
    if pmid:
        return f"pmid:{pmid}"
    doi = str(s.get("doi") or "").lower().strip()
    if doi:
        return f"doi:{doi}"
    epmc = str(s.get("epmc_id") or "").lower().strip()
    if epmc:
        return f"epmc:{epmc}"
    title = _norm_title(s.get("title"))
    if title:
        return "title:" + hashlib.sha1(title.encode()).hexdigest()[:20]
    return None


def _stored_int(value):
    """Parse a stored integer without treating a legitimate zero as missing."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _profiles():
    rows = []
    try:
        import db
        if db.available():
            for row in db.list_catalog() or []:
                slug = str(row.get("slug") or "").strip()
                if not slug or slug in _INTERNAL:
                    continue
                p = db.get(slug, max_age_days=100000)
                if p and p.get("claims"):
                    rows.append((slug, p))
    except Exception as e:
        print(f"WARN database scan unavailable: {type(e).__name__}: {e}")

    if rows:
        return rows

    for slug in cache.list_cached():
        if slug in _INTERNAL:
            continue
        try:
            p = cache.get(slug)
        except Exception:
            p = None
        if p and p.get("claims"):
            rows.append((slug, p))
    return rows


def audit_profile(slug, p):
    errors, warns = [], []
    name = p.get("name") or slug

    if p.get("engine_version") != generate.ENGINE_VERSION:
        errors.append(f"engine_version={p.get('engine_version')!r}; expected {generate.ENGINE_VERSION!r}")
    if int(p.get("schema_version") or 0) < int(generate.PROFILE_SCHEMA_VERSION):
        errors.append(f"schema_version={p.get('schema_version')!r}; expected >= {generate.PROFILE_SCHEMA_VERSION}")
    if not p.get("generated_at"):
        errors.append("missing generated_at")
    if not p.get("sources"):
        errors.append("missing retrieval source provenance")
    if p.get("overall_tier_basis") != "best_human_supported_outcome":
        errors.append("unexpected/missing overall_tier_basis")

    all_unique = {}
    human_unique = {}
    animal_unique = {}
    populations_by_study = {}
    for ci, claim in enumerate(p.get("claims") or []):
        label = claim.get("outcome") or f"claim#{ci+1}"
        studies = claim.get("studies") or []
        if not studies:
            errors.append(f"{label}: claim has no inspectable study records")
        if int(claim.get("n_studies") or 0) != len(studies):
            errors.append(f"{label}: n_studies={claim.get('n_studies')} but stored study records={len(studies)}")
        if not claim.get("study_ids"):
            errors.append(f"{label}: claim has no source identifiers")
        seen_in_claim = set()
        for s in studies:
            key = _study_key(s)
            if not key:
                errors.append(f"{label}: study has no stable source identifier/title")
                continue
            if key in seen_in_claim:
                errors.append(f"{label}: duplicate study record within one outcome ({key})")
            seen_in_claim.add(key)
            all_unique[key] = s
            if s.get("is_preprint"):
                errors.append(f"{label}: preprint remains inside the published graded evidence set ({key})")
            pop = str(s.get("population") or "").strip().lower()
            if pop:
                populations_by_study.setdefault(key, set()).add(pop)
            if pop == "human":
                human_unique[key] = s
            elif pop == "animal":
                animal_unique[key] = s

        if claim.get("tier") == "Strong" and claim.get("direction_status") != "assessed":
            errors.append(f"{label}: Strong but direction_status={claim.get('direction_status')!r}")
        if claim.get("direction_status") == "failed":
            warns.append(f"{label}: direction evaluation failed (tier should already be conservatively capped)")
        if claim.get("effect_extraction_status") == "failed":
            warns.append(f"{label}: effect extraction failed")
        if _PLACEHOLDER in str(claim.get("summary") or ""):
            errors.append(f"{label}: placeholder LLM prose is visible")

    for key, pops in populations_by_study.items():
        meaningful = {p for p in pops if p not in ("", "unknown")}
        if len(meaningful) > 1:
            errors.append(f"{key}: conflicting population labels across outcomes ({', '.join(sorted(meaningful))})")

    actual_total = len(all_unique)
    actual_human = len(human_unique)
    actual_animal = len(animal_unique)
    stored_total = _stored_int(p.get("study_count"))
    stored_human = _stored_int(p.get("unique_human_study_count"))
    stored_animal = _stored_int(p.get("unique_animal_study_count"))

    if stored_total != actual_total:
        errors.append(f"study_count={p.get('study_count')} but unique claim studies={actual_total}")
    if stored_human != actual_human:
        errors.append(f"unique_human_study_count={p.get('unique_human_study_count')} but recomputed={actual_human}")
    if stored_animal != actual_animal:
        errors.append(f"unique_animal_study_count={p.get('unique_animal_study_count')} but recomputed={actual_animal}")

    memberships = sum(len(c.get("studies") or []) for c in (p.get("claims") or []))
    stored_memberships = _stored_int(p.get("outcome_study_memberships"))
    if stored_memberships != memberships:
        errors.append(f"outcome_study_memberships={p.get('outcome_study_memberships')} but recomputed={memberships}")

    pk = p.get("pharmacokinetics")
    if pk:
        if not pk.get("sources"):
            errors.append("pharmacokinetics is present but has no cited sources")
        else:
            for src in pk.get("sources") or []:
                if not isinstance(src, dict) or not src.get("label") or not src.get("url"):
                    errors.append("pharmacokinetics contains an incomplete source citation")
                    break

    # Derived prose is allowed to be absent on a newly generated profile, but it
    # is a publication-quality warning because the UI is much less informative.
    if not p.get("explanation"):
        warns.append("missing explanation prose")
    if p.get("explanation") and not p.get("explanation_es"):
        warns.append("English explanation exists but Spanish translation is missing")
    if not p.get("appraisal"):
        warns.append("missing critical appraisal")

    return name, errors, warns


def main():
    profs = _profiles()
    if not profs:
        print("ERROR: no compound profiles found. Set DATABASE_URL or ensure cache/*.json is available.")
        return 2

    error_count = warning_count = 0
    print(f"Auditing {len(profs)} profiles against engine {generate.ENGINE_VERSION} / schema {generate.PROFILE_SCHEMA_VERSION}\n")
    for slug, p in profs:
        name, errors, warns = audit_profile(slug, p)
        if errors or warns:
            print(name)
            for e in errors:
                print(f"  ERROR: {e}")
            for w in warns:
                print(f"  WARN : {w}")
        error_count += len(errors)
        warning_count += len(warns)

    print(f"\nAudit complete: profiles={len(profs)} errors={error_count} warnings={warning_count}")
    if error_count:
        print("NOT READY TO PUBLISH: fix all ERROR items and rerun this audit.")
        return 1
    print("Structural launch checks passed. Review WARN items and complete the manual scientific gold-set QA before publishing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
