"""
Aesthetic redesign patch: hero glow, glassmorphic search (+ cmd-K badge),
framer-motion gliding category pills, high-end grid cards (depth, glowing
evidence dots, stagger entrance), and REAL study-count metadata injected from
your local cache (no invented numbers — compounds without cached data just
show their tier).

Run on your Mac (where the full cache lives):
    python3 patch_aesthetics.py
Writes Clarity-live3.jsx. Deploy that file.
"""
import sys, re, json, glob, os

SRC = "Clarity-live2.jsx"
OUT = "Clarity-live3.jsx"

def die(m): print("PATCH FAILED:", m); sys.exit(1)

# ---- build REAL metadata from the local cache -----------------------------
def build_meta():
    meta = {}
    for f in glob.glob(os.path.join("cache", "*.json")):
        b = os.path.basename(f)
        if any(k in b for k in ["effect_sizes", "llm_population", "explanations"]):
            continue
        try:
            p = json.load(open(f))
        except Exception:
            continue
        name = (p.get("name") or "").lower().strip()
        if not name or not p.get("claims"):
            continue
        # top outcome = highest-scoring claim
        top = max(p["claims"], key=lambda c: c.get("score", 0))
        n_human = sum(c.get("layers", {}).get("n_human_studies", 0) for c in p["claims"])
        meta[name] = {
            "s": p.get("study_count", 0),                       # total studies
            "h": n_human,                                       # human studies
            "o": (top.get("outcome") or "").title()[:22],       # top outcome
        }
    return meta

