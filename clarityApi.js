// clarityApi.js
// ---------------------------------------------------------------------------
// The data layer that connects the frontend to the LIVE engine.
//
// It does two jobs:
//   1. fetchProfile(topic, category)  -> calls your deployed API, returns the
//      engine's real profile JSON (or throws on error).
//   2. toView(engineProfile)          -> translates the engine's schema into the
//      shape the profile UI renders. This is where "Path 1" lives: we surface
//      the REAL evidence fields (tier, layered scores, grade reasons, effect
//      data, honest buckets) and DO NOT fabricate the editorial fields the
//      engine doesn't produce (mechanism essays, dosing, myths). Those simply
//      aren't shown — the profile is an evidence page, honestly.
//
// Set API_BASE to your live Render URL.
// ---------------------------------------------------------------------------

export const API_BASE = "https://clarity-engine-api.onrender.com";

// ---- 1. Fetch -------------------------------------------------------------

export async function fetchCachedList() {
  const r = await fetch(`${API_BASE}/api/cached`);
  if (!r.ok) throw new Error(`cached list failed: ${r.status}`);
  const j = await r.json();
  return j.cached || [];
}

export async function fetchProfile(topic, category = "supplement") {
  const url = `${API_BASE}/api/profile?topic=${encodeURIComponent(topic)}&category=${encodeURIComponent(category)}`;
  // NOTE: on a cache MISS the server generates live — this can take 30-60s,
  // plus Render free-tier cold start. Callers should show a patient loading UI.
  const r = await fetch(url);
  if (r.status === 503) throw new Error("daily research limit reached — try a compound already in the catalog, or come back tomorrow");
  if (r.status === 429) throw new Error("a moment between searches, please");
  if (!r.ok) throw new Error(`research failed: ${r.status}`);
  const j = await r.json();
  return { profile: j.profile, source: j.source };  // source: "cache" | "generated"
}

// ---- 2. Translate engine JSON -> view model -------------------------------

const TIER_COLORS = {
  Strong: "#38E1C4", Moderate: "#F2B441", Emerging: "#8B7DF2",
  Preliminary: "#F26D6D", Unknown: "#8497B4",
};

// Human-readable one-liners for the layered/gated model, so users understand
// WHY a peptide is "promising but unproven" vs a supplement being "established".
function bucketExplainer(profile) {
  const promising = profile.effects_promising || [];
  const established = profile.effects_established || [];
  if (established.length && !promising.length)
    return "Supported by human evidence across its main outcomes.";
  if (promising.length && !established.length)
    return "Promising in mechanism or animal studies, but not yet proven in humans.";
  if (established.length && promising.length)
    return "Proven in humans for some outcomes; promising-but-unproven for others.";
  return "Early or limited evidence — treat claims with caution.";
}

// Turn one engine claim into a renderable outcome card.
function toOutcome(claim) {
  const L = claim.layers || {};
  const he = claim.headline_effect;   // may be null (no extractable pooled effect)
  return {
    outcome: claim.outcome,
    tier: claim.tier,
    tierColor: TIER_COLORS[claim.tier] || TIER_COLORS.Unknown,
    score: claim.score,
    certainty: claim.certainty,
    nStudies: claim.n_studies,
    hasHuman: claim.has_human_evidence,
    // The three-layer view — the honest core.
    layers: {
      mechanistic: L.mechanistic ?? 0,
      preclinical: L.preclinical ?? 0,
      human: L.human ?? 0,
      overall: L.overall ?? claim.score,
      nHuman: L.n_human_studies ?? 0,
      nAnimal: L.n_animal_studies ?? 0,
      note: L.note || "",
    },
    reasons: claim.grade_reasons || [],
    // Effect size, only when the engine actually extracted one (never faked).
    headlineEffect: he ? {
      metric: he.metric, value: he.value,
      ciLow: he.ci_low, ciHigh: he.ci_high,
      nPooled: he.n_studies_pooled,
      comparator: he.comparator, direction: he.direction,
      estimated: !!he.ci_estimated,
    } : null,
    // Individual plottable effects for a forest plot (solid=verified, dashed=derived).
    plottable: (claim.effects && claim.effects.plottable) || [],
    nNotReported: (claim.effects && claim.effects.n_not_reported) || 0,
    pmids: claim.study_ids || [],
  };
}

// The main translator: engine profile -> view model the UI renders.
export function toView(p) {
  if (!p) return null;
  const claims = (p.claims || []).map(toOutcome);
  return {
    name: p.name,
    category: p.category,
    tier: p.tier,
    tierColor: TIER_COLORS[p.tier] || TIER_COLORS.Unknown,
    overallScore: p.overall_score,
    studyCount: p.study_count,
    // Honest verdict assembled from real fields (NOT an LLM essay).
    verdict: bucketExplainer(p),
    honestyNote: p.honesty_note || null,
    established: p.effects_established || [],
    promising: p.effects_promising || [],
    emerging: p.effects_emerging || [],
    outcomes: claims,
    reviewedBy: p.reviewed_by || "auto",
    generatedBy: p.generated_by || "",
    // Fields the engine does NOT produce (mechanism, dosing, side effects,
    // myths). Deliberately absent — the profile UI should not render sections
    // for these. This is Path 1: show what's real, omit what isn't.
  };
}

// Convenience: fetch + translate in one call.
export async function getProfileView(topic, category) {
  const { profile, source } = await fetchProfile(topic, category);
  return { view: toView(profile), source };
}
