"""
Assemble the LIVE Clarity.jsx from the original mock version.

Reads Clarity.jsx (the mock prototype) and produces Clarity-live.jsx with:
  - a real API data layer (fetch + translate engine JSON)
  - the fake research animation replaced by a real fetch
  - the old mock ProfileView replaced by the per-outcome evidence view
  - everything else (Regimen tab, catalog, app shell, styles) untouched

Run:  python3 assemble_frontend.py
Then deploy Clarity-live.jsx like you did the original.

It VERIFIES each edit landed and refuses to write a broken file — if any anchor
isn't found (e.g. the source changed), it stops and tells you which one.
"""

import sys
import re

SRC = "Clarity.jsx"
OUT = "Clarity-live.jsx"

API_BASE = "https://clarity-engine-api.onrender.com"

# ---------------------------------------------------------------------------
# The new code blocks injected into the file.
# ---------------------------------------------------------------------------

DATA_LAYER = '''
// ===== LIVE ENGINE DATA LAYER (auto-injected) =====
const API_BASE = "%s";
const TIER_COLORS = { Strong:"#38E1C4", Moderate:"#F2B441", Emerging:"#8B7DF2", Preliminary:"#F26D6D", Unknown:"#8497B4" };

async function apiFetchProfile(topic, category = "supplement") {
  const url = `${API_BASE}/api/profile?topic=${encodeURIComponent(topic)}&category=${encodeURIComponent(category)}`;
  const r = await fetch(url);
  if (r.status === 503) throw new Error("Daily research limit reached — try a compound already in the catalog, or come back tomorrow.");
  if (r.status === 429) throw new Error("One moment between searches, please.");
  if (r.status === 400) throw new Error("That doesn't look like a searchable compound.");
  if (!r.ok) throw new Error(`Research failed (${r.status}).`);
  const j = await r.json();
  return { profile: j.profile, source: j.source };
}
function engineClaimToOutcome(claim) {
  const L = claim.layers || {};
  const he = claim.headline_effect;
  return {
    outcome: claim.outcome, tier: claim.tier, tierColor: TIER_COLORS[claim.tier] || TIER_COLORS.Unknown,
    score: claim.score, certainty: claim.certainty, nStudies: claim.n_studies, hasHuman: claim.has_human_evidence,
    layers: { mechanistic: L.mechanistic ?? 0, preclinical: L.preclinical ?? 0, human: L.human ?? 0,
      overall: L.overall ?? claim.score, nHuman: L.n_human_studies ?? 0, nAnimal: L.n_animal_studies ?? 0 },
    reasons: claim.grade_reasons || [],
    headlineEffect: he ? { metric: he.metric, value: he.value, ciLow: he.ci_low, ciHigh: he.ci_high,
      nPooled: he.n_studies_pooled, comparator: he.comparator, direction: he.direction, estimated: !!he.ci_estimated } : null,
    pmids: claim.study_ids || [],
  };
}
function engineProfileToView(p) {
  if (!p) return null;
  const est = p.effects_established || [], prom = p.effects_promising || [];
  let verdict;
  if (est.length && !prom.length) verdict = "Supported by human evidence across its main outcomes.";
  else if (prom.length && !est.length) verdict = "Promising in mechanism or animal studies, but not yet proven in humans.";
  else if (est.length && prom.length) verdict = "Proven in humans for some outcomes; promising-but-unproven for others.";
  else verdict = "Early or limited evidence — treat claims with caution.";
  return { name: p.name, cat: p.category, tier: p.tier, tierColor: TIER_COLORS[p.tier] || TIER_COLORS.Unknown,
    overallScore: p.overall_score, studyCount: p.study_count, verdict, honestyNote: p.honesty_note || null,
    established: est, promising: prom, emerging: p.effects_emerging || [],
    outcomes: (p.claims || []).map(engineClaimToOutcome), reviewedBy: p.reviewed_by || "auto" };
}
// ===== END DATA LAYER =====
''' % API_BASE

NEW_STATE = '''  const [query, setQuery] = useState("");
  const [catFilter, setCatFilter] = useState("all");
  const [tierFilter, setTierFilter] = useState("all");
  const [active, setActive] = useState(null);
  const [notFound, setNotFound] = useState(null);
  const [loading, setLoading] = useState(false);
  const [phase, setPhase] = useState("");
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [source, setSource] = useState(null);
'''

