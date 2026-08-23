"""
Apply the Claude Design Tool visual language to Clarity-live3.jsx, and add the
new chemistry + critical-appraisal sections in that same language.

Design tokens extracted from the Design Tool HTML (not approximated):
  background      #0A0D14
  teal (Strong)   #34E0BE      violet (Emerging) #9A8CF5
  amber (Moderate)#F5B544      coral (Preliminary)#F07D74
  blue (mechanism)#6FA8F2
  text primary    #E8EEF7      secondary #C9D6E7
  muted           #8B9AB6      dim #5E6E8A
  panels          rgba(255,255,255,0.02-0.04) + 1px rgba(255,255,255,0.09)
  radii           12 / 18 / 20px
  fonts           'Space Grotesk' display, 'JetBrains Mono' numeric
  eyebrows        uppercase, letter-spacing 1.2-1.4px
  headings        tight negative tracking (-0.3 to -0.9px)

Run:  python3 patch_design_system.py
Writes Clarity-live4.jsx
"""
import sys
import re

SRC = "Clarity-live3.jsx"
OUT = "Clarity-live4.jsx"


def die(m):
    print("PATCH FAILED:", m)
    sys.exit(1)


# --- design tokens injected as constants -----------------------------------
TOKENS = '''
// ===== Design system (from Claude Design Tool) =====
const D = {
  bg: "#0A0D14",
  panel: "rgba(255,255,255,0.025)",
  panelSolid: "#0E1219",
  line: "rgba(255,255,255,0.09)",
  lineSoft: "rgba(255,255,255,0.055)",
  text: "#E8EEF7",
  text2: "#C9D6E7",
  muted: "#8B9AB6",
  dim: "#5E6E8A",
  teal: "#34E0BE",
  amber: "#F5B544",
  violet: "#9A8CF5",
  coral: "#F07D74",
  blue: "#6FA8F2",
  display: "'Space Grotesk', system-ui, sans-serif",
  mono: "'JetBrains Mono', ui-monospace, monospace",
  r: { sm: 6, md: 12, lg: 18, pill: 20 },
};
const TIER_D = { Strong: D.teal, Moderate: D.amber, Emerging: D.violet, Preliminary: D.coral, Unknown: D.dim };

// Section eyebrow, matching the design language exactly.
function Eyebrow({ children, color }) {
  return (
    <div style={{ color: color || D.muted, fontFamily: D.mono, fontSize: 10.5, fontWeight: 500,
      letterSpacing: 1.35, textTransform: "uppercase", marginBottom: 12 }}>{children}</div>
  );
}

// Panel container, matching the design language exactly.
function Panel({ children, accent, style }) {
  return (
    <div style={{
      background: accent ? `${accent}0D` : D.panel,
      border: `1px solid ${accent ? `${accent}47` : D.line}`,
      borderRadius: D.r.lg, padding: "20px 22px", ...(style || {}),
    }}>{children}</div>
  );
}

// Verified chemistry facts from PubChem — deliberately monospace and factual,
// visually distinct from generated prose. Renders nothing when absent (mixtures
// like whey protein have no single-molecule record, and that's honest).
function ChemistryBlock({ chem }) {
  if (!chem || !chem.formula) return null;
  const Row = ({ k, v }) => (
    <div style={{ display: "flex", gap: 10, alignItems: "baseline", marginBottom: 5 }}>
      <span style={{ color: D.dim, fontFamily: D.mono, fontSize: 10.5, letterSpacing: 0.4,
        textTransform: "uppercase", minWidth: 92 }}>{k}</span>
      <span style={{ color: D.text2, fontFamily: D.mono, fontSize: 12.5, wordBreak: "break-word" }}>{v}</span>
    </div>
  );
  return (
    <Panel style={{ marginTop: 16, padding: "16px 18px" }}>
      <Eyebrow>Verified identity</Eyebrow>
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div style={{ flex: "1 1 260px", minWidth: 240 }}>
          <Row k="Formula" v={chem.formula} />
          {chem.weight ? <Row k="Mol. weight" v={`${chem.weight} g/mol`} /> : null}
          {chem.iupac_name ? <Row k="IUPAC" v={chem.iupac_name} /> : null}
          {chem.synonyms && chem.synonyms.length ? <Row k="Also known as" v={chem.synonyms.slice(0, 4).join(", ")} /> : null}
        </div>
        {chem.image_url ? (
          <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: D.r.md, padding: 8 }}>
            <img src={chem.image_url} alt="Chemical structure" width="110" height="110"
              style={{ display: "block", borderRadius: 6, opacity: 0.92 }} />
          </div>
        ) : null}
      </div>
      {chem.pubchem_url ? (
        <a href={chem.pubchem_url} target="_blank" rel="noreferrer"
          style={{ display: "inline-block", marginTop: 10, color: D.blue, fontFamily: D.mono,
            fontSize: 11, textDecoration: "none" }}>PubChem CID {chem.cid} ↗</a>
      ) : null}
    </Panel>
  );
}

// Critical appraisal — the "how this could be wrong" layer. Deliberately COOLER
// than the rest of the page (slate, not teal) so it reads as a separate voice:
// the methodologist reviewing the evidence rather than the app presenting it.
function AppraisalSection({ ap }) {
  if (!ap || !ap.headline) return null;
  const sev = { high: D.coral, moderate: D.amber, low: D.dim };
  return (
    <div style={{ marginTop: 34, paddingTop: 26, borderTop: `1px solid ${D.line}` }}>
      <Eyebrow color={D.dim}>How this could be wrong</Eyebrow>
      <div style={{ color: D.text2, fontFamily: D.display, fontSize: 16, lineHeight: 1.6,
        letterSpacing: -0.2, marginBottom: 20, maxWidth: 640 }}>{ap.headline}</div>

      {(ap.concerns || []).map((c, i) => (
        <div key={i} style={{ display: "flex", gap: 12, marginBottom: 14 }}>
          <span style={{ width: 3, borderRadius: 2, background: sev[c.severity] || D.dim, flexShrink: 0 }} />
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <span style={{ color: D.text, fontSize: 13.5, fontWeight: 600 }}>{c.issue}</span>
              <span style={{ color: sev[c.severity] || D.dim, fontFamily: D.mono, fontSize: 9.5,
                letterSpacing: 0.6, textTransform: "uppercase" }}>{c.severity}</span>
            </div>
            <div style={{ color: D.muted, fontSize: 13, lineHeight: 1.65 }}>{c.detail}</div>
          </div>
        </div>
      ))}

      {ap.mechanism_check ? (
        <Panel style={{ marginTop: 18, padding: "16px 18px" }}>
          <Eyebrow color={D.blue}>Does the mechanism support the claim?</Eyebrow>
          <div style={{ color: D.text2, fontSize: 13.5, lineHeight: 1.7 }}>{ap.mechanism_check}</div>
        </Panel>
      ) : null}

      {ap.strongest_counterargument ? (
        <Panel style={{ marginTop: 12, padding: "16px 18px" }}>
          <Eyebrow color={D.coral}>The strongest case against</Eyebrow>
          <div style={{ color: D.text2, fontSize: 13.5, lineHeight: 1.7 }}>{ap.strongest_counterargument}</div>
        </Panel>
      ) : null}

      {ap.what_would_change_the_picture ? (
        <div style={{ marginTop: 14, color: D.muted, fontSize: 12.5, lineHeight: 1.65 }}>
          <span style={{ color: D.teal }}>What would settle it: </span>{ap.what_would_change_the_picture}
        </div>
      ) : null}
    </div>
  );
}
'''


