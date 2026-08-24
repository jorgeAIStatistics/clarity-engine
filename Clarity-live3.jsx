import React, { useState, useEffect, useRef, useMemo } from "react";
import { motion } from "framer-motion";
import {
  Search, TrendingUp, Shield, FlaskConical, Activity, Sparkles, ArrowLeft,
  Zap, Heart, Brain, Dumbbell, AlertTriangle, Users, Link2, Beaker, CheckCircle2, CircleDashed,
  Plus, Check, X, Watch, Smartphone, Moon, Clock, Trash2, BookOpen, ClipboardList
} from "lucide-react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Cell, Tooltip,
  LineChart, Line, CartesianGrid, RadialBarChart, RadialBar, PolarAngleAxis,
  AreaChart, Area, ReferenceLine
} from "recharts";


// ---- Design tokens ----
const INK = "#0B1220", PANEL = "#111B2E", PANEL2 = "#0E1626", LINE = "#1E2C44";
const TEAL = "#38E1C4", TEAL_DIM = "#1C5C54", AMBER = "#F2B441", CORAL = "#F26D6D", VIOLET = "#8B7DF2";
const TEXT = "#E6EDF6", MUTE = "#8497B4";
const MONO = "'JetBrains Mono','SF Mono',ui-monospace,monospace";
const DISPLAY = "'Inter',system-ui,sans-serif";

// ---- Categories ----
const CATS = {
  supplement: { label: "Supplements", color: TEAL },
  peptide: { label: "Peptides", color: VIOLET },
  nootropic: { label: "Nootropics", color: "#5FA8F5" },
  vitamin: { label: "Vitamins", color: "#F2B441" },
  mineral: { label: "Minerals", color: "#E29A6B" },
  herb: { label: "Herbs & Adaptogens", color: "#7FD17F" },
  amino: { label: "Amino Acids", color: "#F28FB4" },
  longevity: { label: "Longevity", color: "#5FD6D0" },
  hormonal: { label: "Hormonal", color: "#F26D6D" },
  fat: { label: "Fatty Acids", color: "#E5C15F" },
  gut: { label: "Gut & Probiotics", color: "#9BD46E" },
  goal: { label: "Goals & Conditions", color: "#B39DF2" },
};

// Evidence tiers for catalog chips (illustrative positioning, not fabricated scores)
const T = { strong: "Strong", moderate: "Moderate", emerging: "Emerging", weak: "Weak" };
const tierColor = (t) => (t === "Strong" ? TEAL : t === "Moderate" ? AMBER : t === "Emerging" ? VIOLET : CORAL);

// ===== LIVE ENGINE DATA LAYER (auto-injected) =====
const API_BASE = "https://clarity-engine-api.onrender.com";
const CATALOG_META = {};
const TIER_COLORS = { Strong:"#38E1C4", Moderate:"#F2B441", Emerging:"#8B7DF2", Preliminary:"#F26D6D", Unknown:"#8497B4" };

// Session cache (survives navigation within the session) + in-flight dedup so
// hovering then clicking doesn't double-fetch, and revisiting is instant.
const _profileCache = new Map();   // key -> { profile, source }
const _inflight = new Map();       // key -> Promise

function _cacheKey(topic, category) {
  return `${String(topic).toLowerCase().trim()}::${category}`;
}

async function apiFetchProfile(topic, category = "supplement") {
  const key = _cacheKey(topic, category);
  if (_profileCache.has(key)) return _profileCache.get(key);   // instant on revisit
  if (_inflight.has(key)) return _inflight.get(key);           // dedup hover+click

  const url = `${API_BASE}/api/profile?topic=${encodeURIComponent(topic)}&category=${encodeURIComponent(category)}`;
  const p = (async () => {
    const r = await fetch(url);
    if (r.status === 503) throw new Error("Daily research limit reached — try a compound already in the catalog, or come back tomorrow.");
    if (r.status === 429) throw new Error("One moment between searches, please.");
    if (r.status === 400) throw new Error("That doesn't look like a searchable compound.");
    if (!r.ok) throw new Error(`Research failed (${r.status}).`);
    const j = await r.json();
    const result = { profile: j.profile, source: j.source };
    _profileCache.set(key, result);
    return result;
  })();
  _inflight.set(key, p);
  try { return await p; }
  finally { _inflight.delete(key); }
}

// Fire-and-forget prefetch (used on hover). Swallows errors — it's best-effort.
function prefetchProfile(topic, category = "supplement") {
  const key = _cacheKey(topic, category);
  if (_profileCache.has(key) || _inflight.has(key)) return;
  apiFetchProfile(topic, category).catch(() => {});
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
    outcomes: (p.claims || []).map(engineClaimToOutcome), reviewedBy: p.reviewed_by || "auto", explanation: p.explanation || null };
}
// ===== END DATA LAYER =====

// ---- Full profiles (only where data supports honest depth) ----
const PROFILES = {
  creatine: {
    name: "Creatine Monohydrate", cat: "supplement", tier: T.strong,
    verdict: "Strong evidence for strength & power. Among the most-studied supplements in existence, with a solid long-term safety record.",
    strength: 92, strengthLabel: "Strong", studies: 684, participants: "22,400+", years: "1992–2025",
    mechanism: "Muscles use ATP for quick, explosive energy but store only seconds' worth. Creatine regenerates ATP faster by donating a phosphate group, extending your high-intensity 'battery.' It also pulls water into muscle cells, supporting growth signaling.",
    effects: { established: [
        { t: "Increases maximal strength", d: "~5–15% gains in 1-rep-max vs. placebo", icon: "dumbbell" },
        { t: "Boosts power & sprint output", d: "Improves repeated short bursts", icon: "zap" },
        { t: "Increases lean muscle mass", d: "Cell hydration + greater training volume over time", icon: "activity" }],
      emerging: [
        { t: "Supports cognition under stress", d: "May help during sleep deprivation or high demand", icon: "brain" },
        { t: "Healthy-aging signals", d: "Early data on muscle preservation in older adults", icon: "heart" }] },
    primary: ["Strength training performance", "Muscle growth (hypertrophy)", "High-intensity athletic output"],
    linked: ["Better recovery between sets", "Cognitive resilience when fatigued", "Muscle retention while dieting", "Emerging bone support in older adults"],
    populations: "Extensively studied in healthy adults, athletes, and increasingly older adults. Effects largest in those not already creatine-saturated.",
    sideEffects: [{ t: "Water weight", sev: "mild", d: "1–2 kg early from intracellular water — not fat" }, { t: "GI discomfort", sev: "mild", d: "From large single doses; split or lower to fix" }],
    interactions: "No major drug interactions in healthy people. Kidney disease → consult a physician.",
    stacks: ["Protein / whey", "Carbohydrates", "Beta-alanine", "Resistance training"],
    effect: [{ m: "Strength", v: 8 }, { m: "Power", v: 7 }, { m: "Lean mass", v: 5 }, { m: "Cognition", v: 4 }, { m: "Endurance", v: 2 }],
    trend: [{ y: "'05", n: 180 }, { y: "'10", n: 290 }, { y: "'15", n: 410 }, { y: "'20", n: 560 }, { y: "'25", n: 684 }],
    dose: "3–5 g/day, every day. No loading phase required.", safety: "Well-tolerated; strong long-term safety record in healthy adults.",
    bottomLine: "If you lift and want one supplement with the most proof behind it, this is it. Cheap, safe, and it works — the effect is modest but real and remarkably consistent.",
    doseDetail: "Monohydrate is the only form worth paying for — 'advanced' versions cost more without better results. 3–5 g daily, any time of day, with or without food. Loading (20 g/day for a week) only saturates you faster; it changes nothing long-term.",
    cost: { level: "Very cheap", note: "~$0.10–0.20 per day. One of the best value-per-effect supplements that exists." },
    keyStudies: [
      { title: "Creatine & resistance training meta-analysis", design: "Meta-analysis · 22 RCTs", finding: "Adding creatine to resistance training increased lean mass and strength gains meaningfully over training alone." },
      { title: "International Society of Sports Nutrition position stand", design: "Expert consensus review", finding: "Concluded creatine monohydrate is the most effective legal ergogenic aid for high-intensity work, with a strong safety profile." },
    ],
    myths: [
      { myth: "Creatine damages your kidneys", fact: "In healthy people, long-term studies show no kidney harm. The myth comes from it raising creatinine, a lab marker — not actual damage." },
      { myth: "It's a steroid", fact: "It's an amino-acid-derived compound found in red meat and made by your body. No hormonal action whatsoever." },
      { myth: "You have to load it", fact: "Loading only speeds saturation by a week. A steady 3–5 g/day reaches the same place." },
    ],
    comparison: "Vs. other muscle-building supplements: creatine has far more evidence than HMB, BCAAs, or 'test boosters.' Only protein rivals its support — and they work on different mechanisms, so most people use both.",
  },
  bpc157: {
    name: "BPC-157", cat: "peptide", tier: T.emerging,
    verdict: "Promising in animal studies for tissue repair — but robust human trials are essentially absent. Popular well ahead of the evidence.",
    strength: 34, strengthLabel: "Preliminary", studies: 71, participants: "Mostly rodent", years: "1991–2025",
    mechanism: "A synthetic peptide from a stomach protein. In animals it promotes new blood-vessel formation and modulates growth-factor signaling — the proposed route to faster healing. Almost all mechanism is shown in rodents, not humans.",
    effects: { established: [],
      emerging: [
        { t: "Tendon/ligament healing (animal)", d: "Faster repair in rat tendon injury", icon: "activity" },
        { t: "Gut-lining protection (animal)", d: "Protective effects on intestinal tissue in rodents", icon: "heart" },
        { t: "Anti-inflammatory signals (animal)", d: "Reduced inflammation markers in preclinical models", icon: "zap" }] },
    primary: ["(Claimed) soft-tissue & tendon recovery", "(Claimed) gut health support"],
    linked: ["Reported reduced joint discomfort (anecdotal)", "Reported faster recovery (anecdotal)"],
    populations: "Human evidence minimal — mostly case reports and anecdote. Bulk of data is rodent studies, which don't reliably translate.",
    sideEffects: [{ t: "Unknown long-term profile", sev: "high", d: "Human safety not established in trials" }, { t: "Unregulated sourcing", sev: "high", d: "Sold as 'research chemical'; purity varies widely" }],
    interactions: "Not characterized in humans. Not FDA-approved for therapeutic use.",
    stacks: ["Often combined with TB-500 in community protocols (also unproven)"],
    effect: [{ m: "Tendon (rat)", v: 7 }, { m: "Gut (rat)", v: 6 }, { m: "Anti-infl.", v: 5 }, { m: "Human data", v: 1 }, { m: "RCTs", v: 0 }],
    trend: [{ y: "'05", n: 14 }, { y: "'10", n: 26 }, { y: "'15", n: 41 }, { y: "'20", n: 58 }, { y: "'25", n: 71 }],
    dose: "No established human dosing. Not an approved therapeutic.", safety: "Human safety not established. Legality and quality vary by region.",
    bottomLine: "Genuinely exciting in animals, but the human evidence isn't here yet. Anyone selling certainty about BPC-157 in people is ahead of the science. Promising ≠ proven.",
    doseDetail: "There is no validated human dose. Community protocols exist but rest on animal data and anecdote, not trials. Products are sold as 'research chemicals,' meaning no regulatory oversight of purity, dose accuracy, or contamination.",
    cost: { level: "Expensive + risky", note: "Grey-market pricing varies wildly; quality is unverifiable and legality differs by country." },
    keyStudies: [
      { title: "BPC-157 in tendon healing (rat model)", design: "Preclinical · rodents", finding: "Accelerated tendon-to-bone healing and improved function in injured rats — a striking effect, but in animals only." },
      { title: "Human clinical evidence", design: "Systematic search", finding: "Essentially no completed, peer-reviewed randomized human trials establishing efficacy or long-term safety." },
    ],
    myths: [
      { myth: "It's proven to heal injuries in people", fact: "The healing data is almost entirely from rodents. Human proof would require trials that haven't been done." },
      { myth: "It's safe because it's 'natural'", fact: "It's a synthetic peptide fragment. Human safety simply hasn't been characterized in studies." },
      { myth: "Legal and regulated", fact: "In many regions it's unapproved and sold only for research — not human use." },
    ],
    comparison: "Vs. proven recovery tools: for tissue healing, the evidence base for structured rehab, progressive loading, and adequate protein dwarfs anything BPC-157 has in humans. It's a bet on future data, not a current option.",
  },
  ashwagandha: {
    name: "Ashwagandha", cat: "herb", tier: T.moderate,
    verdict: "Moderate, growing evidence for stress and sleep. Effects are real but modest — a nudge, not a cure.",
    strength: 68, strengthLabel: "Moderate", studies: 213, participants: "12,900+", years: "1998–2025",
    mechanism: "An adaptogenic herb (Withania somnifera). Its withanolides blunt the stress response, partly by lowering cortisol and modulating the HPA axis — the route to its calming and sleep effects.",
    effects: { established: [
        { t: "Reduces perceived stress", d: "Consistent drops in stress questionnaires vs. placebo", icon: "brain" },
        { t: "Lowers cortisol", d: "Meaningful reductions in the primary stress hormone", icon: "activity" }],
      emerging: [
        { t: "Improves sleep quality", d: "Better sleep onset and quality in several trials", icon: "heart" },
        { t: "Modest testosterone bump (men)", d: "Small increases in some male populations", icon: "dumbbell" },
        { t: "Possible strength/recovery aid", d: "Mixed signals on training adaptations", icon: "zap" }] },
    primary: ["Stress reduction", "Sleep quality", "Cortisol management"],
    linked: ["Calmer mood / anxiety relief", "Better recovery via lower stress load", "Modest hormonal support in men", "Possible focus downstream of better sleep"],
    populations: "Studied mostly in stressed but healthy adults. Effects vary by extract (KSM-66, Sensoril).",
    sideEffects: [{ t: "Drowsiness", sev: "mild", d: "Especially higher doses or daytime use" }, { t: "GI upset", sev: "mild", d: "Occasional nausea or loose stools" }, { t: "Thyroid/liver caution", sev: "moderate", d: "Can affect thyroid; rare liver reports — screen first" }],
    interactions: "May interact with thyroid, sedative, and immunosuppressant meds. Consult a physician if you take these.",
    stacks: ["Magnesium (sleep)", "L-theanine (calm)", "Sleep hygiene"],
    effect: [{ m: "Stress", v: 6 }, { m: "Sleep", v: 5 }, { m: "Anxiety", v: 4 }, { m: "Testosterone", v: 3 }, { m: "Strength", v: 2 }],
    trend: [{ y: "'05", n: 38 }, { y: "'10", n: 71 }, { y: "'15", n: 122 }, { y: "'20", n: 178 }, { y: "'25", n: 213 }],
    dose: "300–600 mg/day standardized extract, often at night.", safety: "Generally well-tolerated short-term. Caution with thyroid or liver conditions.",
    bottomLine: "A legit, mild tool for stress and sleep — not a miracle. Best results come from a standardized extract taken consistently for several weeks, alongside actual sleep and stress habits.",
    doseDetail: "Look for a standardized extract (KSM-66 or Sensoril on the label) at 300–600 mg/day. Root extracts are the most studied. Effects build over 4–8 weeks, not overnight. Many take it in the evening for the sleep benefit.",
    cost: { level: "Cheap", note: "~$0.20–0.50 per day for a quality standardized extract." },
    keyStudies: [
      { title: "Ashwagandha for stress & anxiety", design: "RCT · ~60 stressed adults", finding: "Significant reductions in perceived-stress scores and cortisol vs. placebo over ~8 weeks." },
      { title: "Sleep quality meta-analysis", design: "Meta-analysis · multiple RCTs", finding: "Modest but consistent improvements in sleep quality and onset, strongest in people with existing insomnia." },
    ],
    myths: [
      { myth: "It skyrockets testosterone", fact: "Increases in men are real but small and variable — not a replacement for anything clinical." },
      { myth: "It works instantly", fact: "Benefits build over weeks of consistent use, unlike a fast-acting sedative." },
      { myth: "Totally risk-free for everyone", fact: "It can affect thyroid hormones and rarely the liver — people with those conditions should screen first." },
    ],
    comparison: "Vs. other stress supplements: better human evidence than most adaptogens (rhodiola, holy basil), and comparable to L-theanine for calm — though they act differently and are sometimes combined.",
  },
};

