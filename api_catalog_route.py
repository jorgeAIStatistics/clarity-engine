# ============================================================================
# ADD THIS TO app.py  (the CURRENT one that already has /api/ask)
#
# Paste this route among the other @app.route definitions (e.g. after cached()).
# No new imports needed — it uses the `db` and `cache` modules app.py already
# has access to. If your app.py doesn't already `import db`, add it at the top
# alongside `import cache`.
#
# WHY: the landing page currently shows every compound as "Ungraded" until you
# click it, because tiers are only known per-compound after a profile fetch.
# This returns the whole catalog's slug+tier in ONE cheap call so every card
# shows its real grade on load. Reads Postgres when available, falls back to the
# file cache locally.
# ============================================================================

@app.get("/api/catalog")
def catalog():
    # Prefer the DB (one indexed query, no JSON parsing).
    try:
        import db
        rows = db.list_catalog()
        if rows:
            return jsonify({"catalog": rows, "source": "db"})
    except Exception:
        pass

    # Fallback: read the file cache (local dev with no DATABASE_URL). Only pulls
    # the few fields the landing page needs, not whole profiles.
    internal = {"effect_sizes", "llm_population", "explanations", "appraisals",
                "pubchem", "directions", "outcomes", "citations",
                "effect-sizes", "llm-population"}
    out = []
    for slug in cache.list_cached():
        if slug in internal:
            continue
        prof = cache.get(slug)
        if not prof or not prof.get("claims"):
            continue
        out.append({
            "slug": slug,
            "name": prof.get("name"),
            "category": prof.get("category"),
            "tier": prof.get("tier"),
            "study_count": prof.get("study_count", 0),
        })
    return jsonify({"catalog": out, "source": "files"})