def main():
    try:
        src = open(SRC).read()
    except FileNotFoundError:
        die(f"{SRC} not found")
    orig = src

    meta = build_meta()
    print(f"metadata built for {len(meta)} compounds from cache")

    # 1) framer-motion import (v0 supports it)
    anchor = 'import {\n'
    if anchor not in src: die("import anchor missing")
    src = src.replace(anchor, 'import { motion } from "framer-motion";\nimport {\n', 1)

    # 2) inject CATALOG_META after API_BASE line
    m = re.search(r'const API_BASE = "[^"]+";\n', src)
    if not m: die("API_BASE line missing")
    meta_js = "const CATALOG_META = " + json.dumps(meta) + ";\n"
    src = src[:m.end()] + meta_js + src[m.end():]

    # 3) hero ambient glow: wrap hero content with a positioned glow layer
    hero_old = '<div className="hero rise">'
    if hero_old not in src: die("hero div missing")
    src = src.replace(hero_old,
        '<div className="hero rise" style={{ position: "relative" }}>\n'
        '              <div aria-hidden="true" style={{ position: "absolute", top: "-40px", left: "50%", transform: "translateX(-50%)", width: 680, height: 340, background: "radial-gradient(ellipse at center, rgba(13,148,136,0.15) 0%, rgba(13,148,136,0) 70%)", filter: "blur(40px)", pointerEvents: "none", zIndex: 0 }} />', 1)

    # 4) glassmorphic search bar CSS + focus glow + cmdK badge
    search_css_pat = re.compile(r'\.searchbar \{ display:flex; align-items:center; gap:10px; max-width:560px; margin:0 auto; background:\$\{PANEL\}; border:1px solid \$\{LINE\}; border-radius:13px; padding:9px 12px; \}')
    if not search_css_pat.search(src): die("searchbar css missing")
    src = search_css_pat.sub(
        '.searchbar { display:flex; align-items:center; gap:10px; max-width:560px; margin:0 auto; '
        'background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.10); '
        'backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); border-radius:13px; padding:9px 12px; '
        'position:relative; z-index:1; transition:border-color .25s, box-shadow .25s; }\n'
        '        .searchbar:hover, .searchbar:focus-within { border-color:rgba(34,211,238,0.45); '
        'box-shadow:0 0 0 1px rgba(34,211,238,0.25), 0 0 18px rgba(34,211,238,0.15); }\n'
        '        .cmdk { font-family:ui-monospace,monospace; font-size:11px; color:#8497B4; '
        'border:1px solid rgba(255,255,255,0.12); background:rgba(255,255,255,0.04); '
        'padding:2px 7px; border-radius:6px; flex-shrink:0; }',
        src, count=1)

    # add the cmdK badge before the Research button
    go_btn = '<button onClick={submitSearch} className="ev-btn search-go"'
    if go_btn not in src: die("search button missing")
    src = src.replace(go_btn, '<span className="cmdk">\u2318K</span>\n                ' + go_btn, 1)

    # cmd-K actually focuses the search (nice touch, cheap)
    state_anchor = 'const [query, setQuery] = useState("");'
    if state_anchor not in src: die("query state missing")
    src = src.replace(state_anchor, state_anchor + '\n  const searchRef = useRef(null);\n  useEffect(() => {\n    const h = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); searchRef.current?.focus(); } };\n    window.addEventListener("keydown", h);\n    return () => window.removeEventListener("keydown", h);\n  }, []);', 1)
    src = src.replace('<input value={query} onChange={(e) => setQuery(e.target.value)}',
                      '<input ref={searchRef} value={query} onChange={(e) => setQuery(e.target.value)}', 1)

    # 5) FilterPill with framer-motion gliding indicator (layoutId)
    pill_old = re.compile(r'function FilterPill\(\{ active, onClick, label, color \}\) \{.*?\n\}\n', re.S)
    if not pill_old.search(src): die("FilterPill missing")
    new_pill = '''function FilterPill({ active, onClick, label, color }) {
  return (
    <button onClick={onClick} className="ev-chip"
      style={{ position: "relative", whiteSpace: "nowrap", background: "transparent", border: `1px solid ${active ? "transparent" : LINE}`, color: active ? "#E6FFFA" : MUTE, fontFamily: MONO, fontSize: 12, padding: "7px 13px", borderRadius: 20, cursor: "pointer", zIndex: 0 }}>
      {active && (
        <motion.span layoutId="pill-indicator" transition={{ type: "spring", stiffness: 420, damping: 32 }}
          style={{ position: "absolute", inset: 0, background: "rgba(13,148,136,0.35)", border: `1px solid ${color}`, borderRadius: 20, zIndex: -1 }} />
      )}
      {label}
    </button>
  );
}
'''
    src = pill_old.sub(lambda m: new_pill, src, count=1)

    # 6) grid cards: depth, hover gradient, glowing dots, meta row, stagger
    tile_old = re.compile(
        r'\{filtered\.map\(\(c, i\) => \{\n.*?\n\s+\}\)\}\n\s+</div>\n\s+\{filtered\.length === 0',
        re.S)
    if not tile_old.search(src): die("tile map block missing")
    new_tiles = '''{filtered.map((c, i) => {
                const [name, cat, tier, hasProfile, key] = c;
                const cc = CATS[cat];
                const meta = CATALOG_META[name.toLowerCase()];
                const dotGlow = tier === "Strong" ? "0 0 8px #10B981" : tier === "Moderate" ? "0 0 8px #F2B441" : `0 0 6px ${tierColor(tier)}66`;
                return (
                  <motion.div key={name + i}
                    initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: Math.min(i * 0.03, 0.6), duration: 0.35, ease: "easeOut" }}
                    className="cat-tile tile-press" onClick={() => runResearch(name, cat)}
                    onMouseEnter={() => prefetchProfile(name, cat)}
                    style={{
                      background: "rgba(255,255,255,0.015)",
                      border: "1px solid rgba(255,255,255,0.05)",
                      borderRadius: 12, padding: "14px 15px", display: "flex", flexDirection: "column", justifyContent: "space-between", minHeight: 118,
                      cursor: "pointer", transition: "border-color .25s, background .25s, transform .15s",
                    }}
                    whileHover={{ borderColor: "rgba(20,184,166,0.30)", backgroundColor: "rgba(255,255,255,0.03)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 6 }}>
                      <span style={{ fontSize: 14.5, fontWeight: 600, lineHeight: 1.25 }}>{name}</span>
                      <span style={{ display: "flex", alignItems: "center", gap: 4, fontFamily: MONO, fontSize: 10, color: tierColor(tier), flexShrink: 0 }}>
                        <span style={{ width: 6, height: 6, borderRadius: 6, background: tierColor(tier), boxShadow: dotGlow }} />{tier}
                      </span>
                    </div>
                    {meta ? (
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, fontFamily: MONO, fontSize: 10, color: MUTE }}>
                        <span>{meta.h > 0 ? `${meta.h} human ${meta.h === 1 ? "study" : "studies"}` : `${meta.s} studies`}</span>
                        {meta.o ? <span style={{ color: cc.color, background: `${cc.color}10`, border: `1px solid ${cc.color}26`, padding: "2px 6px", borderRadius: 5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 110 }}>{meta.o}</span> : null}
                      </div>
                    ) : null}
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6, marginTop: 10 }}>
                      <span style={{ fontFamily: MONO, fontSize: 9.5, color: cc.color, opacity: 0.75 }}>{cc.label}</span>
                    </div>
                  </motion.div>
                );
              })}
              </div>
              {filtered.length === 0'''
    src = tile_old.sub(lambda m: new_tiles, src, count=1)

    # sanity checks
    for needle, msg in [("framer-motion", "motion import"), ("CATALOG_META", "meta injected"),
                        ("pill-indicator", "pill glide"), ("radial-gradient", "hero glow"),
                        ("cmdk", "cmdK badge"), ("boxShadow: dotGlow", "glowing dots")]:
        if needle not in src: die(f"post-check failed: {msg}")
    if src == orig: die("no changes applied")

    open(OUT, "w").write(src)
    print(f"OK wrote {OUT}. braces {src.count('{')}/{src.count('}')} parens {src.count('(')}/{src.count(')')}")

if __name__ == "__main__":
    main()