def main():
    try:
        src = open(SRC).read()
    except FileNotFoundError:
        die(f"{SRC} not found")
    orig = src

    # 1) inject tokens + components before the profile view
    anchor = "// ---- Plain-language translation"
    if anchor not in src:
        anchor = "function LayerMiniChart("
        if anchor not in src:
            die("no anchor for token injection")
    src = src.replace(anchor, TOKENS + "\n" + anchor, 1)

    # 2) pass chemistry + appraisal through the translator
    old_ret = 'reviewedBy: p.reviewed_by || "auto", explanation: p.explanation || null };'
    if old_ret not in src:
        die("translator return not found")
    src = src.replace(old_ret,
        'reviewedBy: p.reviewed_by || "auto", explanation: p.explanation || null, '
        'chemistry: p.chemistry || null, appraisal: p.appraisal || null };', 1)

    # 3) chemistry block inside "What it is"
    what_is = '<div style={{ color: "#C6D2E2", fontSize: 15, lineHeight: 1.8, letterSpacing: 0.01 }}>{ex.what_it_is}</div>'
    if what_is not in src:
        die("what_it_is block not found")
    src = src.replace(what_is, what_is + "\n          <ChemistryBlock chem={view.chemistry} />", 1)

    # 4) appraisal section before the footer line
    footer = '<div style={{ borderTop: `0.5px solid ${LINE}`, paddingTop: 14, color: "#5A6B87", fontSize: 11, textAlign: "center"'
    if footer not in src:
        die("footer not found")
    src = src.replace(footer, '<AppraisalSection ap={view.appraisal} />\n\n      ' + footer, 1)

    # 5) adopt the design-tool background + fonts globally
    src = src.replace('const INK = "#070B12";', 'const INK = "#0A0D14";')
    src = src.replace('const INK = "#080C14";', 'const INK = "#0A0D14";')
    src = re.sub(r'const TEAL = "#[0-9A-Fa-f]{6}";', 'const TEAL = "#34E0BE";', src, count=1)
    src = re.sub(r'const AMBER = "#[0-9A-Fa-f]{6}";', 'const AMBER = "#F5B544";', src, count=1)
    src = re.sub(r'const VIOLET = "#[0-9A-Fa-f]{6}";', 'const VIOLET = "#9A8CF5";', src, count=1)
    src = re.sub(r'const CORAL = "#[0-9A-Fa-f]{6}";', 'const CORAL = "#F07D74";', src, count=1)
    src = re.sub(r'const TEXT = "#[0-9A-Fa-f]{6}";', 'const TEXT = "#E8EEF7";', src, count=1)
    src = re.sub(r'const MUTE = "#[0-9A-Fa-f]{6}";', 'const MUTE = "#8B9AB6";', src, count=1)

    # tier colors used by cards/map -> design-tool palette
    src = src.replace(
        'const TIER_COLORS = { Strong:"#38E1C4", Moderate:"#F2B441", Emerging:"#8B7DF2", Preliminary:"#F26D6D", Unknown:"#8497B4" };',
        'const TIER_COLORS = { Strong:"#34E0BE", Moderate:"#F5B544", Emerging:"#9A8CF5", Preliminary:"#F07D74", Unknown:"#5E6E8A" };')

    for needle, msg in [("const D = {", "tokens"), ("ChemistryBlock chem=", "chemistry render"),
                        ("AppraisalSection ap=", "appraisal render"),
                        ("chemistry: p.chemistry", "translator")]:
        if needle not in src:
            die(f"post-check failed: {msg}")
    if src == orig:
        die("no changes applied")

    open(OUT, "w").write(src)
    print(f"OK wrote {OUT}. braces {src.count('{')}/{src.count('}')} parens {src.count('(')}/{src.count(')')}")


if __name__ == "__main__":
    main()