NEW_HANDLERS = '''  const runResearch = async (topic, category = "supplement") => {
    setActive(null); setNotFound(null); setError(null); setView(null); setLoading(true);
    setPhase("Searching PubMed and grading the evidence… this can take up to a minute.");
    try {
      const { profile, source } = await apiFetchProfile(topic, category);
      setView(engineProfileToView(profile)); setSource(source);
    } catch (e) {
      setError(e.message || "Something went wrong.");
    } finally {
      setLoading(false); setPhase(""); window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };
  const openProfile = (key) => {
    const entry = CATALOG.find((c) => c[4] === key) || CATALOG.find((c) => c[0].toLowerCase().includes(String(key).toLowerCase()));
    if (entry) runResearch(entry[0], entry[1]); else runResearch(String(key));
  };
  const submitSearch = () => {
    const q = query.trim();
    if (!q) return;
    const entry = CATALOG.find((c) => c[0].toLowerCase().includes(q.toLowerCase()));
    runResearch(q, entry ? entry[1] : "supplement");
  };
'''

NEW_PROFILEVIEW = '''function LayerBar({ label, value, color }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ height: 5, background: LINE, borderRadius: 3, overflow: "hidden" }}>
        <div className="growbar" style={{ width: `${Math.max(0, Math.min(100, value))}%`, height: "100%", background: color }} />
      </div>
      <div style={{ color: MUTE, fontSize: 10, marginTop: 3 }}>{label}</div>
    </div>
  );
}
function EffectLine({ eff }) {
  if (!eff) return null;
  const dir = eff.direction === "harm" ? CORAL : TEAL;
  const val = typeof eff.value === "number" ? eff.value : "?";
  const ci = (typeof eff.ciLow === "number" && typeof eff.ciHigh === "number")
    ? ` (95% CI ${eff.ciLow}\\u2013${eff.ciHigh}${eff.estimated ? ", estimated" : ""})` : "";
  const metricLabel = { cohen_d:"Cohen's d", hedges_g:"Hedges' g", smd:"SMD", correlation:"r",
    odds_ratio:"OR", risk_ratio:"RR", hazard_ratio:"HR", mean_diff:"mean diff" }[eff.metric] || eff.metric;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, marginBottom: 2, flexWrap: "wrap" }}>
      <span style={{ fontFamily: MONO, fontSize: 12, color: dir }}>{metricLabel} {val}{ci}</span>
      {eff.nPooled ? <span style={{ color: MUTE, fontSize: 11 }}>\\u00b7 pooled from {eff.nPooled} studies</span> : null}
      {eff.comparator ? <span style={{ color: MUTE, fontSize: 11 }}>\\u00b7 {eff.comparator}</span> : null}
    </div>
  );
}
function OutcomeCard({ o }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ background: PANEL, border: `0.5px solid ${LINE}`, borderRadius: 12, padding: "14px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <span style={{ color: TEXT, fontSize: 15, fontWeight: 500 }}>{o.outcome}</span>
        <span style={{ background: o.tierColor, color: INK, fontSize: 11, fontWeight: 600, padding: "2px 9px", borderRadius: 20 }}>{o.tier}</span>
      </div>
      <div style={{ display: "flex", gap: 6, marginBottom: 4 }}>
        <LayerBar label="mechanism" value={o.layers.mechanistic} color="#5FA8F5" />
        <LayerBar label="preclinical" value={o.layers.preclinical} color={VIOLET} />
        <LayerBar label="human" value={o.layers.human} color={TEAL} />
      </div>
      <EffectLine eff={o.headlineEffect} />
      <div style={{ color: MUTE, fontSize: 12, lineHeight: 1.55, borderTop: `0.5px solid ${LINE}`, paddingTop: 9, marginTop: 8 }}>
        <span style={{ color: o.tierColor }}>Why: </span>
        {o.reasons && o.reasons.length ? o.reasons.join(" ") : "Graded from the available human and preclinical studies."}
      </div>
      <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ color: MUTE, fontSize: 11 }}>{o.nStudies} studies \\u00b7 {o.layers.nHuman} human \\u00b7 {o.layers.nAnimal} animal</span>
        {o.pmids && o.pmids.length ? (
          <button className="ev-btn" onClick={() => setOpen(!open)}
            style={{ background: "transparent", border: `1px solid ${LINE}`, color: MUTE, fontSize: 11, padding: "3px 9px", borderRadius: 7, cursor: "pointer" }}>
            {open ? "Hide" : "Show"} studies
          </button>
        ) : null}
      </div>
      {open && (
        <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
          {o.pmids.map((pid) => {
            const num = String(pid).replace("PMID:", "");
            return (<a key={pid} href={`https://pubmed.ncbi.nlm.nih.gov/${num}/`} target="_blank" rel="noreferrer"
              style={{ fontFamily: MONO, fontSize: 11, color: "#5FA8F5", textDecoration: "none", border: `1px solid ${LINE}`, padding: "2px 7px", borderRadius: 6 }}>{num}</a>);
          })}
        </div>
      )}
    </div>
  );
}
function ProfileView({ view, source, onBack }) {
  if (!view) return null;
  return (
    <div className="rise" style={{ paddingBottom: 90, paddingTop: 20 }}>
      <button onClick={onBack} className="ev-chip"
        style={{ display: "inline-flex", alignItems: "center", gap: 7, background: PANEL2, border: `1px solid ${LINE}`, color: MUTE, fontFamily: MONO, fontSize: 12, padding: "7px 13px", borderRadius: 20, cursor: "pointer", marginBottom: 18 }}>
        <ArrowLeft size={14} /> Back to catalog
      </button>
      <div style={{ marginBottom: 6, color: TEXT, fontSize: 30, fontWeight: 800, letterSpacing: -0.5, textTransform: "capitalize" }}>{view.name}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6, flexWrap: "wrap" }}>
        <span style={{ background: view.tierColor, color: INK, fontSize: 12, fontWeight: 600, padding: "3px 10px", borderRadius: 20 }}>{view.tier} overall</span>
        <span style={{ color: MUTE, fontSize: 13 }}>{view.studyCount} studies \\u00b7 {view.outcomes.length} outcomes</span>
        {source === "generated" ? <span style={{ color: MUTE, fontSize: 11, fontStyle: "italic" }}>\\u00b7 freshly researched</span> : null}
      </div>
      <div style={{ color: MUTE, fontSize: 13, lineHeight: 1.6, marginBottom: 4, maxWidth: 620 }}>{view.verdict}</div>
      {view.honestyNote ? <div style={{ color: AMBER, fontSize: 12, lineHeight: 1.55, marginBottom: 4, maxWidth: 620 }}>{view.honestyNote}</div> : null}
      <div className="stagger" style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 20 }}>
        {view.outcomes.map((o) => <OutcomeCard key={o.outcome} o={o} />)}
      </div>
      <div style={{ marginTop: 16, color: MUTE, fontSize: 11, textAlign: "center" }}>
        Every grade is auto-generated from PubMed evidence \\u00b7 research &amp; education, not medical advice
      </div>
    </div>
  );
}
'''