// ---- The catalog: 150+ researchable topics (breadth). Fully-profiled ones flagged. ----
const CATALOG = [
  // Supplements
  ["Creatine Monohydrate", "supplement", T.strong, true, "creatine"],
  ["Beta-Alanine", "supplement", T.strong], ["Caffeine", "supplement", T.strong], ["Whey Protein", "supplement", T.strong],
  ["Citrulline Malate", "supplement", T.moderate], ["HMB", "supplement", T.moderate], ["Sodium Bicarbonate", "supplement", T.moderate],
  ["Beetroot / Nitrate", "supplement", T.moderate], ["Electrolytes", "supplement", T.moderate], ["Collagen", "supplement", T.emerging],
  ["Glucosamine", "supplement", T.weak], ["Turmeric / Curcumin", "supplement", T.moderate], ["CoQ10", "supplement", T.moderate],
  ["Melatonin", "supplement", T.strong], ["Glutamine", "supplement", T.weak], ["ZMA", "supplement", T.weak],
  ["Tart Cherry", "supplement", T.emerging], ["Apple Cider Vinegar", "supplement", T.weak],
  // Peptides
  ["BPC-157", "peptide", T.emerging, true, "bpc157"], ["TB-500", "peptide", T.emerging], ["GHK-Cu", "peptide", T.emerging],
  ["Semaglutide (GLP-1)", "peptide", T.strong], ["Tirzepatide", "peptide", T.strong], ["Ipamorelin", "peptide", T.emerging],
  ["CJC-1295", "peptide", T.emerging], ["MOTS-c", "peptide", T.emerging], ["Melanotan II", "peptide", T.weak],
  ["Thymosin Alpha-1", "peptide", T.moderate], ["Sermorelin", "peptide", T.moderate], ["PT-141", "peptide", T.moderate],
  ["Epithalon", "peptide", T.weak], ["AOD-9604", "peptide", T.weak],
  // Nootropics
  ["L-Theanine", "nootropic", T.moderate], ["Caffeine + L-Theanine", "nootropic", T.moderate], ["Bacopa Monnieri", "nootropic", T.moderate],
  ["Lion's Mane", "nootropic", T.emerging], ["Alpha-GPC", "nootropic", T.moderate], ["Modafinil", "nootropic", T.strong],
  ["Rhodiola Rosea", "nootropic", T.moderate], ["Phosphatidylserine", "nootropic", T.moderate], ["Ginkgo Biloba", "nootropic", T.weak],
  ["Noopept", "nootropic", T.weak], ["Piracetam", "nootropic", T.weak], ["Citicoline (CDP-Choline)", "nootropic", T.moderate],
  // Vitamins
  ["Vitamin D3", "vitamin", T.strong], ["Vitamin B12", "vitamin", T.strong], ["Vitamin C", "vitamin", T.moderate],
  ["Vitamin K2", "vitamin", T.moderate], ["Folate (B9)", "vitamin", T.strong], ["Vitamin A", "vitamin", T.moderate],
  ["Vitamin E", "vitamin", T.weak], ["Vitamin B6", "vitamin", T.moderate], ["Biotin (B7)", "vitamin", T.weak],
  ["Niacin (B3)", "vitamin", T.moderate], ["Thiamine (B1)", "vitamin", T.moderate],
  // Minerals
  ["Magnesium", "mineral", T.strong], ["Zinc", "mineral", T.strong], ["Iron", "mineral", T.strong],
  ["Selenium", "mineral", T.moderate], ["Iodine", "mineral", T.strong], ["Calcium", "mineral", T.strong],
  ["Potassium", "mineral", T.strong], ["Copper", "mineral", T.moderate], ["Chromium", "mineral", T.weak],
  ["Boron", "mineral", T.emerging], ["Manganese", "mineral", T.weak],
  // Herbs & adaptogens
  ["Ashwagandha", "herb", T.moderate, true, "ashwagandha"], ["Ginseng (Panax)", "herb", T.moderate], ["Tongkat Ali", "herb", T.emerging],
  ["Fenugreek", "herb", T.emerging], ["Milk Thistle", "herb", T.moderate], ["Berberine", "herb", T.moderate],
  ["Saffron", "herb", T.moderate], ["St. John's Wort", "herb", T.moderate], ["Valerian Root", "herb", T.weak],
  ["Maca Root", "herb", T.emerging], ["Cordyceps", "herb", T.emerging], ["Reishi", "herb", T.emerging],
  ["Holy Basil (Tulsi)", "herb", T.emerging], ["Ginger", "herb", T.moderate], ["Garlic Extract", "herb", T.moderate],
  // Amino acids
  ["L-Citrulline", "amino", T.moderate], ["L-Arginine", "amino", T.weak], ["BCAAs", "amino", T.weak],
  ["EAAs", "amino", T.moderate], ["L-Tyrosine", "amino", T.moderate], ["Taurine", "amino", T.moderate],
  ["Glycine", "amino", T.moderate], ["L-Carnitine", "amino", T.moderate], ["Betaine (TMG)", "amino", T.moderate],
  ["Beta-Alanine", "amino", T.strong], ["NAC", "amino", T.moderate], ["L-Glutamine", "amino", T.weak],
  // Longevity
  ["NMN", "longevity", T.emerging], ["NR (Nicotinamide Riboside)", "longevity", T.emerging], ["Resveratrol", "longevity", T.weak],
  ["Spermidine", "longevity", T.emerging], ["Fisetin", "longevity", T.emerging], ["Quercetin", "longevity", T.moderate],
  ["Metformin (longevity)", "longevity", T.moderate], ["Rapamycin", "longevity", T.emerging], ["Ca-AKG", "longevity", T.emerging],
  ["Urolithin A", "longevity", T.emerging], ["Sulforaphane", "longevity", T.moderate], ["Astaxanthin", "longevity", T.emerging],
  // Hormonal
  ["Testosterone (TRT)", "hormonal", T.strong], ["DHEA", "hormonal", T.moderate], ["Pregnenolone", "hormonal", T.weak],
  ["Vitamin D (hormonal)", "hormonal", T.strong], ["Boron (hormonal)", "hormonal", T.emerging], ["Zinc (hormonal)", "hormonal", T.moderate],
  ["Progesterone", "hormonal", T.moderate], ["Melatonin (hormonal)", "hormonal", T.strong], ["Thyroid (T3/T4)", "hormonal", T.strong],
  // Fatty acids
  ["Omega-3 (EPA/DHA)", "fat", T.strong], ["Fish Oil", "fat", T.strong], ["Krill Oil", "fat", T.moderate],
  ["Algae Oil (vegan omega-3)", "fat", T.moderate], ["MCT Oil", "fat", T.emerging], ["CLA", "fat", T.weak],
  ["Flaxseed / ALA", "fat", T.moderate], ["Evening Primrose Oil", "fat", T.weak],
  // Gut & probiotics
  ["Probiotics (general)", "gut", T.moderate], ["Lactobacillus rhamnosus", "gut", T.moderate], ["Saccharomyces boulardii", "gut", T.moderate],
  ["Prebiotics / Inulin", "gut", T.moderate], ["Psyllium Fiber", "gut", T.strong], ["Digestive Enzymes", "gut", T.weak],
  ["L-Glutamine (gut)", "gut", T.weak], ["Butyrate", "gut", T.emerging], ["Betaine HCl", "gut", T.weak],
  // Goals & conditions
  ["Fat Loss", "goal", T.moderate], ["Muscle Gain", "goal", T.strong], ["Better Sleep", "goal", T.moderate],
  ["Anxiety Relief", "goal", T.moderate], ["Focus & Productivity", "goal", T.moderate], ["Joint Pain", "goal", T.moderate],
  ["Gut Health", "goal", T.moderate], ["Testosterone Support", "goal", T.moderate], ["Immune Support", "goal", T.moderate],
  ["Blood Sugar Control", "goal", T.moderate], ["Heart Health", "goal", T.strong], ["Skin & Anti-Aging", "goal", T.emerging],
  ["Energy & Fatigue", "goal", T.moderate], ["Migraine Prevention", "goal", T.moderate], ["Hair Loss", "goal", T.moderate],
];

