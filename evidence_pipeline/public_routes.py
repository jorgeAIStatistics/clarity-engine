"""Public read-only literature routes. No extraction or arbitrary graph queries."""

from flask import Blueprint, jsonify, request
from .publication import current_records, source_summary

blueprint = Blueprint("pico_public", __name__)


@blueprint.get("/api/pico/studies")
def studies():
    try:
        records = current_records()
    except Exception:
        return jsonify(error="structured_sources_unavailable"), 503
    response = jsonify(
        version="pico-public-v1",
        studies=[source_summary(r) for r in records],
        scope="Research literature; automated source validation is not scientific appraisal.",
    )
    response.headers["Cache-Control"] = "public, max-age=60"
    return response


@blueprint.get("/api/pico/studies/<pmid>")
def study(pmid):
    if not pmid.isdigit() or len(pmid) > 12:
        return jsonify(error="not_found"), 404
    try:
        item = next((r for r in current_records() if r["source"].pmid == pmid), None)
    except Exception:
        return jsonify(error="structured_sources_unavailable"), 503
    if item is None:
        return jsonify(error="not_found"), 404
    response = jsonify(
        version="pico-public-v1",
        study=source_summary(item),
        extraction=item["envelope"].extraction.model_dump(mode="json"),
        sources=[s.model_dump(mode="json") for s in item["envelope"].sources],
        validation=item["grounding"],
        scope="Reported structured extracts; no causal judgment or new statistical synthesis.",
    )

    if request.args.get("download") == "1":
        response.headers["Content-Disposition"] = (
            f'attachment; filename="clarity-pico-{pmid}.json"'
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