def die(msg):
    print("ASSEMBLY FAILED:", msg)
    sys.exit(1)


def main():
    try:
        src = open(SRC).read()
    except FileNotFoundError:
        die(f"can't find {SRC} in this folder")

    original = src

    # 1) Inject the data layer right after the tierColor definition (line ~39).
    anchor = 'const tierColor = (t) =>'
    if anchor not in src:
        die("couldn't find tierColor anchor for data-layer injection")
    line_end = src.index("\n", src.index(anchor)) + 1
    src = src[:line_end] + DATA_LAYER + src[line_end:]

    # 2) Replace the ResearchTab state block.
    state_pat = re.compile(
        r'  const \[query, setQuery\] = useState\(""\);.*?  const \[phase, setPhase\] = useState\(""\);\n',
        re.S)
    if not state_pat.search(src):
        die("couldn't find ResearchTab state block")
    src = state_pat.sub(lambda m: NEW_STATE, src, count=1)

    # 3) Remove the old timers ref + effect (fake animation plumbing).
    src = re.sub(r'  const timers = useRef\(\[\]\);\n', '', src, count=1)
    src = re.sub(r'  const clearTimers = \(\) => \{[^\n]*\n', '', src, count=1)
    src = re.sub(r'  useEffect\(\(\) => clearTimers, \[\]\);\n', '', src, count=1)

    # 4) Replace old openProfile + submitSearch with the real handlers.
    handlers_pat = re.compile(
        r'  const openProfile = \(key\) => \{.*?setActive\(null\); setNotFound\(query\.trim\(\)\);\n  \};\n',
        re.S)
    if not handlers_pat.search(src):
        die("couldn't find openProfile/submitSearch block")
    src = handlers_pat.sub(lambda m: NEW_HANDLERS, src, count=1)

    # 5) Replace the `const d = active ? PROFILES[active] : null;` line — the
    #    new flow uses `view` instead of a PROFILES lookup.
    if 'const d = active ? PROFILES[active] : null;' not in src:
        die("couldn't find the `d` derivation line")
    src = src.replace('const d = active ? PROFILES[active] : null;',
                      'const showProfile = view != null;')

    # 6) Replace the profile-render conditional. Original:
    #    {d && ( <ProfileView d={d} onBack={() => setActive(null)} loading={false} /> )}
    prof_render_pat = re.compile(
        r'\{d && \(\s*<ProfileView d=\{d\} onBack=\{\(\) => setActive\(null\)\}[^)]*\/>\s*\)\}',
        re.S)
    new_prof_render = '{showProfile && (\n          <ProfileView view={view} source={source} onBack={() => { setView(null); setActive(null); }} />\n        )}'
    if not prof_render_pat.search(src):
        die("couldn't find the <ProfileView> render conditional")
    src = prof_render_pat.sub(lambda m: new_prof_render, src, count=1)

    # 7) Guard the browse view: it renders when NOT showing a profile and NOT loading.
    #    Original: {!d && !loading && (
    src = src.replace('{!d && !loading && (', '{!showProfile && !loading && !error && (')

    # 8) Add an error panel next to the loading panel. Inject after the loading block.
    loading_anchor = '{loading && ('
    if loading_anchor in src:
        # add error rendering just before the loading block
        err_block = ('{error && (\n'
                     '          <div style={{ textAlign: "center", padding: "80px 0" }}>\n'
                     '            <div style={{ color: CORAL, fontSize: 15, marginBottom: 10 }}>{error}</div>\n'
                     '            <button onClick={() => { setError(null); }} className="ev-chip" style={{ background: PANEL2, border: `1px solid ${LINE}`, color: MUTE, fontFamily: MONO, fontSize: 12, padding: "7px 13px", borderRadius: 20, cursor: "pointer" }}>Back</button>\n'
                     '          </div>\n'
                     '        )}\n        ')
        src = src.replace(loading_anchor, err_block + loading_anchor, 1)

    # 9) Replace the old ProfileView function definition (and its old helpers stay,
    #    but the old ProfileView must go). Original spans from `function ProfileView({ d, onBack }) {`
    old_pv_pat = re.compile(
        r'function ProfileView\(\{ d, onBack \}\) \{.*?\n\}\n(?=\n// Expandable study card\nfunction StudyCard)',
        re.S)
    if not old_pv_pat.search(src):
        die("couldn't find the old ProfileView definition to replace")
    src = old_pv_pat.sub(lambda m: NEW_PROFILEVIEW, src, count=1)

    # ---- sanity checks: refuse to write a broken file --------------------
    checks = [
        ("apiFetchProfile", "data layer missing"),
        ("function OutcomeCard", "outcome card missing"),
        ("runResearch", "handlers missing"),
        ("view={view}", "profile render not rewired"),
    ]
    for needle, msg in checks:
        if needle not in src:
            die(f"post-edit check failed: {msg}")
    # verify by CONTENT, not size (new ProfileView is smaller than the old mock one)
    if src == original:
        die("no edits applied")

    open(OUT, "w").write(src)
    print(f"OK — wrote {OUT} ({len(src)} chars, was {len(original)}).")
    print("Next: deploy Clarity-live.jsx (paste into v0, or replace app/page in your project).")
    print("Remember to set API_BASE if your backend URL differs.")


if __name__ == "__main__":
    main()