const ICONS = { dumbbell: Dumbbell, zap: Zap, activity: Activity, brain: Brain, heart: Heart };
const gradeColor = (g) => (g >= 70 ? TEAL : g >= 45 ? AMBER : CORAL);
const sevColor = (s) => (s === "high" ? CORAL : s === "moderate" ? AMBER : MUTE);

// Animated count-up (respects reduced-motion)
function useCountUp(target, duration = 900) {
  const [val, setVal] = useState(0);
  useEffect(() => {
    if (typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setVal(target); return;
    }
    let raf, start;
    const step = (ts) => {
      if (!start) start = ts;
      const p = Math.min((ts - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setVal(Math.round(target * eased));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return val;
}

function ResearchTab() {
  const [query, setQuery] = useState("");
  const searchRef = useRef(null);
  useEffect(() => {
    const h = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); searchRef.current?.focus(); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  const [catFilter, setCatFilter] = useState("all");
  const [tierFilter, setTierFilter] = useState("all");
  const [active, setActive] = useState(null);
  const [notFound, setNotFound] = useState(null);
  const [loading, setLoading] = useState(false);
  const [phase, setPhase] = useState("");
  const [pending, setPending] = useState(null);
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [source, setSource] = useState(null);

  const runResearch = async (topic, category = "supplement") => {
    setActive(null); setNotFound(null); setError(null); setView(null); setLoading(true);
    // Optimistic instant feedback: show a lightweight header from catalog data
    // right away, so the page responds instantly even while the profile loads.
    const ce = CATALOG.find((c) => c[0].toLowerCase() === String(topic).toLowerCase())
            || CATALOG.find((c) => c[0].toLowerCase().includes(String(topic).toLowerCase()));
    setPending(ce ? { name: ce[0], cat: ce[1], tier: ce[2] } : { name: topic, cat: category, tier: null });
    setPhase("Searching PubMed and grading the evidence… this can take up to a minute.");
    window.scrollTo({ top: 0, behavior: "smooth" });
    try {
      const { profile, source } = await apiFetchProfile(topic, category);
      setView(engineProfileToView(profile)); setSource(source);
    } catch (e) {
      setError(e.message || "Something went wrong.");
    } finally {
      setLoading(false); setPending(null); setPhase("");
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

  // Non-gradeable entries: goals are outcomes (not compounds), and a few vague
  // multi-substance categories don't map to one gradeable intervention. Grading
  // them produces meaningless scores, so we hide them from the catalog.
  const NON_GRADEABLE = useMemo(() => new Set([
    "electrolytes", "probiotics", "prebiotics", "digestive enzymes", "thyroid", "testosterone",
  ]), []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return CATALOG.filter((c) => {
      if (c[1] === "goal") return false;                       // goals aren't compounds
      if (NON_GRADEABLE.has(c[0].toLowerCase())) return false; // vague categories
      if (catFilter !== "all" && c[1] !== catFilter) return false;
      if (tierFilter !== "all" && c[2] !== tierFilter) return false;
      if (q && !c[0].toLowerCase().includes(q)) return false;
      return true;
    }).sort((a, b) => (b[3] ? 1 : 0) - (a[3] ? 1 : 0));
  }, [query, catFilter, tierFilter, NON_GRADEABLE]);

  const showProfile = view != null;
  const totalTopics = useMemo(
    () => CATALOG.filter((c) => c[1] !== "goal" && !NON_GRADEABLE.has(c[0].toLowerCase())).length,
    [NON_GRADEABLE]
  );

  return (
    <div style={{ minHeight: "100%", background: INK, color: TEXT, fontFamily: DISPLAY }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');
        * { box-sizing: border-box; }
        .ev-btn:hover { filter:brightness(1.08); }
        .ev-chip:hover { background:${PANEL} !important; border-color:${TEAL_DIM} !important; }
        .ev-card { transition: transform .16s ease, border-color .16s ease; }
        .ev-card:hover { transform: translateY(-2px); border-color:${TEAL_DIM} !important; }
        .cat-tile { transition: transform .16s ease, border-color .16s ease, background .16s ease; cursor:pointer; }
        .cat-tile:hover { transform: translateY(-2px); border-color:${TEAL_DIM} !important; background:${PANEL} !important; }
        @keyframes pulse { 0%,100%{opacity:.35} 50%{opacity:1} }
        @keyframes rise { from{opacity:0; transform:translateY(8px)} to{opacity:1; transform:translateY(0)} }
        @keyframes riseIn { from{opacity:0; transform:translateY(14px)} to{opacity:1; transform:translateY(0)} }
        .rise { animation: rise .45s ease both; }
        .stagger > * { animation: riseIn .5s cubic-bezier(.22,.61,.36,1) both; }
        .stagger > *:nth-child(1){animation-delay:.02s} .stagger > *:nth-child(2){animation-delay:.08s}
        .stagger > *:nth-child(3){animation-delay:.14s} .stagger > *:nth-child(4){animation-delay:.20s}
        .stagger > *:nth-child(5){animation-delay:.26s} .stagger > *:nth-child(6){animation-delay:.32s}
        .stagger > *:nth-child(7){animation-delay:.38s} .stagger > *:nth-child(8){animation-delay:.44s}
        .stagger > *:nth-child(9){animation-delay:.50s} .stagger > *:nth-child(10){animation-delay:.56s}
        .stagger > *:nth-child(11){animation-delay:.62s} .stagger > *:nth-child(12){animation-delay:.68s}
        .stagger > *:nth-child(13){animation-delay:.74s} .stagger > *:nth-child(14){animation-delay:.80s}
        .growbar { transform-origin:left; animation: growbar .7s cubic-bezier(.22,.61,.36,1) both; }
        @keyframes growbar { from{transform:scaleX(0)} to{transform:scaleX(1)} }
        .tile-press:active { transform: scale(.97) !important; }
        .expandable { overflow:hidden; transition: max-height .35s ease, opacity .3s ease; }
        input::placeholder { color:${MUTE}; }
        select { -webkit-appearance:none; appearance:none; }
        ::-webkit-scrollbar { height:6px; width:6px; } ::-webkit-scrollbar-thumb { background:${LINE}; border-radius:8px; }

        /* Hero */
        .hero { padding: 40px 0 22px; text-align: center; }
        .eyebrow { font-family:${MONO}; font-size:11px; color:${TEAL}; letter-spacing:1.4px; margin-bottom:12px; }
        .hero-h1 { font-size:34px; font-weight:800; line-height:1.08; letter-spacing:-1px; margin:0 auto 20px; max-width:640px; }

        /* Search */
        .searchbar { display:flex; align-items:center; gap:10px; max-width:560px; margin:0 auto; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.10); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); border-radius:13px; padding:9px 12px; position:relative; z-index:1; transition:border-color .25s, box-shadow .25s; }
        .searchbar:hover, .searchbar:focus-within { border-color:rgba(34,211,238,0.45); box-shadow:0 0 0 1px rgba(34,211,238,0.25), 0 0 18px rgba(34,211,238,0.15); }
        .cmdk { font-family:ui-monospace,monospace; font-size:11px; color:#8497B4; border:1px solid rgba(255,255,255,0.12); background:rgba(255,255,255,0.04); padding:2px 7px; border-radius:6px; flex-shrink:0; }
        .search-go { display:flex; align-items:center; gap:6px; background:${TEAL}; color:${INK}; border:1px solid ${TEAL}; font-weight:700; font-size:14px; padding:9px 15px; border-radius:9px; cursor:pointer; flex-shrink:0; }

        /* Filter bar */
        .filterbar { display:flex; align-items:center; gap:10px; margin-bottom:12px; }
        .cat-scroll { display:flex; gap:7px; overflow-x:auto; padding:4px 0; flex:1; scrollbar-width:none; }
        .cat-scroll::-webkit-scrollbar { display:none; }
        .tier-select { flex-shrink:0; }

        /* Grid */
        .catgrid { display:grid; grid-template-columns:repeat(3,1fr); gap:11px; }

        @media (prefers-reduced-motion: reduce){ .rise{animation:none} }
        @media (min-width: 761px){ .hero-h1 { font-size:44px; letter-spacing:-1.4px; } .hero { padding:56px 0 26px; } }
        @media (max-width: 760px){
          .grid2 { grid-template-columns:1fr !important; }
          .verdictgrid { grid-template-columns:1fr !important; }
          .catgrid { grid-template-columns:1fr 1fr !important; }
          .go-label { display:none; }
          .search-go { padding:9px 12px; }
        }
        @media (max-width: 420px){ .tagline { display:none; } }
      `}</style>

      {/* Top bar */}
      <div style={{ borderBottom: `1px solid ${LINE}`, padding: "12px 20px", display: "flex", alignItems: "center", gap: 11, position: "sticky", top: 0, background: `${INK}F0`, backdropFilter: "blur(8px)", zIndex: 20 }}>
        <div onClick={() => { setActive(null); setNotFound(null); }} style={{ display: "flex", alignItems: "center", gap: 9, cursor: "pointer" }}>
          <div style={{ width: 25, height: 25, borderRadius: 7, background: `linear-gradient(135deg,${TEAL},${TEAL_DIM})`, display: "grid", placeItems: "center" }}>
            <Activity size={14} color={INK} strokeWidth={2.6} />
          </div>
          <span style={{ fontWeight: 800, letterSpacing: -0.4, fontSize: 16 }}>Clarity</span>
        </div>
        <span className="tagline" style={{ paddingLeft: 11, borderLeft: `1px solid ${LINE}`, fontFamily: DISPLAY, fontSize: 12, fontWeight: 500, color: MUTE, letterSpacing: 0.1 }}>The Data, Told Straight</span>
      </div>

      <div style={{ maxWidth: 1160, margin: "0 auto", padding: "0 22px" }}>

        {/* ===== PROFILE VIEW ===== */}
        {showProfile && (
          <ProfileView view={view} source={source} onBack={() => { setView(null); setActive(null); }} />
        )}

        {/* ===== LOADING ===== */}
        {error && (
          <div style={{ textAlign: "center", padding: "80px 0" }}>
            <div style={{ color: CORAL, fontSize: 15, marginBottom: 10 }}>{error}</div>
            <button onClick={() => { setError(null); }} className="ev-chip" style={{ background: PANEL2, border: `1px solid ${LINE}`, color: MUTE, fontFamily: MONO, fontSize: 12, padding: "7px 13px", borderRadius: 20, cursor: "pointer" }}>Back</button>
          </div>
        )}
        {loading && (
          <div style={{ paddingTop: 30 }}>
            {pending && (
              <div style={{ marginBottom: 24 }}>
                <div style={{ color: TEAL, fontSize: 11, fontWeight: 600, letterSpacing: 1.5, marginBottom: 8, textTransform: "uppercase" }}>{pending.cat}</div>
                <div style={{ color: TEXT, fontSize: 28, fontWeight: 800, letterSpacing: -0.5, textTransform: "capitalize" }}>{pending.name}</div>
                {pending.tier && (
                  <div style={{ marginTop: 8, display: "inline-flex", alignItems: "center", gap: 6, fontFamily: MONO, fontSize: 12, color: tierColor(pending.tier) }}>
                    <span style={{ width: 7, height: 7, borderRadius: 7, background: tierColor(pending.tier) }} />{pending.tier}
                  </div>
                )}
              </div>
            )}
            <div style={{ textAlign: "center", padding: "60px 0" }}>
              <div style={{ display: "inline-flex", gap: 6, marginBottom: 20 }}>
                {[0, 1, 2].map((i) => <div key={i} style={{ width: 9, height: 9, borderRadius: 9, background: TEAL, animation: `pulse 1s ${i * 0.15}s infinite` }} />)}
              </div>
              <div style={{ fontFamily: MONO, fontSize: 13, color: MUTE, maxWidth: 360, margin: "0 auto", lineHeight: 1.5 }}>{phase}</div>
            </div>
          </div>
        )}

        {/* ===== CATALOG / BROWSE VIEW ===== */}
        {!showProfile && !loading && !error && (
          <>
            {/* Hero + search — responsive, contained */}
            <div className="hero rise" style={{ position: "relative" }}>
              <div aria-hidden="true" style={{ position: "absolute", top: "-40px", left: "50%", transform: "translateX(-50%)", width: 680, height: 340, background: "radial-gradient(ellipse at center, rgba(13,148,136,0.15) 0%, rgba(13,148,136,0) 70%)", filter: "blur(40px)", pointerEvents: "none", zIndex: 0 }} />
              <div className="eyebrow">{totalTopics} TOPICS · EVIDENCE-GRADED</div>
              <h1 className="hero-h1">
                Search anything in health.<br />Get the <span style={{ color: TEAL }}>evidence</span>, not the hype.
              </h1>
              <div className="searchbar">
                <Search size={18} color={MUTE} style={{ flexShrink: 0 }} />
                <input ref={searchRef} value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submitSearch()}
                  placeholder="Search a topic…"
                  style={{ flex: 1, minWidth: 0, background: "transparent", border: "none", outline: "none", color: TEXT, fontSize: 16, fontFamily: DISPLAY, padding: "6px 0" }} />
                <span className="cmdk">⌘K</span>
                <button onClick={submitSearch} className="ev-btn search-go" aria-label="Research">
                  <Sparkles size={15} /><span className="go-label">Research</span>
                </button>
              </div>
            </div>

            {/* Single filter row: categories scroll; tiers tuck into a compact select */}
            <div className="filterbar">
              <div className="cat-scroll">
                <FilterPill active={catFilter === "all"} onClick={() => setCatFilter("all")} label="All" color={TEAL} />
                {Object.entries(CATS).filter(([k]) => k !== "goal").map(([k, v]) => (
                  <FilterPill key={k} active={catFilter === k} onClick={() => setCatFilter(k)} label={v.label} color={v.color} />
                ))}
              </div>
              <div className="tier-select">
                <select value={tierFilter} onChange={(e) => setTierFilter(e.target.value)}
                  style={{ background: PANEL2, color: tierFilter === "all" ? MUTE : tierColor(tierFilter), border: `1px solid ${LINE}`, borderRadius: 20, fontFamily: MONO, fontSize: 11.5, padding: "7px 10px", outline: "none", cursor: "pointer" }}>
                  <option value="all">Evidence: all</option>
                  <option value={T.strong}>Strong</option>
                  <option value={T.moderate}>Moderate</option>
                  <option value={T.emerging}>Emerging</option>
                  <option value={T.weak}>Weak</option>
                </select>
              </div>
            </div>

            {/* Result count + live-profile hint */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, margin: "2px 2px 14px", flexWrap: "wrap" }}>
              <span style={{ fontFamily: MONO, fontSize: 11.5, color: MUTE }}>
                {filtered.length} {filtered.length === 1 ? "topic" : "topics"}
                {catFilter !== "all" && <span style={{ color: CATS[catFilter].color }}> · {CATS[catFilter].label}</span>}
              </span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontFamily: MONO, fontSize: 10.5, color: MUTE }}>
                tap any topic to research it live
              </span>
            </div>

            {/* Coming-soon notice — encouraging, not error-like */}
            {notFound && (
              <div className="rise" style={{ background: `${TEAL}0C`, border: `1px solid ${TEAL}33`, borderRadius: 10, padding: "11px 14px", marginBottom: 14, display: "flex", gap: 10, alignItems: "flex-start" }}>
                <Sparkles size={15} color={TEAL} style={{ flexShrink: 0, marginTop: 2 }} />
                <div style={{ fontSize: 13, lineHeight: 1.45 }}>
                  <b>{notFound}</b> is in the catalog — its full profile rolls out as our engine grades the studies.
                  <span style={{ color: MUTE }}> Three are live now: tap a <b style={{ color: TEAL }}>DEEP</b> tile (Creatine, BPC-157, Ashwagandha) to see the complete experience.</span>
                </div>
              </div>
            )}

            {/* Catalog grid — the star; 2 cols mobile, 3 desktop */}
            <div className="catgrid" style={{ paddingBottom: 60 }}>
              {filtered.map((c, i) => {
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
                        <span>{meta.h > 0 ? `${meta.h} human ${meta.h === 1 ? "study" : "studies"}` : `${meta.s} analyzed`}</span>
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
              {filtered.length === 0 && (
              <div style={{ textAlign: "center", padding: "40px 0 80px", color: MUTE, fontFamily: MONO, fontSize: 13 }}>
                No topics match. Try clearing filters.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function FilterPill({ active, onClick, label, color }) {
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

// ---- Plain-language translation (rule-based, free, consistent) ----
// Converts stats a specialist reads into sentences anyone understands. This is
// the "told straight" promise: the chart is the evidence, the caption is the
// meaning. Deterministic thresholds, no LLM, no fabrication.

function effectMagnitudeWords(metric, value) {
  // For standardized effects (d/g/SMD/correlation), use Cohen-style bands.
  const smdFamily = ["cohen_d", "hedges_g", "smd", "correlation"];
  const v = Math.abs(value);
  if (smdFamily.includes(metric)) {
    if (v < 0.2) return "a very small";
    if (v < 0.5) return "a small but real";
    if (v < 0.8) return "a moderate";
    return "a large";
  }
  // ratios: distance from 1.0
  if (["odds_ratio", "risk_ratio", "hazard_ratio"].includes(metric)) {
    const d = Math.abs(value - 1);
    if (d < 0.1) return "a very small";
    if (d < 0.3) return "a modest";
    if (d < 0.6) return "a meaningful";
    return "a large";
  }
  return "a measurable"; // mean_diff etc — units vary, stay neutral
}

function plainEffect(eff) {
  if (!eff || typeof eff.value !== "number") return null;
  const lo = typeof eff.ciLow === "number" ? eff.ciLow : eff.value;
  const hi = typeof eff.ciHigh === "number" ? eff.ciHigh : eff.value;
  const nullVal = ["odds_ratio", "risk_ratio", "hazard_ratio"].includes(eff.metric) ? 1 : 0;
  const crossesNull = lo < nullVal && hi > nullVal;
  if (crossesNull) {
    return "Studies don't yet agree — the evidence so far can't confirm a clear effect.";
  }
  const mag = effectMagnitudeWords(eff.metric, eff.value);
  const dir = eff.direction === "harm" ? "change worth noting" : "benefit";
  const conf = eff.estimated ? " (precision estimated)" : "";
  return `Shows ${mag} ${dir}, consistent across studies${conf}.`;
}

function plainTier(tier, hasHuman) {
  switch (tier) {
    case "Strong": return "Well-proven in people — this is about as settled as supplement science gets.";
    case "Moderate": return "Good human evidence, though not yet airtight.";
    case "Emerging": return "Early signs only — too little human data to rely on yet.";
    case "Preliminary": return hasHuman ? "Very limited human evidence so far." : "Mostly lab or animal data — unproven in people.";
    default: return "";
  }
}

function evidenceMapSummary(outcomes) {
  const strong = outcomes.filter((o) => o.tier === "Strong").map((o) => o.outcome);
  const mod = outcomes.filter((o) => o.tier === "Moderate").map((o) => o.outcome);
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const parts = [];
  if (strong.length) parts.push(`strongly supported for ${strong.map(cap).join(", ")}`);
  if (mod.length) parts.push(`moderately for ${mod.map(cap).join(", ")}`);
  if (!parts.length) return "Evidence is still early across all measured outcomes.";
  return `Best evidence is ${parts.join("; ")}.`;
}

// ---- Full profile view ----
function LayerMiniChart({ mech, preclin, human }) {
  const bars = [
    { label: "mech", v: mech, c: "#5FA8F5" },
    { label: "preclin", v: preclin, c: VIOLET },
    { label: "human", v: human, c: TEAL },
  ];
  return (
    <div>
      <div style={{ color: "#5A6B87", fontSize: 10, marginBottom: 6 }}>EVIDENCE LAYERS</div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 56 }}>
        {bars.map((b) => (
          <div key={b.label} style={{ flex: 1, textAlign: "center" }}>
            <div className="growbar-v" style={{ height: Math.max(3, (b.v / 100) * 50), background: b.v > 3 ? b.c : "#2A3854", borderRadius: "3px 3px 0 0" }} />
            <div style={{ color: MUTE, fontSize: 9, marginTop: 4 }}>{b.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ForestMini({ eff }) {
  if (!eff || typeof eff.value !== "number") {
    return <div style={{ textAlign: "center", color: "#5A6B87", fontSize: 11, lineHeight: 1.5 }}>No pooled effect size<br/>reported in abstracts</div>;
  }
  // map an effect (smd-ish) onto a 0..1.0 axis; clamp for display
  const xmin = -0.2, xmax = 1.0;
  const sx = (v) => 20 + ((Math.max(xmin, Math.min(xmax, v)) - xmin) / (xmax - xmin)) * 180;
  const lo = typeof eff.ciLow === "number" ? eff.ciLow : eff.value;
  const hi = typeof eff.ciHigh === "number" ? eff.ciHigh : eff.value;
  const crosses = lo < 0 && hi > 0;
  const col = crosses ? AMBER : TEAL;
  return (
    <div>
      <div style={{ color: "#5A6B87", fontSize: 10, marginBottom: 6 }}>HOW BIG IS THE BENEFIT?</div>
      <svg viewBox="0 0 220 44" width="100%" role="img" aria-label={`Pooled effect ${eff.value}, CI ${lo} to ${hi}`}>
        <line x1="20" y1="22" x2="200" y2="22" stroke={LINE} strokeWidth="1" />
        <line x1={sx(0)} y1="8" x2={sx(0)} y2="36" stroke="#5A6B87" strokeWidth="1" />
        <text x={sx(0)} y="6" fill="#5A6B87" fontSize="8" textAnchor="middle" fontFamily="Inter">0</text>
        <line x1={sx(lo)} y1="22" x2={sx(hi)} y2="22" stroke={col} strokeWidth="3" />
        <line x1={sx(lo)} y1="17" x2={sx(lo)} y2="27" stroke={col} strokeWidth="2" />
        <line x1={sx(hi)} y1="17" x2={sx(hi)} y2="27" stroke={col} strokeWidth="2" />
        <circle cx={sx(eff.value)} cy="22" r="5" fill={col} />
        <text x={sx(eff.value)} y="42" fill={MUTE} fontSize="9" textAnchor="middle" fontFamily={MONO}>
          {eff.value}{typeof eff.ciLow === "number" ? ` (${eff.ciLow}–${eff.ciHigh})` : ""}{eff.estimated ? "*" : ""}
        </text>
      </svg>
    </div>
  );
}

function EvidenceMap({ outcomes }) {
  // position each outcome on an Emerging->Strong axis by tier
  const tierX = { Preliminary: 90, Emerging: 150, Moderate: 300, Strong: 490 };
  const rows = outcomes.map((o) => ({ name: o.outcome, x: tierX[o.tier] || 150, color: o.tierColor }));
  const H = 20 + rows.length * 30 + 20;
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  return (
    <div style={{ background: "#0E1728", border: `0.5px solid ${LINE}`, borderRadius: 12, padding: "16px 18px", marginBottom: 22 }}>
      <div style={{ color: MUTE, fontSize: 11, fontWeight: 600, letterSpacing: 1, marginBottom: 6 }}>WHAT IT'S GOOD FOR</div>
      <div style={{ color: "#C6D2E2", fontSize: 13.5, lineHeight: 1.6, marginBottom: 16 }}>{evidenceMapSummary(outcomes)}</div>
      <svg viewBox={`0 0 560 ${H}`} width="100%" role="img" aria-label="Evidence map of all outcomes by strength">
        {[150, 300, 490].map((x, i) => <line key={i} x1={x} y1="8" x2={x} y2={H - 22} stroke={LINE} strokeWidth="1" />)}
        <text x="150" y={H - 6} fill="#5A6B87" fontSize="9" textAnchor="middle" fontFamily="Inter">Emerging</text>
        <text x="300" y={H - 6} fill="#5A6B87" fontSize="9" textAnchor="middle" fontFamily="Inter">Moderate</text>
        <text x="490" y={H - 6} fill="#5A6B87" fontSize="9" textAnchor="middle" fontFamily="Inter">Strong</text>
        {rows.map((r, i) => {
          const y = 20 + i * 30;
          return (
            <g key={r.name}>
              <text x="0" y={y + 4} fill={TEXT} fontSize="12" fontFamily="Inter">{cap(r.name).length > 16 ? cap(r.name).slice(0, 15) + "…" : cap(r.name)}</text>
              <rect x="120" y={y} width={Math.max(4, r.x - 120)} height="8" rx="4" fill={r.color} />
              <circle cx={r.x} cy={y + 4} r="6" fill={r.color} />
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function findDetail(ex, outcome) {
  if (!ex || !ex.outcome_detail || !outcome) return null;
  const t = String(outcome).toLowerCase().trim();
  return ex.outcome_detail.find((d) => String(d.outcome || "").toLowerCase().trim() === t) || null;
}

function OutcomeGraphicCard({ o, detail }) {
  const [showData, setShowData] = useState(false);
  const effWords = plainEffect(o.headlineEffect);
  return (
    <div style={{ background: PANEL, border: `0.5px solid ${LINE}`, borderRadius: 12, padding: "18px 20px", marginBottom: 12, transition: "border-color .25s ease-out, background .25s ease-out" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ color: TEXT, fontSize: 16.5, fontWeight: 650, letterSpacing: -0.2, textTransform: "capitalize" }}>{o.outcome}</span>
        <span style={{ background: o.tierColor, color: INK, fontSize: 10, fontWeight: 700, padding: "2px 9px", borderRadius: 12 }}>{o.tier}</span>
      </div>

      {/* PLAIN LANGUAGE LEADS */}
      <div style={{ color: "#C6D2E2", fontSize: 13.5, lineHeight: 1.6, marginBottom: 6 }}>{plainTier(o.tier, o.hasHuman)}</div>
      {detail && detail.what_studies_show ? (
        <div style={{ color: "#C6D2E2", fontSize: 13.5, lineHeight: 1.72, marginTop: 8, marginBottom: 6 }}>{detail.what_studies_show}</div>
      ) : null}
      {detail && detail.why_this_grade ? (
        <div style={{ color: MUTE, fontSize: 12.5, lineHeight: 1.6, marginBottom: 6, paddingLeft: 10, borderLeft: `2px solid ${o.tierColor}55` }}>{detail.why_this_grade}</div>
      ) : null}
      {effWords ? <div style={{ color: MUTE, fontSize: 12.5, lineHeight: 1.55, marginBottom: 4 }}>{effWords}</div> : null}

      {/* the "why", plain */}
      <div style={{ color: MUTE, fontSize: 12, lineHeight: 1.55, marginTop: 6 }}>
        {o.reasons && o.reasons.length ? o.reasons.join(" ") : "Graded from the available studies."}
        {" "}<StudyToggle pmids={o.pmids} nStudies={o.nStudies} />
      </div>

      {/* CHARTS AS SUPPORTING DETAIL — collapsed by default */}
      <button onClick={() => setShowData(!showData)} className="ev-btn"
        style={{ marginTop: 11, background: "transparent", border: `1px solid ${LINE}`, color: MUTE, fontSize: 11, padding: "4px 10px", borderRadius: 7, cursor: "pointer" }}>
        {showData ? "Hide the data" : "See the data"}
      </button>
      {showData && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "center", marginTop: 12, borderTop: `0.5px solid ${LINE}`, paddingTop: 14 }}>
          <LayerMiniChart mech={o.layers.mechanistic} preclin={o.layers.preclinical} human={o.layers.human} />
          <ForestMini eff={o.headlineEffect} />
        </div>
      )}
    </div>
  );
}

function StudyToggle({ pmids, nStudies }) {
  const [open, setOpen] = useState(false);
  if (!pmids || !pmids.length) return <span style={{ color: MUTE }}>{nStudies} studies analyzed</span>;
  return (
    <>
      <span onClick={() => setOpen(!open)} style={{ color: "#5FA8F5", cursor: "pointer" }}>{open ? "hide" : `show ${pmids.length} studies`} ↗</span>
      {open && (
        <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
          {pmids.map((pid) => {
            const num = String(pid).replace("PMID:", "");
            return <a key={pid} href={`https://pubmed.ncbi.nlm.nih.gov/${num}/`} target="_blank" rel="noreferrer" style={{ fontFamily: MONO, fontSize: 11, color: "#5FA8F5", textDecoration: "none", border: `1px solid ${LINE}`, padding: "2px 7px", borderRadius: 6 }}>{num}</a>;
          })}
        </div>
      )}
    </>
  );
}

function ProfileView({ view, source, onBack }) {
  if (!view) return null;
  const ex = view.explanation || null;
  const proven = view.outcomes.filter((o) => o.tier === "Strong" || o.tier === "Moderate");
  const promising = view.outcomes.filter((o) => o.tier === "Emerging" || o.tier === "Preliminary");
  return (
    <div className="rise" style={{ paddingBottom: 90, paddingTop: 20 }}>
      <button onClick={onBack} className="ev-chip" style={{ display: "inline-flex", alignItems: "center", gap: 7, background: PANEL2, border: `1px solid ${LINE}`, color: MUTE, fontFamily: MONO, fontSize: 12, padding: "7px 13px", borderRadius: 20, cursor: "pointer", marginBottom: 18 }}>
        <ArrowLeft size={14} /> Back to catalog
      </button>

      {/* HEADER */}
      <div style={{ background: "#0E1728", border: `0.5px solid ${LINE}`, borderRadius: 14, padding: "22px 24px", marginBottom: 14, display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 20, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 250 }}>
          <div style={{ color: TEAL, fontSize: 11, fontWeight: 600, letterSpacing: 1.5, marginBottom: 8, textTransform: "uppercase" }}>{view.cat}</div>
          <div style={{ color: TEXT, fontSize: 30, fontWeight: 800, letterSpacing: -0.5, marginBottom: 12, textTransform: "capitalize" }}>{view.name}</div>
          <div style={{ color: "#B8C4D6", fontSize: 14, lineHeight: 1.7, maxWidth: 430, marginBottom: 16 }}>{view.verdict}</div>
          <div style={{ display: "flex", gap: 22, alignItems: "baseline", fontFamily: MONO }}>
            <div><span style={{ color: TEXT, fontSize: 16, fontWeight: 700 }}>{view.studyCount}</span><span style={{ color: MUTE, fontSize: 12 }}> studies analyzed</span></div>
            <div><span style={{ color: TEXT, fontSize: 16, fontWeight: 700 }}>{view.outcomes.length}</span><span style={{ color: MUTE, fontSize: 12 }}> outcomes</span></div>
          </div>
          <div style={{ color: "#5A6B87", fontSize: 11, marginTop: 8, lineHeight: 1.5, maxWidth: 420 }}>Count reflects studies retrieved and graded for these outcomes — not the compound’s total literature.</div>
        </div>
        <div style={{ textAlign: "center" }}>
          <div style={{ width: 92, height: 92, borderRadius: "50%", border: `3px solid ${view.tierColor}`, display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 8px", background: "rgba(56,225,196,0.06)" }}>
            <span style={{ color: view.tierColor, fontSize: 16, fontWeight: 800 }}>{String(view.tier).toUpperCase()}</span>
          </div>
          <div style={{ color: MUTE, fontSize: 11 }}>overall evidence</div>
        </div>
      </div>

      {/* EVIDENCE MAP */}
      <EvidenceMap outcomes={view.outcomes} />

      {ex && ex.what_it_is ? (
        <div style={{ marginBottom: 30 }}>
          <div style={{ color: TEAL, fontSize: 10.5, fontWeight: 700, letterSpacing: 1.6, marginBottom: 10 }}>WHAT IT IS</div>
          <div style={{ color: "#C6D2E2", fontSize: 15, lineHeight: 1.8, letterSpacing: 0.01 }}>{ex.what_it_is}</div>
        </div>
      ) : null}

      {ex && ex.how_it_works ? (
        <div style={{ marginBottom: 30 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <span style={{ fontFamily: MONO, color: TEAL, fontSize: 13 }}>01</span>
            <span style={{ color: TEXT, fontSize: 19, fontWeight: 700, letterSpacing: -0.3 }}>How it works in the body</span>
          </div>
          <div style={{ color: "#C6D2E2", fontSize: 15, lineHeight: 1.8, letterSpacing: 0.01 }}>{ex.how_it_works}</div>
        </div>
      ) : null}

      {ex && ex.evidence_base ? (
        <div style={{ marginBottom: 30 }}>
          <div style={{ color: TEAL, fontSize: 10.5, fontWeight: 700, letterSpacing: 1.6, marginBottom: 10 }}>THE RESEARCH BEHIND IT</div>
          <div style={{ color: "#C6D2E2", fontSize: 15, lineHeight: 1.8, letterSpacing: 0.01 }}>{ex.evidence_base}</div>
        </div>
      ) : null}

      {/* EFFECTS ON HUMANS */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 5 }}>
          <span style={{ fontFamily: MONO, color: TEAL, fontSize: 13 }}>02</span>
          <span style={{ color: TEXT, fontSize: 19, fontWeight: 700, letterSpacing: -0.3 }}>Effects on humans</span>
        </div>
        <div style={{ color: MUTE, fontSize: 12, marginBottom: 14, paddingLeft: 34 }}>Each outcome graded on how evidence builds: mechanism → animal → human.</div>
        {proven.map((o) => <OutcomeGraphicCard key={o.outcome} o={o} detail={findDetail(ex, o.outcome)} />)}
        {promising.length ? (
          <div style={{ borderTop: `0.5px dashed #3A3468`, paddingTop: 12, marginTop: 4 }}>
            <div style={{ color: VIOLET, fontSize: 11, fontWeight: 600, letterSpacing: 1, marginBottom: 8 }}>PROMISING — NOT YET PROVEN</div>
            {promising.map((o) => (
              <div key={o.outcome} style={{ background: "rgba(139,125,242,0.05)", border: `0.5px dashed #3A3468`, borderRadius: 10, padding: "12px 15px", marginBottom: 8, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div><span style={{ color: TEXT, fontSize: 14, fontWeight: 600, textTransform: "capitalize" }}>{o.outcome}</span>
                  <div style={{ color: MUTE, fontSize: 12.5, marginTop: 4, lineHeight: 1.6 }}>{(findDetail(ex, o.outcome) || {}).what_studies_show || (o.reasons && o.reasons[0]) || "Preliminary evidence only."}</div></div>
                <span style={{ background: "rgba(139,125,242,0.15)", color: VIOLET, fontSize: 10, fontWeight: 600, padding: "2px 9px", borderRadius: 12, whiteSpace: "nowrap" }}>{o.tier}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      {ex && ex.emerging_research ? (
        <div style={{ marginBottom: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <span style={{ fontFamily: MONO, color: TEAL, fontSize: 13 }}>03</span>
            <span style={{ color: TEXT, fontSize: 19, fontWeight: 700, letterSpacing: -0.3 }}>On the horizon</span>
          </div>
          <div style={{ color: "#C6D2E2", fontSize: 15, lineHeight: 1.8, letterSpacing: 0.01 }}>{ex.emerging_research}</div>
        </div>
      ) : null}

      {ex && ex.open_questions ? (
        <div style={{ background: "rgba(139,125,242,0.05)", border: `0.5px solid rgba(139,125,242,0.18)`, borderRadius: 10, padding: "14px 16px", marginBottom: 14 }}>
          <div style={{ color: VIOLET, fontSize: 11, fontWeight: 600, letterSpacing: 1, marginBottom: 7 }}>WHAT WE STILL DON'T KNOW</div>
          <div style={{ color: "#C6D2E2", fontSize: 13.5, lineHeight: 1.7 }}>{ex.open_questions}</div>
        </div>
      ) : null}

      {ex && ex.caveats ? (
        <div style={{ background: "rgba(242,180,65,0.06)", border: `0.5px solid rgba(242,180,65,0.2)`, borderRadius: 10, padding: "12px 15px", marginBottom: 18 }}>
          <span style={{ color: AMBER, fontSize: 12, fontWeight: 600 }}>Worth knowing: </span>
          <span style={{ color: "#C6D2E2", fontSize: 13, lineHeight: 1.6 }}>{ex.caveats}</span>
        </div>
      ) : null}

      <div style={{ borderTop: `0.5px solid ${LINE}`, paddingTop: 14, color: "#5A6B87", fontSize: 11, textAlign: "center", lineHeight: 1.6 }}>
        {ex ? "Explanation AI-generated from the graded evidence · " : ""}grades &amp; charts from real PubMed data · research &amp; education, not medical advice
      </div>
    </div>
  );
}

// Expandable study card
function StudyCard({ s }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="ev-card" onClick={() => setOpen((o) => !o)}
      style={{ background: PANEL2, border: `1px solid ${LINE}`, borderRadius: 10, padding: "13px 15px", cursor: "pointer" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.3 }}>{s.title}</span>
          <span style={{ fontFamily: MONO, fontSize: 10.5, color: CATS.nootropic.color }}>{s.design}</span>
        </div>
        <span style={{ fontFamily: MONO, fontSize: 18, color: MUTE, transform: open ? "rotate(45deg)" : "none", transition: "transform .25s ease", flexShrink: 0 }}>+</span>
      </div>
      <div className="expandable" style={{ maxHeight: open ? 120 : 0, opacity: open ? 1 : 0, marginTop: open ? 10 : 0 }}>
        <p style={{ fontSize: 13.5, lineHeight: 1.5, color: TEXT, opacity: 0.85, margin: 0 }}>{s.finding}</p>
      </div>
    </div>
  );
}

// Myth vs fact row
function MythRow({ m }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 8, background: PANEL2, border: `1px solid ${LINE}`, borderRadius: 10, padding: "13px 15px" }}>
      <div style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
        <span style={{ fontFamily: MONO, fontSize: 9.5, color: CORAL, background: `${CORAL}18`, border: `1px solid ${CORAL}44`, padding: "2px 6px", borderRadius: 5, flexShrink: 0, letterSpacing: 0.5, marginTop: 1 }}>MYTH</span>
        <span style={{ fontSize: 14, color: TEXT, opacity: 0.7, textDecoration: "line-through", textDecorationColor: `${CORAL}88`, lineHeight: 1.4 }}>{m.myth}</span>
      </div>
      <div style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
        <span style={{ fontFamily: MONO, fontSize: 9.5, color: TEAL, background: `${TEAL}18`, border: `1px solid ${TEAL}44`, padding: "2px 6px", borderRadius: 5, flexShrink: 0, letterSpacing: 0.5, marginTop: 1 }}>FACT</span>
        <span style={{ fontSize: 14, lineHeight: 1.45 }}>{m.fact}</span>
      </div>
    </div>
  );
}

function EffectColumn({ title, sub, list, solid }) {
  if (!list || list.length === 0) {
    return (
      <div style={{ marginTop: 16 }}>
        <ColHeader title={title} sub={sub} solid={solid} />
        <div style={{ marginTop: 8, fontSize: 13.5, color: MUTE, fontStyle: "italic", paddingLeft: 2 }}>No effects reach this tier yet — the human evidence isn't there.</div>
      </div>
    );
  }
  return (
    <div style={{ marginTop: 16 }}>
      <ColHeader title={title} sub={sub} solid={solid} />
      <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }} className="grid2">
        {list.map((e, i) => {
          const Ic = ICONS[e.icon] || Activity;
          return (
            <div key={i} className="ev-card" style={{ display: "flex", gap: 11, background: PANEL2, border: `1px solid ${LINE}`, borderRadius: 10, padding: "13px 14px" }}>
              <div style={{ width: 30, height: 30, borderRadius: 8, background: solid ? `${TEAL}18` : `${AMBER}14`, display: "grid", placeItems: "center", flexShrink: 0 }}>
                <Ic size={16} color={solid ? TEAL : AMBER} />
              </div>
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 600, lineHeight: 1.3 }}>{e.t}</div>
                <div style={{ fontSize: 12, color: MUTE, lineHeight: 1.4, marginTop: 2 }}>{e.d}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
function ColHeader({ title, sub, solid }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
      {solid ? <CheckCircle2 size={14} color={TEAL} /> : <CircleDashed size={14} color={AMBER} />}
      <span style={{ fontSize: 13, fontWeight: 700, color: solid ? TEAL : AMBER, letterSpacing: 0.3 }}>{title}</span>
      <span style={{ fontSize: 12, color: MUTE }}>· {sub}</span>
    </div>
  );
}
function BenefitCard({ k, icon, title, sub, items, color }) {
  return (
    <div style={{ background: PANEL, border: `1px solid ${LINE}`, borderRadius: 12, padding: "18px 20px" }}>
      <SectionTitle icon={icon} k={k} t={title} s={sub} tight />
      <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 9 }}>
        {items.map((it, i) => (
          <div key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <span style={{ marginTop: 6, width: 6, height: 6, borderRadius: 6, background: color, flexShrink: 0 }} />
            <span style={{ fontSize: 14, lineHeight: 1.4 }}>{it}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
function StrengthMeter({ value, label }) {
  const animated = useCountUp(value, 1100);
  const data = [{ v: animated, fill: gradeColor(value) }];
  return (
    <div style={{ width: 180, textAlign: "center" }}>
      <div style={{ position: "relative", height: 150 }}>
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart innerRadius="72%" outerRadius="100%" data={data} startAngle={220} endAngle={-40}>
            <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
            <RadialBar background={{ fill: PANEL2 }} dataKey="v" cornerRadius={20} isAnimationActive={false} />
          </RadialBarChart>
        </ResponsiveContainer>
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", pointerEvents: "none" }}>
          <div>
            <div style={{ fontFamily: MONO, fontSize: 38, fontWeight: 700, color: gradeColor(value), lineHeight: 1 }}>{animated}</div>
            <div style={{ fontFamily: MONO, fontSize: 10, color: MUTE, letterSpacing: 1 }}>/ 100</div>
          </div>
        </div>
      </div>
      <div style={{ fontFamily: MONO, fontSize: 12, color: gradeColor(value), letterSpacing: 1, marginTop: 2 }}>{label.toUpperCase()}</div>
      <div style={{ fontSize: 11, color: MUTE, marginTop: 3 }}>evidence strength</div>
    </div>
  );
}
function SectionTitle({ icon, k, t, s, tight }) {
  return (
    <div style={{ marginBottom: tight ? 4 : 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <span style={{ fontFamily: MONO, fontSize: 11, color: TEAL, opacity: 0.7 }}>{k}</span>
        <span style={{ color: TEAL, display: "flex" }}>{icon}</span>
        <span style={{ fontSize: 16, fontWeight: 700, letterSpacing: -0.3 }}>{t}</span>
      </div>
      {s && <div style={{ color: MUTE, fontSize: 13, marginTop: 3, marginLeft: 29 }}>{s}</div>}
    </div>
  );
}
function InfoCard({ k, title, body, accent }) {
  return (
    <div style={{ background: PANEL, border: `1px solid ${LINE}`, borderRadius: 12, padding: "18px 20px", display: "flex", gap: 14 }}>
      <div style={{ width: 3, borderRadius: 3, background: accent, flexShrink: 0 }} />
      <div>
        <div style={{ fontFamily: MONO, fontSize: 11, color: MUTE, letterSpacing: 1, marginBottom: 6 }}>{k} · {title.toUpperCase()}</div>
        <div style={{ fontSize: 14.5, lineHeight: 1.5 }}>{body}</div>
      </div>
    </div>
  );
}



// ---- Supplement library (with evidence + interaction tags) ----
const LIB = [
  { name: "Creatine Monohydrate", tier: "Strong", score: 92, tags: ["performance"], serotonin: false },
  { name: "Magnesium Glycinate", tier: "Moderate", score: 68, tags: ["sleep", "calm"], serotonin: false },
  { name: "Ashwagandha", tier: "Moderate", score: 68, tags: ["stress", "sleep"], serotonin: false },
  { name: "L-Theanine", tier: "Moderate", score: 64, tags: ["calm", "focus"], serotonin: false },
  { name: "Omega-3 (EPA/DHA)", tier: "Strong", score: 84, tags: ["heart", "mood"], serotonin: false },
  { name: "Vitamin D3", tier: "Strong", score: 82, tags: ["immune", "mood"], serotonin: false },
  { name: "5-HTP", tier: "Emerging", score: 44, tags: ["mood", "sleep"], serotonin: true },
  { name: "St. John's Wort", tier: "Moderate", score: 60, tags: ["mood"], serotonin: true },
  { name: "Melatonin", tier: "Strong", score: 80, tags: ["sleep"], serotonin: false },
  { name: "Tongkat Ali", tier: "Emerging", score: 46, tags: ["hormonal"], serotonin: false },
  { name: "Caffeine", tier: "Strong", score: 88, tags: ["focus", "performance"], serotonin: false },
  { name: "Rhodiola Rosea", tier: "Moderate", score: 62, tags: ["stress", "focus"], serotonin: false },
];
const TIMING = ["Morning", "Midday", "Evening", "Pre-workout"];
const rgTierColor = (t) => (t === "Strong" ? TEAL : t === "Moderate" ? AMBER : t === "Emerging" ? VIOLET : CORAL);

// ---- Simulated wearable data (what a Whoop/Oura/Apple Watch would stream) ----
// A stack change happens on day 14 (added Magnesium) — see the sleep/HRV lift after.
const DAYS = 28;
const CHANGE_DAY = 14;
function genSeries(base, lift, noise, seed) {
  let s = seed;
  const rnd = () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };
  return Array.from({ length: DAYS }, (_, i) => {
    const post = i >= CHANGE_DAY ? lift : 0;
    return Math.round((base + post + (rnd() - 0.5) * noise) * 10) / 10;
  });
}
const WEARABLE = {
  sleep: genSeries(6.8, 0.9, 1.1, 11),   // hours — rises after magnesium
  hrv: genSeries(52, 9, 8, 23),          // ms — recovery marker, rises
  rhr: genSeries(58, -3, 4, 37),         // resting HR — drops (good)
  strain: genSeries(11, 0.4, 3, 51),     // activity/strain — flat (control)
};

function RegimenTab() {
  const [connected, setConnected] = useState(false);
  const [connectingVia, setConnectingVia] = useState(null);
  const [stack, setStack] = useState([
    { id: 1, name: "Creatine Monohydrate", dose: "5 g", timing: "Morning", start: "4 weeks ago" },
    { id: 2, name: "Omega-3 (EPA/DHA)", dose: "2 g", timing: "Morning", start: "3 weeks ago" },
    { id: 3, name: "Magnesium Glycinate", dose: "300 mg", timing: "Evening", start: "2 weeks ago" },
  ]);
  const [adding, setAdding] = useState(false);
  const [metric, setMetric] = useState("sleep");
  const [checkin, setCheckin] = useState({ mood: 3, focus: 3, stress: 3 });
  const [checkinDone, setCheckinDone] = useState(false);

  // ---- Stack analysis (the tool, not the read) ----
  const analysis = useMemo(() => {
    const entries = stack.map((s) => LIB.find((l) => l.name === s.name)).filter(Boolean);
    const serotoninCount = entries.filter((e) => e.serotonin).length;
    const weak = entries.filter((e) => e.score < 50);
    const avgScore = entries.length ? Math.round(entries.reduce((a, e) => a + e.score, 0) / entries.length) : 0;
    const flags = [];
    if (serotoninCount >= 2) flags.push({ sev: "high", text: `${serotoninCount} items raise serotonin — combining them risks serotonin syndrome. Space them or consult a doctor.` });
    weak.forEach((w) => flags.push({ sev: "med", text: `${w.name} has weak evidence (${w.score}/100) — you may be paying for little benefit.` }));
    // simple timing note
    const eveningStim = stack.some((s) => s.timing === "Evening" && (s.name.includes("Caffeine")));
    if (eveningStim) flags.push({ sev: "med", text: "A stimulant is scheduled for evening — may hurt the sleep you're tracking." });
    return { avgScore, flags, count: entries.length };
  }, [stack]);

  const metricMeta = {
    sleep: { label: "Sleep", unit: "hrs", color: TEAL, icon: Moon, data: WEARABLE.sleep, good: "up" },
    hrv: { label: "HRV (recovery)", unit: "ms", color: VIOLET, icon: Activity, data: WEARABLE.hrv, good: "up" },
    rhr: { label: "Resting HR", unit: "bpm", color: AMBER, icon: Heart, data: WEARABLE.rhr, good: "down" },
    strain: { label: "Activity", unit: "", color: "#5FA8F5", icon: Zap, data: WEARABLE.strain, good: "flat" },
  };
  const mm = metricMeta[metric];
  const chartData = mm.data.map((v, i) => ({ day: i + 1, v }));
  const pre = mm.data.slice(0, CHANGE_DAY);
  const post = mm.data.slice(CHANGE_DAY);
  const preAvg = pre.reduce((a, b) => a + b, 0) / pre.length;
  const postAvg = post.reduce((a, b) => a + b, 0) / post.length;
  const delta = postAvg - preAvg;
  const pct = Math.round((delta / preAvg) * 100);

  return (
    <div style={{ minHeight: "100%", background: INK, color: TEXT, fontFamily: DISPLAY }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');
        * { box-sizing: border-box; }
        .btn:hover { filter: brightness(1.08); }
        .card { transition: transform .16s ease, border-color .16s ease; }
        .card:active { transform: scale(.99); }
        @keyframes rise { from{opacity:0; transform:translateY(10px)} to{opacity:1; transform:translateY(0)} }
        .rise { animation: rise .45s ease both; }
        @media (max-width:760px){ .grid2{grid-template-columns:1fr !important} .metricrow{overflow-x:auto} }
      `}</style>

      {/* Header */}
      <div style={{ borderBottom: `1px solid ${LINE}`, padding: "13px 20px", display: "flex", alignItems: "center", gap: 9, position: "sticky", top: 0, background: `${INK}F0`, backdropFilter: "blur(8px)", zIndex: 20 }}>
        <div style={{ width: 25, height: 25, borderRadius: 7, background: `linear-gradient(135deg,${TEAL},${TEAL_DIM})`, display: "grid", placeItems: "center" }}>
          <Activity size={14} color={INK} strokeWidth={2.6} />
        </div>
        <span style={{ fontWeight: 800, letterSpacing: -0.4, fontSize: 16 }}>Clarity</span>
        <span style={{ fontFamily: MONO, fontSize: 10.5, color: TEAL, border: `1px solid ${TEAL_DIM}`, padding: "3px 9px", borderRadius: 20, marginLeft: 2 }}>My Regimen</span>
      </div>

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "22px 20px 90px" }}>

        {/* ===== CONNECT TRACKER ===== */}
        {!connected ? (
          <div className="rise" style={{ background: PANEL, border: `1px solid ${LINE}`, borderRadius: 16, padding: "26px 24px", textAlign: "center", marginBottom: 18 }}>
            <div style={{ width: 46, height: 46, borderRadius: 13, background: `${TEAL}18`, display: "grid", placeItems: "center", margin: "0 auto 14px" }}>
              <Watch size={24} color={TEAL} />
            </div>
            <h2 style={{ fontSize: 21, fontWeight: 800, letterSpacing: -0.5, margin: "0 0 6px" }}>Connect your tracker</h2>
            <p style={{ color: MUTE, fontSize: 14.5, lineHeight: 1.5, margin: "0 auto 20px", maxWidth: 440 }}>
              We read sleep, HRV, and recovery automatically — so you never log them by hand. You only tell us what you take and how you feel.
            </p>
            <div className="grid2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, maxWidth: 440, margin: "0 auto" }}>
              {[
                { k: "apple", label: "Apple Health", icon: Smartphone, note: "Watch, Oura, Whoop → all in one" },
                { k: "whoop", label: "Whoop", icon: Activity, note: "Strain & recovery" },
                { k: "oura", label: "Oura Ring", icon: Activity, note: "Sleep & readiness" },
                { k: "manual", label: "Skip / manual", icon: Plus, note: "Enter data yourself" },
              ].map((o) => {
                const Ic = o.icon;
                return (
                  <button key={o.k} className="btn card" onClick={() => { setConnectingVia(o.k); setTimeout(() => setConnected(true), 900); }}
                    style={{ background: PANEL2, border: `1px solid ${connectingVia === o.k ? TEAL : LINE}`, borderRadius: 11, padding: "14px 14px", cursor: "pointer", textAlign: "left", display: "flex", gap: 11, alignItems: "center" }}>
                    <div style={{ width: 34, height: 34, borderRadius: 9, background: `${TEAL}14`, display: "grid", placeItems: "center", flexShrink: 0 }}>
                      {connectingVia === o.k ? <span style={{ fontFamily: MONO, fontSize: 10, color: TEAL }}>•••</span> : <Ic size={17} color={TEAL} />}
                    </div>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>{o.label}</div>
                      <div style={{ fontSize: 11, color: MUTE }}>{o.note}</div>
                    </div>
                  </button>
                );
              })}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "flex-start", justifyContent: "center", marginTop: 18, maxWidth: 440, marginLeft: "auto", marginRight: "auto" }}>
              <Shield size={13} color={MUTE} style={{ flexShrink: 0, marginTop: 2 }} />
              <span style={{ fontSize: 11, color: MUTE, lineHeight: 1.4, textAlign: "left" }}>
                Your health data is private and encrypted. It's never sold or shared without your explicit, separate consent.
              </span>
            </div>
          </div>
        ) : (
          <>
            {/* ===== CONNECTED BANNER ===== */}
            <div className="rise" style={{ display: "flex", alignItems: "center", gap: 10, background: `${TEAL}10`, border: `1px solid ${TEAL}33`, borderRadius: 12, padding: "11px 15px", marginBottom: 16 }}>
              <div style={{ width: 26, height: 26, borderRadius: 8, background: `${TEAL}1A`, display: "grid", placeItems: "center" }}><Check size={15} color={TEAL} /></div>
              <span style={{ fontSize: 13.5 }}><b>Tracker connected.</b> <span style={{ color: MUTE }}>Sleep, HRV & recovery are syncing automatically — 28 days of history loaded.</span></span>
            </div>

            {/* ===== STACK HEALTH SUMMARY ===== */}
            <div className="rise grid2" style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 16, alignItems: "center", background: PANEL, border: `1px solid ${LINE}`, borderRadius: 14, padding: "18px 20px", marginBottom: 14 }}>
              <div style={{ textAlign: "center", paddingRight: 16, borderRight: `1px solid ${LINE}` }}>
                <div style={{ fontFamily: MONO, fontSize: 34, fontWeight: 700, color: rgTierColor(analysis.avgScore >= 70 ? "Strong" : analysis.avgScore >= 50 ? "Moderate" : "Emerging"), lineHeight: 1 }}>{analysis.avgScore}</div>
                <div style={{ fontFamily: MONO, fontSize: 9.5, color: MUTE, letterSpacing: 1, marginTop: 4 }}>STACK<br/>EVIDENCE</div>
              </div>
              <div>
                <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 3 }}>Your {analysis.count}-item regimen</div>
                <div style={{ fontSize: 13, color: MUTE, lineHeight: 1.45 }}>
                  {analysis.flags.length === 0
                    ? "No conflicts detected. Your stack leans on well-supported ingredients."
                    : `${analysis.flags.length} thing${analysis.flags.length > 1 ? "s" : ""} worth reviewing below.`}
                </div>
              </div>
            </div>

            {/* ===== ANALYSIS FLAGS (the tool) ===== */}
            {analysis.flags.length > 0 && (
              <div className="rise" style={{ marginBottom: 14, display: "flex", flexDirection: "column", gap: 8 }}>
                {analysis.flags.map((f, i) => (
                  <div key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start", background: `${f.sev === "high" ? CORAL : AMBER}0E`, border: `1px solid ${f.sev === "high" ? CORAL : AMBER}33`, borderRadius: 10, padding: "11px 14px" }}>
                    <AlertTriangle size={15} color={f.sev === "high" ? CORAL : AMBER} style={{ flexShrink: 0, marginTop: 1 }} />
                    <span style={{ fontSize: 13, lineHeight: 1.45 }}>{f.text}</span>
                  </div>
                ))}
              </div>
            )}

            {/* ===== THE STACK ===== */}
            <SectionHead icon={<Link2 size={15} />} title="My stack" action={
              <button className="btn" onClick={() => setAdding((a) => !a)} style={{ display: "flex", alignItems: "center", gap: 5, background: adding ? PANEL2 : TEAL, color: adding ? MUTE : INK, border: `1px solid ${adding ? LINE : TEAL}`, fontWeight: 700, fontSize: 12.5, padding: "6px 12px", borderRadius: 8, cursor: "pointer" }}>
                {adding ? <><X size={13} /> Close</> : <><Plus size={14} /> Add</>}
              </button>
            } />

            {adding && (
              <AddItem onAdd={(item) => { setStack((s) => [...s, { ...item, id: Date.now() }]); setAdding(false); }} existing={stack.map((s) => s.name)} />
            )}

            <div style={{ display: "flex", flexDirection: "column", gap: 9, marginBottom: 22 }}>
              {stack.map((item) => {
                const lib = LIB.find((l) => l.name === item.name);
                return (
                  <div key={item.id} className="card" style={{ display: "flex", alignItems: "center", gap: 12, background: PANEL, border: `1px solid ${LINE}`, borderRadius: 11, padding: "13px 15px" }}>
                    <div style={{ width: 8, height: 8, borderRadius: 8, background: rgTierColor(lib?.tier || "Weak"), flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 14.5, fontWeight: 600 }}>{item.name}</div>
                      <div style={{ display: "flex", gap: 12, marginTop: 2, fontFamily: MONO, fontSize: 11, color: MUTE, flexWrap: "wrap" }}>
                        <span>{item.dose}</span>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}><Clock size={10} /> {item.timing}</span>
                        <span>since {item.start}</span>
                      </div>
                    </div>
                    {lib && <span style={{ fontFamily: MONO, fontSize: 10, color: rgTierColor(lib.tier), flexShrink: 0 }}>{lib.tier}</span>}
                    <button onClick={() => setStack((s) => s.filter((x) => x.id !== item.id))} style={{ background: "transparent", border: "none", cursor: "pointer", color: MUTE, padding: 4 }}><Trash2 size={15} /></button>
                  </div>
                );
              })}
            </div>

            {/* ===== PASSIVE METRICS + CORRELATION (the retention magic) ===== */}
            <SectionHead icon={<TrendingUp size={15} />} title="What your body shows" sub="Auto-synced from your tracker — no logging" />
            <div className="metricrow" style={{ display: "flex", gap: 8, marginBottom: 12 }}>
              {Object.entries(metricMeta).map(([k, m]) => {
                const Ic = m.icon;
                return (
                  <button key={k} className="btn" onClick={() => setMetric(k)}
                    style={{ flex: 1, minWidth: 90, background: metric === k ? PANEL : PANEL2, border: `1px solid ${metric === k ? m.color : LINE}`, borderRadius: 10, padding: "10px 8px", cursor: "pointer", textAlign: "center" }}>
                    <Ic size={16} color={m.color} style={{ marginBottom: 3 }} />
                    <div style={{ fontSize: 12, fontWeight: 600 }}>{m.label}</div>
                  </button>
                );
              })}
            </div>

            <div style={{ background: PANEL, border: `1px solid ${LINE}`, borderRadius: 12, padding: "18px 18px 12px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8, flexWrap: "wrap", gap: 8 }}>
                <div>
                  <div style={{ fontSize: 15, fontWeight: 700 }}>{mm.label} <span style={{ fontFamily: MONO, fontSize: 11, color: MUTE }}>· last 28 days</span></div>
                  <div style={{ fontSize: 12.5, color: MUTE, marginTop: 2 }}>Dashed line = you added Magnesium (day {CHANGE_DAY})</div>
                </div>
                {mm.good !== "flat" && (
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontFamily: MONO, fontSize: 18, fontWeight: 700, color: (mm.good === "up" ? delta > 0 : delta < 0) ? TEAL : MUTE }}>
                      {delta > 0 ? "+" : ""}{delta.toFixed(1)} {mm.unit}
                    </div>
                    <div style={{ fontFamily: MONO, fontSize: 10, color: MUTE }}>vs. before</div>
                  </div>
                )}
              </div>
              <div style={{ height: 190 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ left: -20, right: 8, top: 6 }}>
                    <defs>
                      <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={mm.color} stopOpacity={0.35} />
                        <stop offset="100%" stopColor={mm.color} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke={LINE} vertical={false} />
                    <XAxis dataKey="day" tick={{ fill: MUTE, fontFamily: MONO, fontSize: 9 }} axisLine={{ stroke: LINE }} tickLine={false} />
                    <YAxis tick={{ fill: MUTE, fontFamily: MONO, fontSize: 9 }} axisLine={false} tickLine={false} domain={["dataMin - 2", "dataMax + 2"]} />
                    <Tooltip contentStyle={{ background: PANEL2, border: `1px solid ${LINE}`, borderRadius: 8, fontFamily: MONO, fontSize: 12, color: TEXT }} />
                    <ReferenceLine x={CHANGE_DAY} stroke={TEAL} strokeDasharray="4 4" />
                    <Area type="monotone" dataKey="v" stroke={mm.color} strokeWidth={2.5} fill="url(#g)" dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              {mm.good !== "flat" && (mm.good === "up" ? delta > 0 : delta < 0) && (
                <div style={{ display: "flex", gap: 9, alignItems: "flex-start", background: `${TEAL}0C`, border: `1px solid ${TEAL}30`, borderRadius: 9, padding: "10px 13px", marginTop: 6 }}>
                  <Sparkles size={14} color={TEAL} style={{ flexShrink: 0, marginTop: 1 }} />
                  <span style={{ fontSize: 12.5, lineHeight: 1.45 }}>
                    Your {mm.label.toLowerCase()} improved ~{Math.abs(pct)}% after adding Magnesium. <span style={{ color: MUTE }}>This is an association, not proof — but it's your own n-of-1 signal worth watching.</span>
                  </span>
                </div>
              )}
            </div>

            {/* ===== WEEKLY CHECK-IN (only what sensors can't read) ===== */}
            <div style={{ marginTop: 22 }}>
              <SectionHead icon={<Brain size={15} />} title="Weekly check-in" sub="The few things your wearable can't measure" />
              {!checkinDone ? (
                <div style={{ background: PANEL, border: `1px solid ${LINE}`, borderRadius: 12, padding: "18px 20px" }}>
                  {[
                    { k: "mood", label: "Mood", icon: Heart },
                    { k: "focus", label: "Focus", icon: Zap },
                    { k: "stress", label: "Stress", icon: Brain },
                  ].map((row) => {
                    const Ic = row.icon;
                    return (
                      <div key={row.k} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                        <Ic size={16} color={MUTE} style={{ flexShrink: 0 }} />
                        <span style={{ fontSize: 14, width: 54, flexShrink: 0 }}>{row.label}</span>
                        <div style={{ display: "flex", gap: 6, flex: 1 }}>
                          {[1, 2, 3, 4, 5].map((n) => (
                            <button key={n} onClick={() => setCheckin((c) => ({ ...c, [row.k]: n }))}
                              style={{ flex: 1, height: 32, borderRadius: 7, cursor: "pointer", border: `1px solid ${checkin[row.k] === n ? TEAL : LINE}`, background: checkin[row.k] === n ? `${TEAL}22` : PANEL2, color: checkin[row.k] === n ? TEAL : MUTE, fontFamily: MONO, fontSize: 13, fontWeight: 600 }}>
                              {n}
                            </button>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                  <button className="btn" onClick={() => setCheckinDone(true)} style={{ width: "100%", marginTop: 4, background: TEAL, color: INK, border: "none", fontWeight: 700, fontSize: 14, padding: "11px", borderRadius: 9, cursor: "pointer" }}>
                    Save this week — 3 taps, done
                  </button>
                  <div style={{ textAlign: "center", fontFamily: MONO, fontSize: 10.5, color: MUTE, marginTop: 10 }}>That's all we ask you to type. Everything else syncs itself.</div>
                </div>
              ) : (
                <div style={{ background: PANEL, border: `1px solid ${TEAL}33`, borderRadius: 12, padding: "20px", textAlign: "center" }}>
                  <Check size={22} color={TEAL} style={{ marginBottom: 6 }} />
                  <div style={{ fontSize: 14.5, fontWeight: 600 }}>Logged for this week.</div>
                  <div style={{ fontSize: 12.5, color: MUTE, marginTop: 4 }}>We'll nudge you next week — and tell you what your data reveals over time.</div>
                </div>
              )}
            </div>

            {/* Data-value footer note */}
            <div style={{ marginTop: 24, fontFamily: MONO, fontSize: 10.5, color: MUTE, textAlign: "center", lineHeight: 1.6, borderTop: `1px solid ${LINE}`, paddingTop: 16 }}>
              Prototype · Simulated tracker data · Not medical advice<br/>
              Structured intervention → outcome data (with consent) is the foundation of real-world evidence.
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function SectionHead({ icon, title, sub, action }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: TEAL, display: "flex" }}>{icon}</span>
          <span style={{ fontSize: 16, fontWeight: 700, letterSpacing: -0.3 }}>{title}</span>
        </div>
        {sub && <div style={{ color: MUTE, fontSize: 12.5, marginTop: 2, marginLeft: 24 }}>{sub}</div>}
      </div>
      {action}
    </div>
  );
}

function AddItem({ onAdd, existing }) {
  const [name, setName] = useState("");
  const [dose, setDose] = useState("");
  const [timing, setTiming] = useState("Morning");
  const options = LIB.filter((l) => !existing.includes(l.name));
  return (
    <div className="rise" style={{ background: PANEL2, border: `1px solid ${TEAL_DIM}`, borderRadius: 11, padding: "15px 16px", marginBottom: 12 }}>
      <div style={{ fontFamily: MONO, fontSize: 10.5, color: MUTE, letterSpacing: 1, marginBottom: 8 }}>ADD TO STACK</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
        {options.slice(0, 8).map((o) => (
          <button key={o.name} onClick={() => setName(o.name)}
            style={{ background: name === o.name ? `${TEAL}22` : PANEL, border: `1px solid ${name === o.name ? TEAL : LINE}`, color: name === o.name ? TEAL : TEXT, fontSize: 12, padding: "6px 10px", borderRadius: 7, cursor: "pointer" }}>
            {o.name}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input value={dose} onChange={(e) => setDose(e.target.value)} placeholder="Dose (e.g. 5 g)"
          style={{ flex: 1, minWidth: 120, background: PANEL, border: `1px solid ${LINE}`, borderRadius: 8, color: TEXT, fontSize: 13, padding: "9px 12px", outline: "none", fontFamily: DISPLAY }} />
        <select value={timing} onChange={(e) => setTiming(e.target.value)}
          style={{ background: PANEL, border: `1px solid ${LINE}`, borderRadius: 8, color: TEXT, fontSize: 13, padding: "9px 12px", outline: "none", fontFamily: DISPLAY }}>
          {TIMING.map((t) => <option key={t}>{t}</option>)}
        </select>
      </div>
      <button className="btn" disabled={!name} onClick={() => onAdd({ name, dose: dose || "—", timing, start: "today" })}
        style={{ width: "100%", marginTop: 10, background: name ? TEAL : PANEL, color: name ? INK : MUTE, border: `1px solid ${name ? TEAL : LINE}`, fontWeight: 700, fontSize: 13.5, padding: "10px", borderRadius: 8, cursor: name ? "pointer" : "not-allowed" }}>
        Add {name || "an item"}
      </button>
    </div>
  );
}


// ============================================================
//  CLARITY — unified app shell with tab navigation
//  Research tab = evidence catalog + profiles
//  My Regimen tab = personal stack + passive tracking loop
// ============================================================
export default function Clarity() {
  const [tab, setTab] = useState("research");
  return (
    <div style={{ minHeight: "100vh", background: INK }}>
      <div style={{ paddingBottom: 64 }}>
        {tab === "research" ? <ResearchTab /> : <RegimenTab />}
      </div>
      {/* Bottom tab bar */}
      <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, display: "flex",
        background: INK + "F2", backdropFilter: "blur(10px)", borderTop: `1px solid ${LINE}`, zIndex: 50 }}>
        {[
          { k: "research", label: "Research", icon: BookOpen },
        ].map((t) => {
          const Ic = t.icon;
          const on = tab === t.k;
          return (
            <button key={t.k} onClick={() => setTab(t.k)}
              style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 3,
                background: "transparent", border: "none", cursor: "pointer", padding: "10px 0 12px",
                color: on ? TEAL : MUTE }}>
              <Ic size={20} color={on ? TEAL : MUTE} />
              <span style={{ fontFamily: MONO, fontSize: 10.5, fontWeight: on ? 700 : 500 }}>{t.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
