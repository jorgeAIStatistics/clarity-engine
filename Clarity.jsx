import React, { useState, useEffect, useRef, useMemo } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import {
  Search, TrendingUp, Shield, FlaskConical, Activity, Sparkles, ArrowLeft,
  Zap, Heart, Brain, Dumbbell, AlertTriangle, Users, Link2, Beaker, CheckCircle2, CircleDashed,
  Plus, Check, X, Watch, Smartphone, Moon, Clock, Trash2, BookOpen, ClipboardList,
  MessageCircle, Send
} from "lucide-react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Cell, Tooltip,
  LineChart, Line, CartesianGrid, RadialBarChart, RadialBar, PolarAngleAxis,
  AreaChart, Area, ReferenceLine
} from "recharts";


// ---- Design tokens ----
const INK = "#0A0D14", PANEL = "#141A26", PANEL2 = "#0E1219", LINE = "#1B2434";
const TEAL = "#34E0BE", TEAL_DIM = "#1B7A6C", AMBER = "#F5B544", CORAL = "#F07D74", VIOLET = "#9A8CF5";
const TEXT = "#E8EEF7", MUTE = "#8B9AB6";
const MONO = "'JetBrains Mono','SF Mono',ui-monospace,monospace";
const DISPLAY = "'Space Grotesk','Inter',system-ui,sans-serif";


// ---- Motion system -------------------------------------------------------
// Deliberately restrained: motion clarifies hierarchy and interaction rather
// than decorating scientific content. Every component respects reduced-motion.
const MOTION_EASE = [0.22, 1, 0.36, 1];
const MOTION_SPRING = { type: "spring", stiffness: 320, damping: 28, mass: 0.78 };
const PAGE_TRANSITION = { duration: 0.34, ease: MOTION_EASE };

// Route/view changes should always start at the top. We do the jump immediately
// and once again on the next frame so layout/AnimatePresence swaps cannot preserve
// an old scroll offset.
function jumpToPageTop() {
  if (typeof window === "undefined") return;
  const go = () => {
    try { window.scrollTo({ top: 0, left: 0, behavior: "auto" }); } catch { window.scrollTo(0, 0); }
    const scroller = document.scrollingElement || document.documentElement;
    if (scroller) scroller.scrollTop = 0;
    if (document.body) document.body.scrollTop = 0;
  };
  go();
  requestAnimationFrame(go);
}

function routeSlug(name) {
  return String(name || "").toLowerCase().trim()
    .normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function compoundRoute(name) { return `/compound/${routeSlug(name)}`; }

function parseBrowserRoute() {
  if (typeof window === "undefined") return { tab:"home" };
  let path = window.location.pathname || "/";
  try { path = decodeURIComponent(path); } catch {}
  path = path.replace(/\/+$/, "") || "/";
  if (path === "/research") return { tab:"research", request:{ clear:true } };
  if (path === "/methodology") return { tab:"research", request:{ methodology:true } };
  if (path === "/learn" || path === "/learn/basics") return { tab:"learn", learnSection:"basics" };
  if (path === "/learn/evidence") return { tab:"learn", learnSection:"evidence" };
  if (path === "/privacy") return { tab:"privacy" };
  if (path === "/terms") return { tab:"terms" };
  const m = path.match(/^\/compound\/([^/]+)$/);
  if (m) {
    const slug = m[1].toLowerCase();
    const entry = (typeof CATALOG !== "undefined") ? CATALOG.find((c)=>routeSlug(c[0])===slug) : null;
    return { tab:"research", request:{ topic:entry?.[0] || slug.replace(/-/g," "), category:entry?.[1] || "supplement" } };
  }
  return { tab:"home" };
}

function writeBrowserRoute(path, replace = false) {
  if (typeof window === "undefined") return;
  if (window.location.pathname === path) return;
  try { window.history[replace ? "replaceState" : "pushState"]({}, "", path); } catch {}
}

function Reveal({ children, delay = 0, y = 18, amount = 0.16, style, className }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      className={className}
      style={style}
      initial={reduceMotion ? false : { opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount }}
      transition={reduceMotion ? { duration: 0 } : { duration: 0.56, delay, ease: MOTION_EASE }}
    >
      {children}
    </motion.div>
  );
}

function PageEnter({ children, active = true, style }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      style={style}
      initial={reduceMotion ? false : { opacity: 0, y: 10 }}
      animate={active ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
      transition={reduceMotion ? { duration: 0 } : PAGE_TRANSITION}
    >
      {children}
    </motion.div>
  );
}

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
const API_BASE = (import.meta.env.VITE_API_BASE_URL || "https://clarity-engine-api.onrender.com").replace(/\/$/, "");

// ===== Language (EN / ES) =====
// UI chrome strings live here; compound PROSE is served from `*_es` fields on
// the profile (translated once by translate.py). Language persists per-session.
const LangContext = React.createContext(["en", () => {}]);
const STRINGS = {
  en: {
    tagline: "Peptides, Told Straight",
    eyebrow: "PEPTIDE EVIDENCE · PUBMED + EUROPE PMC · MECHANISMS & DATA",
    hero_1: "The peptide resource that gives you the ", hero_evidence: "science", hero_2: ", not the sales pitch.",
    search_ph: "Creatine, ashwagandha, BPC-157…",
    research: "Research", categories: "CATEGORIES", all_compounds: "All compounds",
    evidence_all: "Evidence: all", topics: "topics", topic: "topic",
    back: "Back", overall_tier: "STRONGEST HUMAN TIER",
    studies_analyzed: "unique studies graded", outcomes_graded: "major outcomes graded", run_in_people: "unique human studies",
    tier_note: "Tier is the headline; the score is the strength behind it.",
    good_for: "OUTCOMES — RANKED BY EVIDENCE CERTAINTY",
    effects_humans: "Effects on humans",
    what_studies_show: "WHAT THE STUDIES SHOW", why_grade: "WHY THIS GRADE",
    ask_title: "Ask about the evidence", ask_ph: "Ask anything about ",
    not_found: "That doesn't look like a searchable compound.",
    warming: "Warming up the research engine — first load can take a moment…",
    tiers: { Strong: "Strong", Moderate: "Moderate", Emerging: "Emerging", Preliminary: "Preliminary", Unknown: "Unknown" },
  },
  es: {
    tagline: "Péptidos, Sin Rodeos",
    eyebrow: "EVIDENCIA DE PÉPTIDOS · PUBMED + EUROPE PMC · MECANISMOS Y DATOS",
    hero_1: "El recurso de péptidos que te da la ", hero_evidence: "ciencia", hero_2: ", no el discurso de venta.",
    search_ph: "Creatina, ashwagandha, BPC-157…",
    research: "Investigar", categories: "CATEGORÍAS", all_compounds: "Todos los compuestos",
    evidence_all: "Evidencia: todas", topics: "temas", topic: "tema",
    back: "Volver", overall_tier: "NIVEL HUMANO MÁS FUERTE",
    studies_analyzed: "estudios únicos calificados", outcomes_graded: "resultados principales calificados", run_in_people: "estudios humanos únicos",
    tier_note: "El nivel es el titular; la puntuación es la fuerza detrás de él.",
    good_for: "RESULTADOS — ORDENADOS POR CERTEZA DE EVIDENCIA",
    effects_humans: "Efectos en humanos",
    what_studies_show: "LO QUE MUESTRAN LOS ESTUDIOS", why_grade: "POR QUÉ ESTE NIVEL",
    ask_title: "Pregunta sobre la evidencia", ask_ph: "Pregunta lo que sea sobre ",
    not_found: "Eso no parece un compuesto que se pueda buscar.",
    warming: "Encendiendo el motor de investigación — la primera carga puede tardar…",
    tiers: { Strong: "Fuerte", Moderate: "Moderada", Emerging: "Emergente", Preliminary: "Preliminar", Unknown: "Desconocida" },
  },
};
// Hook: returns the string table for the active language.
function useT() {
  const [lang] = React.useContext(LangContext);
  return STRINGS[lang] || STRINGS.en;
}
// Pick English or Spanish prose from a profile object based on active language.
function pickLang(obj, esObj, lang) {
  return (lang === "es" && esObj) ? esObj : obj;
}
function tierLabel(tier, lang = "en") {
  const table = STRINGS[lang] || STRINGS.en;
  return (table.tiers && table.tiers[tier]) || tier;
}
function categoryLabel(key, lang = "en") {
  const es = lang === "es";
  const labels = es ? {
    supplement: "Suplementos", peptide: "Péptidos", nootropic: "Nootrópicos", vitamin: "Vitaminas",
    mineral: "Minerales", herb: "Hierbas y adaptógenos", amino: "Aminoácidos", longevity: "Longevidad",
    hormonal: "Hormonal", fat: "Ácidos grasos", gut: "Intestino y probióticos", goal: "Objetivos y condiciones",
  } : Object.fromEntries(Object.entries(CATS).map(([k,v]) => [k, v.label]));
  return labels[key] || (CATS[key] && CATS[key].label) || key;
}
const PEPTIDE_FAMILY_ES = {
  healing: { label: "Curación y recuperación", blurb: "Explorados para reparación de tejidos, tendones e intestino; por ahora, gran parte de la evidencia proviene de animales y células." },
  gh: { label: "Secretagogos de hormona de crecimiento", blurb: "Estimulan la liberación de hormona de crecimiento del propio cuerpo. Varios tienen farmacología humana real, aunque la evidencia clínica varía." },
  metabolic: { label: "Metabólicos y GLP-1", blurb: "La clase GLP-1: los péptidos con mejor evidencia aquí, respaldados por grandes ensayos en humanos para peso y glucosa." },
  longevity: { label: "Longevidad y biorreguladores", blurb: "Biorreguladores tipo Khavinson y péptidos mitocondriales: mecanismos interesantes, pero evidencia humana limitada." },
  other: { label: "Otros e investigación", blurb: "Péptidos explorados para inmunidad, pigmentación, función sexual y más." },
};


const GUIDE_COPY = {
  en: {
    nav_home: "Home", nav_research: "Research", nav_learn: "Learn",
    top_tagline: "The Data, Told Straight",
    home_eyebrow: "CLARITY · EVIDENCE, EXPLAINED",
    home_title_1: "Understand the evidence ", home_title_2: "before the hype.",
    home_sub: "Peptides, supplements, and emerging compounds explained through the research behind them — from mechanism and animal models to human trials.",
    search_label: "SEARCH A COMPOUND", search_placeholder: "BPC-157, creatine, semaglutide, magnesium…", search_button: "Research",
    new_here: "Not sure where to begin?", new_here_sub: "Choose the path that matches what you want to understand. You can always jump straight into the full evidence catalog.",
    route_basics: "I'm new here", route_basics_sub: "Learn what peptides and supplements are, and what an evidence grade actually means.", route_basics_cta: "Start the 3-minute guide",
    route_compound: "I'm researching a compound", route_compound_sub: "Go straight to a profile with outcomes, evidence layers, studies, and uncertainty.", route_compound_cta: "Search above",
    route_goal: "I have a goal", route_goal_sub: "Explore example research topics by recovery, sleep, cognition, metabolic health, longevity, and skin.", route_goal_cta: "Explore areas",
    route_evidence: "I want to understand the science", route_evidence_sub: "See how ideas move from mechanisms and animal work into human evidence — and why each stage matters.", route_evidence_cta: "How evidence works",
    browse_all: "Browse the full research catalog",
    goals_eyebrow: "EXPLORE BY AREA", goals_title: "Start with the question you care about.", goals_sub: "These are example research topics, not recommendations or rankings. Open a compound to see what its evidence actually supports.", goal_paths: "research paths", goal_more: "more", goal_less: "show less", goal_open: "open research",
    evidence_eyebrow: "THE CLARITY IDEA", evidence_title: "Different evidence answers different questions.",
    evidence_sub: "A mechanism can be plausible, an animal result can be important, and a human claim can still remain uncertain. Clarity keeps those layers separate instead of blending them into one marketing story.",
    mech: "Mechanism", mech_sub: "Is there a biologically plausible pathway?",
    animal: "Animal & preclinical", animal_sub: "Does the effect appear in a living system, and what can we learn about biology, dosing, or toxicity?",
    human: "Human evidence", human_sub: "Does the effect actually translate to people under the conditions studied?",
    evidence_cta: "Learn how research moves from idea to evidence",
    compare_eyebrow: "SEE THE DIFFERENCE", compare_title: "The same category can hide very different evidence bases.",
    compare_sub: "Open two peptide profiles and compare where the evidence actually lives — human trials versus predominantly preclinical research.",
    compare_human: "Human-research example", compare_preclinical: "Preclinical-dominant example",
    open_profile: "Open profile",
    basics_eyebrow: "START HERE", basics_title: "A short guide to reading Clarity.", basics_sub: "You do not need a research background. The goal is to understand what each kind of evidence can tell you — and what it cannot.",
    peptides_title: "What is a peptide?", peptides_body: "Peptides are short chains of amino acids. Some occur naturally in the body, some are medicines, and others are experimental research compounds. “Peptide” describes what something is chemically — not whether it works, whether it is safe, or whether it has been proven in people.",
    supplements_title: "What is a supplement?", supplements_body: "Supplements are a broader category that can include vitamins, minerals, amino acids, herbs, proteins, fatty acids, and other compounds. Clarity does not assume a supplement works because it is popular or ‘natural’; it asks what the evidence supports for each outcome.",
    research_eyebrow: "HOW RESEARCH BUILDS", research_title: "From a biological idea to evidence in people.", research_sub: "Research is not one straight conveyor belt, but these stages show the kinds of questions scientists often answer as evidence matures.",
    step_mechanism: "Mechanism", step_mechanism_sub: "What pathway or target could explain an effect?",
    step_cells: "Cells & tissue", step_cells_sub: "Can the proposed effect occur in a controlled biological system?",
    step_animals: "Animal models", step_animals_sub: "What happens in a whole living organism? What mechanisms, dose relationships, or safety signals appear?",
    step_humans: "Human studies", step_humans_sub: "Does the signal translate to people, in a defined population and setting?",
    step_rct: "Controlled trials", step_rct_sub: "Does the intervention outperform placebo or a comparison under controlled conditions?",
    step_synthesis: "Evidence synthesis", step_synthesis_sub: "When multiple studies exist, what does the accumulated body of evidence show?",
    animal_value_title: "Animal evidence is valuable.", animal_value_body: "Animal models can reveal mechanisms, tissue effects, pharmacology, toxicity signals, and whether an idea is promising enough to study further. Much of biomedical research depends on this preclinical work.",
    animal_limit_title: "But it answers a different question.", animal_limit_body: "An effect in an animal does not establish that the same intervention will be effective or safe in humans. Species biology, disease models, metabolism, dosing, and study conditions can differ.",
    human_value_title: "Why human data matters", human_value_body: "If the claim is about what a compound does for people, evidence in people is the direct test. Human studies let us evaluate translation, clinically meaningful outcomes, adverse effects, and how results vary across populations.",
    clarity_rule: "Clarity's rule", clarity_rule_body: "Strong preclinical evidence can make a compound scientifically interesting. It cannot, by itself, turn a human claim into a proven one. That is why the human layer gates the headline evidence tier while the lower layers remain visible and valuable.",
    tiers_eyebrow: "READING THE TIERS", tiers_title: "The grade is confidence in the evidence — not the power of the compound.", tiers_sub: "A Preliminary compound may still be biologically interesting. The label means the evidence does not yet justify strong confidence in a human effect.",
    score_title: "And the number is not a probability.", score_body: "An evidence-strength score such as 36/100 does not mean a 36% chance that the compound works. It describes the strength and depth of the evidence base under Clarity's scoring rules.",
    ready_title: "Ready to read a real profile?", ready_sub: "Pick a compound and use the layers, outcome grades, study table, and critical appraisal together — no single chart tells the whole story.", ready_cta: "Go to Research",
    beginner_link: "New here? Learn how to read the evidence",
    methodology_link: "Technical grading methodology",
    goal_recovery: "Recovery & performance", goal_recovery_sub: "Muscle, training, tissue repair", goal_sleep: "Sleep & stress", goal_sleep_sub: "Sleep quality, stress, calm", goal_cognitive: "Cognition & focus", goal_cognitive_sub: "Attention, memory, fatigue", goal_metabolic: "Metabolic health", goal_metabolic_sub: "Weight, appetite, glucose", goal_longevity: "Longevity", goal_longevity_sub: "Aging biology and resilience", goal_skin: "Skin & tissue", goal_skin_sub: "Skin, collagen, wound research",
  },
  es: {
    nav_home: "Inicio", nav_research: "Investigación", nav_learn: "Aprender",
    top_tagline: "Los datos, sin rodeos",
    home_eyebrow: "CLARITY · EVIDENCIA, EXPLICADA",
    home_title_1: "Entiende la evidencia ", home_title_2: "antes del ruido.",
    home_sub: "Péptidos, suplementos y compuestos emergentes explicados a través de la investigación que los respalda: desde mecanismos y modelos animales hasta ensayos en humanos.",
    search_label: "BUSCA UN COMPUESTO", search_placeholder: "BPC-157, creatina, semaglutida, magnesio…", search_button: "Investigar",
    new_here: "¿No sabes por dónde empezar?", new_here_sub: "Elige la ruta que mejor se ajuste a lo que quieres entender. Siempre puedes saltar directamente al catálogo completo de evidencia.",
    route_basics: "Soy nuevo aquí", route_basics_sub: "Aprende qué son los péptidos y suplementos, y qué significa realmente una calificación de evidencia.", route_basics_cta: "Empezar la guía de 3 minutos",
    route_compound: "Estoy investigando un compuesto", route_compound_sub: "Ve directo a un perfil con resultados, capas de evidencia, estudios e incertidumbre.", route_compound_cta: "Busca arriba",
    route_goal: "Tengo un objetivo", route_goal_sub: "Explora temas de investigación por recuperación, sueño, cognición, salud metabólica, longevidad y piel.", route_goal_cta: "Explorar áreas",
    route_evidence: "Quiero entender la ciencia", route_evidence_sub: "Mira cómo una idea pasa de mecanismos y estudios animales a evidencia humana, y por qué cada etapa importa.", route_evidence_cta: "Cómo funciona la evidencia",
    browse_all: "Ver todo el catálogo de investigación",
    goals_eyebrow: "EXPLORA POR ÁREA", goals_title: "Empieza por la pregunta que te importa.", goals_sub: "Son ejemplos de temas de investigación, no recomendaciones ni rankings. Abre un compuesto para ver qué respalda realmente su evidencia.", goal_paths: "rutas de investigación", goal_more: "más", goal_less: "mostrar menos", goal_open: "abrir investigación",
    evidence_eyebrow: "LA IDEA DE CLARITY", evidence_title: "Distintos tipos de evidencia responden preguntas distintas.",
    evidence_sub: "Un mecanismo puede ser plausible, un resultado animal puede ser importante y aun así una afirmación en humanos puede seguir siendo incierta. Clarity mantiene esas capas separadas en lugar de mezclarlas en una sola historia de marketing.",
    mech: "Mecanismo", mech_sub: "¿Existe una vía biológica plausible?",
    animal: "Animal y preclínica", animal_sub: "¿Aparece el efecto en un sistema vivo y qué podemos aprender sobre biología, dosis o toxicidad?",
    human: "Evidencia humana", human_sub: "¿El efecto realmente se traduce a personas bajo las condiciones estudiadas?",
    evidence_cta: "Aprender cómo una idea se convierte en evidencia",
    compare_eyebrow: "MIRA LA DIFERENCIA", compare_title: "Una misma categoría puede esconder bases de evidencia muy distintas.",
    compare_sub: "Abre dos perfiles de péptidos y compara dónde vive realmente la evidencia: ensayos en humanos frente a investigación predominantemente preclínica.",
    compare_human: "Ejemplo con investigación humana", compare_preclinical: "Ejemplo dominado por datos preclínicos",
    open_profile: "Abrir perfil",
    basics_eyebrow: "EMPIEZA AQUÍ", basics_title: "Una guía corta para leer Clarity.", basics_sub: "No necesitas formación en investigación. El objetivo es entender qué puede decirte cada tipo de evidencia y qué no puede demostrar.",
    peptides_title: "¿Qué es un péptido?", peptides_body: "Los péptidos son cadenas cortas de aminoácidos. Algunos aparecen naturalmente en el cuerpo, algunos son medicamentos y otros son compuestos experimentales de investigación. “Péptido” describe qué es algo químicamente; no dice si funciona, si es seguro ni si se ha demostrado en personas.",
    supplements_title: "¿Qué es un suplemento?", supplements_body: "Los suplementos son una categoría más amplia que puede incluir vitaminas, minerales, aminoácidos, hierbas, proteínas, ácidos grasos y otros compuestos. Clarity no supone que un suplemento funciona porque sea popular o ‘natural’; pregunta qué respalda la evidencia para cada resultado.",
    research_eyebrow: "CÓMO SE CONSTRUYE LA EVIDENCIA", research_title: "De una idea biológica a evidencia en personas.", research_sub: "La investigación no es una cinta transportadora perfectamente lineal, pero estas etapas muestran las preguntas que suelen responderse a medida que madura la evidencia.",
    step_mechanism: "Mecanismo", step_mechanism_sub: "¿Qué vía o diana podría explicar un efecto?",
    step_cells: "Células y tejido", step_cells_sub: "¿Puede ocurrir el efecto propuesto en un sistema biológico controlado?",
    step_animals: "Modelos animales", step_animals_sub: "¿Qué ocurre en un organismo vivo completo? ¿Qué mecanismos, relaciones de dosis o señales de seguridad aparecen?",
    step_humans: "Estudios en humanos", step_humans_sub: "¿La señal se traduce a personas, en una población y contexto definidos?",
    step_rct: "Ensayos controlados", step_rct_sub: "¿La intervención supera al placebo o a una comparación bajo condiciones controladas?",
    step_synthesis: "Síntesis de evidencia", step_synthesis_sub: "Cuando existen varios estudios, ¿qué muestra el conjunto acumulado de evidencia?",
    animal_value_title: "La evidencia animal es valiosa.", animal_value_body: "Los modelos animales pueden revelar mecanismos, efectos tisulares, farmacología, señales de toxicidad y si una idea merece estudiarse más. Gran parte de la investigación biomédica depende de este trabajo preclínico.",
    animal_limit_title: "Pero responde una pregunta diferente.", animal_limit_body: "Un efecto en un animal no establece que la misma intervención será eficaz o segura en humanos. La biología entre especies, los modelos de enfermedad, el metabolismo, la dosis y las condiciones del estudio pueden diferir.",
    human_value_title: "Por qué importan los datos humanos", human_value_body: "Si la afirmación es sobre lo que un compuesto hace en personas, la evidencia en personas es la prueba directa. Los estudios humanos permiten evaluar traducción, resultados clínicamente relevantes, efectos adversos y variación entre poblaciones.",
    clarity_rule: "La regla de Clarity", clarity_rule_body: "Una evidencia preclínica fuerte puede hacer que un compuesto sea científicamente interesante. Por sí sola no puede convertir una afirmación humana en una demostrada. Por eso la capa humana limita el nivel principal, mientras que las capas inferiores siguen visibles y son valiosas.",
    tiers_eyebrow: "CÓMO LEER LOS NIVELES", tiers_title: "La calificación mide confianza en la evidencia, no la potencia del compuesto.", tiers_sub: "Un compuesto Preliminar puede seguir siendo biológicamente interesante. La etiqueta significa que la evidencia aún no justifica una confianza fuerte en un efecto humano.",
    score_title: "Y el número no es una probabilidad.", score_body: "Una puntuación de fuerza de evidencia como 36/100 no significa una probabilidad de 36% de que el compuesto funcione. Describe la fuerza y profundidad de la base de evidencia según las reglas de Clarity.",
    ready_title: "¿Listo para leer un perfil real?", ready_sub: "Elige un compuesto y usa en conjunto las capas, las calificaciones por resultado, la tabla de estudios y la evaluación crítica; ningún gráfico cuenta toda la historia por sí solo.", ready_cta: "Ir a Investigación",
    beginner_link: "¿Nuevo aquí? Aprende a leer la evidencia",
    methodology_link: "Metodología técnica de calificación",
    goal_recovery: "Recuperación y rendimiento", goal_recovery_sub: "Músculo, entrenamiento, reparación tisular", goal_sleep: "Sueño y estrés", goal_sleep_sub: "Calidad del sueño, estrés, calma", goal_cognitive: "Cognición y enfoque", goal_cognitive_sub: "Atención, memoria, fatiga", goal_metabolic: "Salud metabólica", goal_metabolic_sub: "Peso, apetito, glucosa", goal_longevity: "Longevidad", goal_longevity_sub: "Biología del envejecimiento y resiliencia", goal_skin: "Piel y tejidos", goal_skin_sub: "Piel, colágeno, cicatrización",
  },
};

function guideCopy(lang) { return GUIDE_COPY[lang] || GUIDE_COPY.en; }

const CATALOG_META = {};
const TIER_COLORS = { Strong:"#34E0BE", Moderate:"#F5B544", Emerging:"#9A8CF5", Preliminary:"#F07D74", Unknown:"#5E6E8A" };

// Session cache (survives navigation within the session) + in-flight dedup so
// hovering then clicking doesn't double-fetch, and revisiting is instant.
const _profileCache = new Map();   // key -> { profile, source }
const _inflight = new Map();       // key -> Promise

// Real engine grades, keyed by lowercase compound name. Populated from the
// current backend catalog/profile responses only. Deliberately NOT persisted to
// sessionStorage: after an engine deployment, a stale browser tab must not be
// able to resurrect an older scientific grade. In-memory caching still makes
// navigation within the open app instant.
const _tierCache = new Map();
function _recordTier(name, tier, human, meta = {}) {
  if (!name || !tier) return;
  const raw = String(name).toLowerCase().trim();
  const prev = _tierCache.get(raw) || {};
  const record = { ...prev, tier, human: human ?? prev.human ?? null, ...meta };
  _tierCache.set(raw, record);
  // Also store under the cleaned form so "Semaglutide (GLP-1)" and "semaglutide"
  // both resolve regardless of which the catalog vs. the DB slug uses.
  const cleaned = raw.replace(/\s*\([^)]*\)\s*/g, " ").split("/")[0].trim();
  if (cleaned && cleaned !== raw) {
    const prevClean = _tierCache.get(cleaned) || {};
    _tierCache.set(cleaned, { ...prevClean, ...record });
  }
}
function liveTier(name) {
  const raw = String(name).toLowerCase().trim();
  // Try exact, then a cleaned form (drop "(...)" and slash-suffix) so display
  // names like "Semaglutide (GLP-1)" match a stored slug of "semaglutide".
  const cleaned = raw.replace(/\s*\([^)]*\)\s*/g, " ").split("/")[0].trim();
  return _tierCache.get(raw) || (cleaned && cleaned !== raw ? _tierCache.get(cleaned) : null) || null;
}

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
    const j = await r.json().catch(() => ({}));
    if (r.status === 409 && j.code === "STALE_PROFILE") throw new Error("This evidence profile is being refreshed for the current engine. Please try it again after the catalog update finishes.");
    if (r.status === 404 && j.code === "NOT_IN_CATALOG") throw new Error("That compound is not in Clarity's audited catalog yet.");
    if (r.status === 503) throw new Error(j.hint || "Research generation is temporarily unavailable.");
    if (r.status === 429) throw new Error("One moment between searches, please.");
    if (r.status === 400) throw new Error("That doesn't look like a searchable compound.");
    if (!r.ok) throw new Error(j.error || `Research failed (${r.status}).`);
    const result = { profile: j.profile, source: j.source };
    _profileCache.set(key, result);
    // Record the REAL tier so the catalog stops showing hardcoded guesses.
    if (j.profile && j.profile.tier) {
      const humanN = Number.isFinite(j.profile.unique_human_study_count)
        ? j.profile.unique_human_study_count
        : (j.profile.claims || []).reduce((n, c) => n + ((c.layers && c.layers.n_human_studies) || 0), 0);
      const outcomeDependent = !!j.profile.outcome_dependent;
      _recordTier(topic, j.profile.tier, humanN, {
        displayTier: outcomeDependent ? "Outcome-dependent" : j.profile.tier,
        outcomeDependent,
        bestOutcome: j.profile.best_outcome || null,
        bestTier: j.profile.best_tier || j.profile.tier,
      });
    }
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

// Grounded Q&A. Posts to /api/ask, which answers ONLY from the compound's
// already-graded profile (never the model's general knowledge). Returns
// { answer, grounded }.
async function apiAsk(topic, category, question, history, language = "en") {
  const r = await fetch(`${API_BASE}/api/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, category, question, history: history || [], language }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok && !j.answer) {
    throw new Error(j.error || `Assistant failed (${r.status}).`);
  }
  return j;  // { answer, grounded, pmids, coverage, retrieved_studies, event_id, ... }
}

async function apiAskFeedback(eventId, helpful) {
  if (!eventId) return false;
  try {
    const r = await fetch(`${API_BASE}/api/ask/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_id: eventId, helpful: !!helpful }),
    });
    return r.ok;
  } catch {
    return false;
  }
}

// Load the whole catalog's real tiers in ONE call on page load, so every card
// shows its grade immediately instead of "Ungraded until clicked". Seeds the
// tier cache keyed by both name and slug (the catalog list uses display names).
async function apiFetchCatalog() {
  try {
    // Never let a browser session keep grades from an older engine release.
    _tierCache.clear();
    try { sessionStorage.removeItem("clarity_tiers"); } catch {}
    const r = await fetch(`${API_BASE}/api/catalog`);
    if (!r.ok) return 0;
    const j = await r.json();
    const rows = j.catalog || [];
    for (const row of rows) {
      if (row.stale) continue;
      const meta = {
        displayTier: row.display_tier || row.tier,
        outcomeDependent: !!row.outcome_dependent,
        bestOutcome: row.best_outcome || null,
        bestTier: row.best_tier || row.tier,
        outcomeTiers: row.outcome_tiers || [],
      };
      if (row.name && row.tier) _recordTier(row.name, row.tier, null, meta);
      if (row.slug && row.tier) _recordTier(row.slug, row.tier, null, meta);
    }
    return rows.length;
  } catch {
    return 0;
  }
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
    directionStatus: claim.direction_status || "not_assessed",
    effectExtractionStatus: claim.effect_extraction_status || "not_assessed",
    preprintsExcluded: claim.preprints_excluded || 0,
    summary: claim.summary || null, summary_es: claim.summary_es || null,
    headlineEffect: he ? { metric: he.metric, value: he.value, ciLow: he.ci_low, ciHigh: he.ci_high,
      nPooled: he.n_studies_pooled, comparator: he.comparator, direction: he.direction, estimated: !!he.ci_estimated } : null,
    pmids: claim.study_ids || [],
    studies: claim.studies || [],
    weighted: claim.weighted_score ? {
      score: claim.weighted_score.final_score,
      ciLow: claim.weighted_score.confidence_interval?.lower,
      ciHigh: claim.weighted_score.confidence_interval?.upper,
      confTier: claim.weighted_score.confidence_tier,
      direction: claim.weighted_score.direction,
    } : null,
  };
}
function engineProfileToView(p) {
  if (!p) return null;
  const est = p.effects_established || [], prom = p.effects_promising || [];
  let verdict;
  if (est.length && !prom.length) verdict = "Supported by human evidence across its main outcomes.";
  else if (prom.length && !est.length) verdict = "Promising in mechanism or animal studies, but not yet supported by convincing human evidence.";
  else if (est.length && prom.length) verdict = "Supported by human evidence for some outcomes; still early or uncertain for others.";
  else verdict = "Early or limited evidence — treat claims with caution.";
  const bestTier = p.best_tier || p.tier;
  return { name: p.name, cat: p.category, tier: p.tier, bestTier, outcomeDependent: !!p.outcome_dependent,
    displayTier: p.outcome_dependent ? "Outcome-dependent" : p.tier,
    bestOutcome: p.best_outcome || null, tierColor: TIER_COLORS[bestTier] || TIER_COLORS[p.tier] || TIER_COLORS.Unknown,
    overallScore: p.overall_score, studyCount: p.study_count,
    uniqueHumanStudyCount: p.unique_human_study_count, uniqueAnimalStudyCount: p.unique_animal_study_count,
    uniqueUnlabelledStudyCount: p.unique_unlabelled_study_count, outcomeStudyMemberships: p.outcome_study_memberships,
    engineVersion: p.engine_version || null, generatedAt: p.generated_at || null, sources: p.sources || [],
    tierBasis: p.overall_tier_basis || "best_human_supported_outcome", verdict, honestyNote: p.honesty_note || null,
    thinEvidence: p.thin_evidence || false, thinEvidenceNote: p.thin_evidence_note || null,
    established: est, promising: prom, emerging: p.effects_emerging || [],
    outcomes: (p.claims || []).map(engineClaimToOutcome), reviewedBy: p.reviewed_by || "auto", explanation: p.explanation || null, explanation_es: p.explanation_es || null, chemistry: p.chemistry || null, pharmacokinetics: p.pharmacokinetics || null, appraisal: p.appraisal || null, appraisal_es: p.appraisal_es || null,
    weighted: p.weighted_score ? { score: p.weighted_score.score, best: p.weighted_score.best_outcome_score, nScored: p.weighted_score.n_outcomes_scored } : null };
}
// ===== END DATA LAYER =====

// ---- Catalog entities (grades come from the live backend, never these hints) ----
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
  ["Semaglutide", "peptide", T.strong], ["Tirzepatide", "peptide", T.strong], ["Retatrutide", "peptide", T.emerging], ["Dihexa", "peptide", T.weak], ["AHK-Cu", "peptide", T.weak], ["Ipamorelin", "peptide", T.emerging],
  ["CJC-1295", "peptide", T.emerging], ["MOTS-c", "peptide", T.emerging], ["Melanotan II", "peptide", T.weak],
  ["Thymosin Alpha-1", "peptide", T.moderate], ["Sermorelin", "peptide", T.moderate], ["PT-141", "peptide", T.moderate],
  ["Epithalon", "peptide", T.weak], ["AOD-9604", "peptide", T.weak],
  // Additional peptides (graded, in DB)
  ["Tesamorelin", "peptide", T.moderate], ["KPV", "peptide", T.emerging], ["Semax", "peptide", T.emerging],
  ["Glutathione", "peptide", T.moderate], ["Selank", "peptide", T.emerging], ["IGF-1 LR3", "peptide", T.weak],
  ["5-Amino-1MQ", "peptide", T.weak], ["Cagrilintide", "peptide", T.emerging], ["DSIP", "peptide", T.emerging],
  ["SNAP-8", "peptide", T.weak], ["Cartalax", "peptide", T.weak], ["Kisspeptin", "peptide", T.emerging],
  ["LL-37", "peptide", T.emerging], ["ARA-290", "peptide", T.emerging], ["VIP", "peptide", T.emerging],
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

// Peptide families — how the peptide-curious actually search. A peptide is
// matched to a family by name; anything unmatched falls into "Other / research".
// This only ORGANIZES existing peptides — no data invented.
const PEPTIDE_FAMILIES = [
  { key: "healing", label: "Healing & Recovery",
    blurb: "Explored for tissue, tendon, and gut repair — mostly on the strength of animal and cell data so far.",
    members: ["bpc-157","bpc157","tb-500","tb500","ghk-cu","ghk","ahk-cu","kpv","ll-37","cartalax"] },
  { key: "gh", label: "Growth Hormone Secretagogues",
    blurb: "Prompt the body to release its own growth hormone. Several have real human pharmacology behind them.",
    members: ["ipamorelin","cjc-1295","cjc1295","sermorelin","tesamorelin","hexarelin","ghrp","igf-1 lr3","igf-1"] },
  { key: "metabolic", label: "Metabolic & GLP-1",
    blurb: "The GLP-1 class — the best-evidenced peptides here, with large human trials for weight and glucose.",
    members: ["semaglutide","semaglutide (glp-1)","tirzepatide","retatrutide","survodutide","cagrilintide","aod-9604"] },
  { key: "longevity", label: "Longevity & Bioregulators",
    blurb: "Khavinson-style bioregulators and mitochondrial peptides — intriguing mechanisms, thin human data.",
    members: ["epithalon","epitalon","pinealon","vesugen","crystagen","mots-c","5-amino-1mq","ss-31"] },
  { key: "other", label: "Other & Research",
    blurb: "Peptides explored for immunity, pigmentation, sexual function, and more.",
    members: ["thymosin alpha-1","pt-141","melanotan ii","melanotan-1","melanotan","kisspeptin","dihexa","ara-290",
              "semax","selank","glutathione","snap-8","vip","vasoactive intestinal peptide","dsip","delta sleep-inducing peptide",
              "oxytocin","selank","semax","snap-8","delta sleep-inducing peptide","cibinetide",
              "vasoactive intestinal peptide"] },
];
// Blends — multi-peptide combos sold as one product. We do NOT grade blends:
// no study tests the specific combination, so a grade would be meaningless. We
// cover them honestly — components, links to each component's REAL evidence, and
// why they're sold together — plus a buy link for those who want the combo.
// Fill in each blend's real components from the supplier (don't guess contents).
const BLENDS = [
  { name: "Wolverine", components: ["BPC-157", "TB-500"],
    pitch: "Sold together for tissue and tendon repair — the two most-hyped healing peptides in one vial." },
  // Composition has not been independently verified in the evidence dataset.
  // Keep the disclosed affiliate listing, but do not guess ingredients.
  { name: "GLOW", components: [],
    pitch: "Commercial peptide blend. Clarity does not grade the blend as a unit; verify the current supplier label for its exact composition.", unverified: true },
  { name: "KLOW", components: [],
    pitch: "Commercial peptide blend. Clarity does not grade the blend as a unit; verify the current supplier label for its exact composition.", unverified: true },
];

function peptideFamilyOf(name) {
  const k = (name || "").toLowerCase().trim();
  for (const fam of PEPTIDE_FAMILIES) {
    if (fam.members.some((m) => k === m || k.startsWith(m) || m.startsWith(k))) return fam.key;
  }
  return "other";
}

function ResearchTab({ langState, initialRequest, onHome, onLearn, onProfileOpen, onResearchRoot, onMethodologyOpen }) {
  const [query, setQuery] = useState("");
  const searchRef = useRef(null);
  useEffect(() => {
    const h = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); searchRef.current?.focus(); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  const [catFilter, setCatFilter] = useState("peptide");
  const [tierFilter, setTierFilter] = useState("all");
  const [active, setActive] = useState(null);
  const [notFound, setNotFound] = useState(null);
  const [loading, setLoading] = useState(false);
  const [phase, setPhase] = useState("");
  const [pending, setPending] = useState(null);
  const [view, setView] = useState(null);
  const [showMethod, setShowMethod] = useState(false);  // "How grading works" page
  const [error, setError] = useState(null);
  const [source, setSource] = useState(null);
  const [gradeVersion, setGradeVersion] = useState(0);  // bump to refresh catalog tiers
  const [warming, setWarming] = useState(true);         // catalog still loading
  const [showWakeMsg, setShowWakeMsg] = useState(false); // show "waking up" after a beat
  const [sidebarOpen, setSidebarOpen] = useState(false); // mobile drawer
  const launchHandled = useRef(null);
  const t = STRINGS[langState[0]] || STRINGS.en;
  const guide = guideCopy(langState[0]);

  // On first load, pull every compound's real tier in one call so cards show
  // their grade immediately instead of "Ungraded". If the backend was asleep
  // (free tier spins down), the first call can take ~50s — after 4s we show a
  // friendly "waking up" banner so the wait reads as intentional, not broken.
  useEffect(() => {
    let alive = true;
    const wakeTimer = setTimeout(() => { if (alive) setShowWakeMsg(true); }, 4000);
    apiFetchCatalog().then((n) => {
      if (!alive) return;
      clearTimeout(wakeTimer);
      setWarming(false);
      setShowWakeMsg(false);
      if (n > 0) setGradeVersion((v) => v + 1);
    }).catch(() => {
      if (!alive) return;
      clearTimeout(wakeTimer);
      setWarming(false);
      setShowWakeMsg(false);
    });
    return () => { alive = false; clearTimeout(wakeTimer); };
  }, []);

  const runResearch = async (topic, category = "supplement") => {
    setActive(null); setNotFound(null); setError(null); setView(null); setLoading(true);
    // Optimistic instant feedback: show a lightweight header from catalog data
    // right away, so the page responds instantly even while the profile loads.
    const ce = CATALOG.find((c) => c[0].toLowerCase() === String(topic).toLowerCase())
            || CATALOG.find((c) => c[0].toLowerCase().includes(String(topic).toLowerCase()));
    setPending(ce ? { name: ce[0], cat: ce[1], tier: null } : { name: topic, cat: category, tier: null });
    setPhase("Searching PubMed and grading the evidence… this can take up to a minute.");
    jumpToPageTop();
    // Clean the DISPLAY name into a searchable term: drop parenthetical labels
    // ("Semaglutide (GLP-1)" -> "Semaglutide") and slash-suffixes ("Protein / whey"
    // -> "Protein"). The parenthetical is a label for humans, not a PubMed term.
    const searchTopic = String(topic)
      .replace(/\s*\([^)]*\)\s*/g, " ")   // remove (…)
      .split("/")[0]                       // take the part before a slash
      .trim() || String(topic).trim();
    try {
      const { profile, source } = await apiFetchProfile(searchTopic, category);
      setView(engineProfileToView(profile)); setSource(source);
      onProfileOpen?.(profile?.name || topic, profile?.category || category);
      jumpToPageTop();
      setGradeVersion((v) => v + 1);   // refresh catalog tiles with the real grade
    } catch (e) {
      setError(e.message || "Something went wrong.");
    } finally {
      setLoading(false); setPending(null); setPhase("");
    }
  };
  useEffect(() => {
    if (!initialRequest || launchHandled.current === initialRequest.id) return;
    launchHandled.current = initialRequest.id;
    if (initialRequest.clear) {
      setView(null); setShowMethod(false); setError(null); setActive(null); setNotFound(null);
      jumpToPageTop();
    } else if (initialRequest.methodology) {
      setView(null); setShowMethod(true); setError(null); setActive(null);
      jumpToPageTop();
    } else if (initialRequest.topic) {
      setQuery(initialRequest.topic);
      runResearch(initialRequest.topic, initialRequest.category || "supplement");
    } else if (initialRequest.category) {
      setCatFilter(initialRequest.category);
      setView(null); setShowMethod(false); setError(null);
      jumpToPageTop();
    }
  }, [initialRequest]);

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
      if (tierFilter !== "all") {
        // Prefer the REAL engine grade; fall back to the catalog hint only while
        // a compound is still ungraded, so the filter stays usable on first load.
        const lv = liveTier(c[0]);
        // Never filter on the catalog's historical hint. Until the engine grade
        // arrives, this card is simply not eligible for a grade-specific filter.
        if (!lv || lv.tier !== tierFilter) return false;
      }
      if (q && !c[0].toLowerCase().includes(q)) return false;
      return true;
    }).sort((a, b) => (b[3] ? 1 : 0) - (a[3] ? 1 : 0));
  }, [query, catFilter, tierFilter, NON_GRADEABLE, gradeVersion]);

  const showProfile = view != null;
  const closeDeepView = () => {
    setShowMethod(false);
    setView(null);
    setActive(null);
    setError(null);
    onResearchRoot?.();
    jumpToPageTop();
  };
  const totalTopics = useMemo(
    () => CATALOG.filter((c) => c[1] !== "goal" && !NON_GRADEABLE.has(c[0].toLowerCase())).length,
    [NON_GRADEABLE]
  );

  return (
    <LangContext.Provider value={langState}>
    <div style={{ minHeight: "100%", background: INK, color: TEXT, fontFamily: DISPLAY }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');
        * { box-sizing: border-box; }
        .ev-btn:hover { filter:brightness(1.08); }
        .ev-chip:hover { background:${PANEL} !important; border-color:${TEAL_DIM} !important; }
        .ev-card { transition: transform .28s cubic-bezier(.22,1,.36,1), border-color .28s ease, box-shadow .28s ease, background .28s ease; }
        .ev-card:hover { transform: translateY(-4px); border-color:${TEAL_DIM} !important; box-shadow:0 16px 44px rgba(0,0,0,.22); }
        .cat-tile { transition: transform .28s cubic-bezier(.22,1,.36,1), border-color .28s ease, background .28s ease, box-shadow .28s ease; cursor:pointer; }
        .cat-tile:hover { transform: translateY(-4px); border-color:${TEAL_DIM} !important; background:${PANEL} !important; box-shadow:0 14px 40px rgba(0,0,0,.20); }
        @keyframes pulse { 0%,100%{opacity:.35} 50%{opacity:1} }
        @keyframes rise { from{opacity:0; transform:translateY(8px)} to{opacity:1; transform:translateY(0)} }
        @keyframes riseIn { from{opacity:0; transform:translateY(14px)} to{opacity:1; transform:translateY(0)} }
        .rise { animation: rise .5s cubic-bezier(.22,1,.36,1) both; }
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
        @keyframes growY { from{transform:scaleY(0)} to{transform:scaleY(1)} }
        @keyframes ciDraw { from{transform:scaleX(0)} to{transform:scaleX(1)} }
        @keyframes ringDraw { from{stroke-dashoffset:100} to{stroke-dashoffset:0} }
        @keyframes fadeUp { from{opacity:0;transform:translateY(7px)} to{opacity:1;transform:none} }
        .ask-dots::after { content:"…"; animation: askdots 1.4s steps(4,end) infinite; }
        @keyframes askdots { 0%{content:""} 25%{content:"."} 50%{content:".."} 75%{content:"..."} }
        .tile-press:active { transform: scale(.97) !important; }
        .expandable { overflow:hidden; transition: max-height .35s ease, opacity .3s ease; }
        input::placeholder { color:${MUTE}; }
        select { -webkit-appearance:none; appearance:none; }
        ::-webkit-scrollbar { height:6px; width:6px; } ::-webkit-scrollbar-thumb { background:${LINE}; border-radius:8px; }

        /* Hero */
        .hero { padding: 52px 0 30px; text-align: center; }
        .eyebrow { font-family:${MONO}; font-size:11px; color:${TEAL}; letter-spacing:1.6px; margin-bottom:18px; }
        .hero-h1 { font-size:40px; font-weight:700; line-height:1.04; letter-spacing:-1.6px; margin:0 auto 24px; max-width:760px; text-wrap:pretty; }
        .hero-sub { font-family:${MONO}; font-size:11px; color:#5E6E8A; margin-top:14px; }

        /* Radial glow behind hero */
        .hero-glow { position:fixed; top:-180px; left:50%; transform:translateX(-50%); width:900px; height:420px; background:radial-gradient(ellipse at center, rgba(52,224,190,0.13), rgba(52,224,190,0) 68%); filter:blur(30px); pointer-events:none; z-index:0; }

        /* Search */
        .searchbar { display:flex; align-items:center; gap:12px; max-width:600px; margin:0 auto; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.12); backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px); border-radius:15px; padding:11px 14px; position:relative; z-index:1; transition:border-color .25s, box-shadow .25s; }
        .searchbar:hover, .searchbar:focus-within { border-color:rgba(52,224,190,0.5); box-shadow:0 0 0 1px rgba(52,224,190,0.22), 0 0 26px rgba(52,224,190,0.14); }
        .cmdk { font-family:${MONO}; font-size:10.5px; color:#5E6E8A; border:1px solid rgba(255,255,255,0.12); background:rgba(255,255,255,0.04); padding:3px 8px; border-radius:6px; flex-shrink:0; }
        .search-go { display:flex; align-items:center; gap:6px; background:${TEAL}; color:${INK}; border:1px solid ${TEAL}; font-weight:700; font-size:14px; padding:9px 15px; border-radius:9px; cursor:pointer; flex-shrink:0; }

        /* Filter bar */
        .filterbar { display:flex; align-items:center; gap:10px; margin-bottom:12px; }
        .cat-scroll { display:flex; gap:8px; overflow-x:auto; padding:4px 0; flex:1; scrollbar-width:none; }
        .cat-scroll::-webkit-scrollbar { display:none; }
        .tier-select { flex-shrink:0; }

        /* ===== App shell: sidebar + main ===== */
        .app-shell { display:flex; align-items:flex-start; gap:0; }
        .sidebar {
          position:sticky; top:0; align-self:flex-start; width:248px; flex-shrink:0; height:100vh;
          border-right:1px solid rgba(255,255,255,0.07); padding:22px 16px; overflow-y:auto;
          display:flex; flex-direction:column; gap:6px; background:rgba(255,255,255,0.012);
        }
        .sidebar-brand { display:flex; align-items:center; gap:10px; padding:4px 8px 18px; }
        .nav-item {
          display:flex; align-items:center; gap:10px; width:100%; text-align:left;
          padding:9px 12px; border-radius:10px; cursor:pointer; border:1px solid transparent;
          background:transparent; color:#8B9AB6; font-family:'Space Grotesk',sans-serif; font-size:13.5px;
          transition:background .18s ease, color .18s ease, border-color .18s ease;
        }
        .nav-item:hover { background:rgba(255,255,255,0.04); color:#E8EEF7; }
        .nav-item.active { background:rgba(52,224,190,0.10); color:#34E0BE; border-color:rgba(52,224,190,0.3); }
        .nav-dot { width:8px; height:8px; border-radius:3px; flex-shrink:0; }
        .main-area { flex:1; min-width:0; padding:34px 28px 60px; max-width:1000px; }
        .page-title { font-size:30px; line-height:1.1; letter-spacing:-1px; font-weight:700; margin:0 0 18px; max-width:640px; text-wrap:pretty; }
        .hamburger { display:none; }
        .sidebar-backdrop { display:none; }

        /* Grid */
        .catgrid { display:grid; grid-template-columns:repeat(auto-fill,minmax(232px,1fr)); gap:12px; }

        /* Scientific data layouts — keep labels inside their cards at every width. */
        .evidence-axis { display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin-left:32%; margin-right:92px; align-items:end; }
        .evidence-axis > span:nth-child(1) { text-align:left; }
        .evidence-axis > span:nth-child(2) { text-align:center; }
        .evidence-axis > span:nth-child(3) { text-align:right; }
        .evidence-row { display:grid; grid-template-columns:minmax(190px,32%) minmax(0,1fr) 92px; align-items:center; gap:14px; }
        .evidence-tier-right { text-align:right; }
        .chem-visual { border-right:1px solid rgba(255,255,255,.065); }
        .study-matrix { grid-template-columns:repeat(15,minmax(0,1fr)); }
        .molecular-signature-grid { display:grid; grid-template-columns:minmax(110px,150px) minmax(0,1fr); }

        @media (prefers-reduced-motion: reduce){ .rise{animation:none} .hero-glow{display:none} }
        @media (min-width: 761px){ .hero-h1 { font-size:60px; letter-spacing:-2.4px; } .hero { padding:74px 0 40px; } }
        @media (max-width: 900px){
          /* Sidebar collapses to an off-canvas drawer toggled by the hamburger. */
          .sidebar {
            position:fixed; top:0; left:0; z-index:80; height:100vh; width:250px;
            transform:translateX(-100%); transition:transform .28s cubic-bezier(.2,.9,.25,1);
            background:#0C0F16;
          }
          .sidebar.open { transform:translateX(0); }
          .sidebar-backdrop.open { display:block; position:fixed; inset:0; z-index:70; background:rgba(0,0,0,0.5); }
          .hamburger {
            display:inline-flex; align-items:center; justify-content:center; width:40px; height:40px;
            border-radius:10px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.03);
            color:#E8EEF7; cursor:pointer; margin-bottom:16px;
          }
          .main-area { padding:20px 18px 60px; }
        }
        @media (max-width: 760px){
          .desktop-top-nav{display:none!important;}
          .tagline{display:none!important;}
          .grid2 { grid-template-columns:1fr !important; }
          .verdictgrid { grid-template-columns:1fr !important; }
          .catgrid { grid-template-columns:1fr 1fr !important; }
          .go-label { display:none; }
          .search-go { padding:9px 12px; }
          .evidence-axis { display:none; }
          .evidence-row { grid-template-columns:1fr; gap:9px; padding:2px 0 8px; }
          .evidence-tier-right { text-align:left !important; display:flex; align-items:baseline; gap:8px; }
          .chem-visual { border-right:none; border-bottom:1px solid rgba(255,255,255,.065); }
          .study-matrix { grid-template-columns:repeat(12,minmax(0,1fr)) !important; }
          .molecular-signature-grid { grid-template-columns:1fr !important; }
          .molecular-signature-visual { border-right:none !important; border-bottom:1px solid rgba(255,255,255,.06); }
          .evidence-composition-grid { grid-template-columns:1fr !important; }
        }
        @media (max-width: 420px){ .tagline { display:none; } .study-matrix{grid-template-columns:repeat(10,minmax(0,1fr)) !important;} }
      `}</style>

      {/* Sticky top bar. Back stays visible while reading any deep page. */}
      <div style={{ borderBottom: `1px solid ${LINE}`, padding: "10px 20px", minHeight: 50, display: "flex", alignItems: "center", gap: 11, position: "sticky", top: 0, background: `${INK}F2`, backdropFilter: "blur(12px)", WebkitBackdropFilter:"blur(12px)", zIndex: 55 }}>
        {(showProfile || showMethod) ? (
          <motion.button aria-label={langState[0] === "es" ? "Volver" : "Back"} whileHover={{ x:-2 }} whileTap={{ scale:.96 }} onClick={closeDeepView}
            style={{ width:34, height:34, borderRadius:10, display:"grid", placeItems:"center", flexShrink:0, cursor:"pointer", background:"rgba(255,255,255,.035)", border:`1px solid ${LINE}`, color:TEXT }}>
            <ArrowLeft size={16}/></motion.button>
        ) : null}
        <button type="button" aria-label={langState[0] === "es" ? "Ir al inicio" : "Go home"} onClick={() => { setActive(null); setNotFound(null); if (onHome) onHome(); }} style={{ display: "flex", alignItems: "center", gap: 9, cursor: "pointer", border:0, background:"transparent", padding:0, color:"inherit" }}>
          <div style={{ width: 25, height: 25, borderRadius: 7, background: `linear-gradient(135deg,${TEAL},${TEAL_DIM})`, display: "grid", placeItems: "center" }}>
            <Activity size={14} color={INK} strokeWidth={2.6} />
          </div>
          <span style={{ fontWeight: 800, letterSpacing: -0.4, fontSize: 16 }}>Clarity</span>
        </button>
        <span className="tagline" style={{ paddingLeft: 11, borderLeft: `1px solid ${LINE}`, fontFamily: DISPLAY, fontSize: 12, fontWeight: 500, color: MUTE, letterSpacing: 0.1 }}>{guide.top_tagline}</span>
        <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:10}}><TopNavLinks active="research" onHome={onHome} onResearch={closeDeepView} onLearn={()=>onLearn?.("basics")} lang={langState[0]}/><GuideLanguageToggle langState={langState}/></div>
      </div>

      <div style={{ maxWidth: 1160, margin: "0 auto", padding: "0 22px" }}>

        {/* ===== PROFILE VIEW ===== */}
        {showMethod && !showProfile && (
          <MethodologyPage onBack={closeDeepView} />
        )}

        {showProfile && (
          <ProfileView view={view} source={source} onBack={closeDeepView} onLearn={onLearn} />
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
        {!showProfile && !showMethod && !loading && !error && (
          <>
            {/* Cold-start banner — only shows if the backend is slow to wake */}
            {showWakeMsg && warming ? (
              <div style={{ position: "fixed", top: 64, left: "50%", transform: "translateX(-50%)", zIndex: 50,
                display: "flex", alignItems: "center", gap: 10, padding: "10px 16px", borderRadius: 12,
                background: "rgba(52,224,190,0.10)", border: "1px solid rgba(52,224,190,0.35)", backdropFilter: "blur(10px)",
                fontFamily: MONO, fontSize: 12, color: TEAL, boxShadow: "0 8px 30px rgba(0,0,0,0.4)" }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: TEAL, animation: "pulse 1.2s ease-in-out infinite" }} />
                Warming up the research engine — first load can take a moment…
              </div>
            ) : null}
            {/* Hero glow (kept, subtle) */}
            <div aria-hidden="true" className="hero-glow" />

            <div className="app-shell">
              {/* Mobile backdrop */}
              <div className={`sidebar-backdrop ${sidebarOpen ? "open" : ""}`} onClick={() => setSidebarOpen(false)} />

              {/* ===== SIDEBAR ===== */}
              <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
                <div className="sidebar-brand">
                  <div style={{ width: 26, height: 26, borderRadius: 8, background: `linear-gradient(135deg,${TEAL},#1B7A6C)`, display: "grid", placeItems: "center", flexShrink: 0 }}>
                    <Activity size={15} color={INK} />
                  </div>
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: -0.3 }}>Clarity</div>
                    <div style={{ fontFamily: MONO, fontSize: 9, color: MUTE, letterSpacing: 0.5 }}>{t.tagline.toUpperCase()}</div>
                  </div>
                </div>

                {/* Language toggle */}
                <div style={{ display: "flex", gap: 4, padding: "0 8px 14px" }}>
                  {[["en", "EN"], ["es", "ES"]].map(([code, label]) => (
                    <button key={code} onClick={() => langState[1](code)}
                      style={{ flex: 1, padding: "6px 0", borderRadius: 8, cursor: "pointer", fontFamily: MONO, fontSize: 11, letterSpacing: 0.5,
                        background: langState[0] === code ? "rgba(52,224,190,0.12)" : "rgba(255,255,255,0.03)",
                        border: `1px solid ${langState[0] === code ? "rgba(52,224,190,0.4)" : "rgba(255,255,255,0.08)"}`,
                        color: langState[0] === code ? TEAL : MUTE }}>
                      {label}
                    </button>
                  ))}
                </div>

                <button className="nav-item" onClick={() => { setSidebarOpen(false); if (onLearn) onLearn("basics"); }} style={{ marginBottom: 8, borderColor: "rgba(52,224,190,0.16)", background: "rgba(52,224,190,0.04)" }}>
                  <BookOpen size={14} color={TEAL} />
                  <span>{guide.beginner_link}</span>
                </button>

                <div style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: 1.2, color: "#5E6E8A", padding: "0 12px 8px" }}>{t.categories}</div>
                {/* Peptides lead — the focus of the site. */}
                {CATS.peptide ? (
                  <button className={`nav-item ${catFilter === "peptide" ? "active" : ""}`} onClick={() => { setCatFilter("peptide"); setSidebarOpen(false); }}>
                    <span className="nav-dot" style={{ background: CATS.peptide.color }} />{categoryLabel("peptide", langState[0])}
                  </button>
                ) : null}
                <button className={`nav-item ${catFilter === "all" ? "active" : ""}`} onClick={() => { setCatFilter("all"); setSidebarOpen(false); }}>
                  <span className="nav-dot" style={{ background: TEAL }} />{t.all_compounds}
                </button>
                {Object.entries(CATS).filter(([k]) => k !== "goal" && k !== "peptide").map(([k, v]) => (
                  <button key={k} className={`nav-item ${catFilter === k ? "active" : ""}`} onClick={() => { setCatFilter(k); setSidebarOpen(false); }}>
                    <span className="nav-dot" style={{ background: v.color }} />{categoryLabel(k, langState[0])}
                  </button>
                ))}

                <div style={{ marginTop: "auto", paddingTop: 16, borderTop: `1px solid rgba(255,255,255,0.07)` }}>
                  <button className="nav-item" onClick={() => { if (onLearn) onLearn("evidence"); setSidebarOpen(false); }}>
                    <FlaskConical size={14} color={VIOLET} />{langState[0] === "es" ? "Guía de evidencia" : "Evidence guide"}
                  </button>
                  <button className="nav-item" onClick={() => { setView(null); setShowMethod(true); setSidebarOpen(false); onMethodologyOpen?.(); jumpToPageTop(); }}>
                    <span className="nav-dot" style={{ background: "transparent", border: `1.5px solid ${TEAL}` }} />{langState[0] === "es" ? "Cómo calificamos" : "How grading works"}
                  </button>
                </div>
              </aside>

              {/* ===== MAIN ===== */}
              <main className="main-area">
                <button className="hamburger" onClick={() => setSidebarOpen(true)} aria-label="Open menu">☰</button>

                <div className="eyebrow" style={{ marginBottom: 10 }}>{t.eyebrow}</div>
                <h1 className="page-title">
                  {t.hero_1}<span style={{ color: TEAL }}>{t.hero_evidence}</span>{t.hero_2}
                </h1>

                <div className="searchbar" style={{ margin: "0 0 16px", maxWidth: 560 }}>
                  <span style={{ fontFamily: MONO, fontSize: 15, color: "#5E6E8A", flexShrink: 0 }}>⌕</span>
                  <input ref={searchRef} value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submitSearch()}
                    placeholder={t.search_ph}
                    style={{ flex: 1, minWidth: 0, background: "transparent", border: "none", outline: "none", color: TEXT, fontSize: 16, fontFamily: DISPLAY, padding: "6px 0" }} />
                  <span className="cmdk">⌘K</span>
                  <button onClick={submitSearch} className="ev-btn search-go" aria-label={t.research}>
                    <Sparkles size={15} /><span className="go-label">{t.research}</span>
                  </button>
                </div>

                {/* Utility bar: secondary filters + topic count */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap", marginBottom: 18, paddingBottom: 14, borderBottom: `1px solid rgba(255,255,255,0.06)` }}>
                  <select value={tierFilter} onChange={(e) => setTierFilter(e.target.value)}
                    style={{ background: PANEL2, color: tierFilter === "all" ? MUTE : tierColor(tierFilter), border: `1px solid ${LINE}`, borderRadius: 20, fontFamily: MONO, fontSize: 11.5, padding: "7px 12px", outline: "none", cursor: "pointer" }}>
                    <option value="all">{t.evidence_all}</option>
                    <option value={T.strong}>{tierLabel("Strong", langState[0])}</option>
                    <option value={T.moderate}>{tierLabel("Moderate", langState[0])}</option>
                    <option value={T.emerging}>{tierLabel("Emerging", langState[0])}</option>
                    <option value={T.weak}>{langState[0] === "es" ? "Débil" : "Weak"}</option>
                  </select>
                  <span style={{ fontFamily: MONO, fontSize: 11.5, color: MUTE }}>
                    {filtered.length} {filtered.length === 1 ? t.topic : t.topics}
                    {catFilter !== "all" && <span style={{ color: CATS[catFilter].color }}> · {categoryLabel(catFilter, langState[0])}</span>}
                  </span>
                </div>

                {/* Coming-soon notice */}
                {notFound && (
                  <div className="rise" style={{ background: `${TEAL}0C`, border: `1px solid ${TEAL}33`, borderRadius: 10, padding: "11px 14px", marginBottom: 14, display: "flex", gap: 10, alignItems: "flex-start" }}>
                    <Sparkles size={15} color={TEAL} style={{ flexShrink: 0, marginTop: 2 }} />
                    <div style={{ fontSize: 13, lineHeight: 1.45 }}>
                      <b>{notFound}</b> is in the catalog — its full profile rolls out as our engine grades the studies.
                    </div>
                  </div>
                )}

                {/* Catalog grid */}
                {/* Peptide landing intro — only on the peptide view */}
                {catFilter === "peptide" ? (
                  <div style={{ borderRadius: 16, padding: "20px 22px", marginBottom: 22, background: "linear-gradient(135deg,rgba(52,224,190,0.07),rgba(154,140,245,0.05))", border: "1px solid rgba(52,224,190,0.2)" }}>
                    <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: -0.4, marginBottom: 8 }}>{langState[0] === "es" ? "Péptidos, agrupados según para qué se investigan" : "Peptides, grouped by what they're explored for"}</div>
                    <div style={{ fontSize: 13.5, lineHeight: 1.65, color: "#A9B8CE", maxWidth: 680, textWrap: "pretty" }}>
                      {langState[0] === "es" ? "Cada uno muestra su calificación real de evidencia: desde GLP-1 con grandes ensayos en humanos hasta péptidos de investigación cuya evidencia sigue siendo principalmente animal. Empieza por el mecanismo, mira dónde está realmente la ciencia y qué falta por demostrar." : "Each one below carries its real evidence grade — from GLP-1s with large human trials to research peptides still living mostly in animal data. Lead with the mechanism, see where the science actually stands, and where it might go next."}
                    </div>
                  </div>
                ) : null}

                {(() => {
                  // One card renderer, used by both the flat grid and the grouped view.
                  const renderCard = (c, i) => {
                    const [name, cat] = c;
                    const cc = CATS[cat];
                    const live = liveTier(name);
                    const graded = !!live;
                    const tier = live ? live.tier : null;
                    const bestTier = live?.bestTier || tier;
                    const outcomeDependent = !!live?.outcomeDependent;
                    const displayTier = outcomeDependent ? (langState[0] === "es" ? "Depende del resultado" : "Outcome-dependent") : tierLabel(tier, langState[0]);
                    const tc = graded ? tierColor(bestTier) : "#5E6E8A";
                    const fillPct = bestTier === "Strong" ? "90%" : bestTier === "Moderate" ? "62%" : bestTier === "Emerging" ? "40%" : bestTier === "Preliminary" ? "24%" : "0%";
                    return (
                      <motion.div key={name + i}
                        initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: Math.min(i * 0.03, 0.6), duration: 0.35, ease: "easeOut" }}
                        className="cat-tile tile-press" role="button" tabIndex={0} aria-label={`${langState[0] === "es" ? "Abrir evidencia para" : "Open evidence for"} ${name}`} onClick={() => runResearch(name, cat)}
                        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); runResearch(name, cat); } }}
                        onMouseEnter={() => prefetchProfile(name, cat)}
                        style={{
                          background: "rgba(255,255,255,0.025)",
                          border: "1px solid rgba(255,255,255,0.07)",
                          borderRadius: 14, padding: "16px 17px", display: "flex", flexDirection: "column", justifyContent: "space-between", gap: 10, minHeight: 132,
                          cursor: "pointer", transition: "border-color .22s, background .22s, transform .22s",
                        }}
                        whileHover={{ y: -3, borderColor: "rgba(52,224,190,0.45)", backgroundColor: "rgba(255,255,255,0.055)" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                          <span style={{ fontSize: 14.5, fontWeight: 600, lineHeight: 1.3 }}>{name}</span>
                          {graded ? (
                            <span style={{ display: "flex", alignItems: "center", gap: 5, fontFamily: MONO, fontSize: 10, color: tc, flexShrink: 0 }}>
                              <span style={{ width: 8, height: 8, borderRadius: 2, background: tc }} />{displayTier}
                            </span>
                          ) : (
                            <span style={{ display: "flex", alignItems: "center", gap: 5, fontFamily: MONO, fontSize: 9.5, color: "#5E6E8A", flexShrink: 0 }}>
                              <span style={{ width: 8, height: 8, borderRadius: 2, border: "1.5px dashed #5E6E8A" }} />{langState[0] === "es" ? "Sin calificar" : "Ungraded"}
                            </span>
                          )}
                        </div>
                        <div style={{ height: 6, borderRadius: 3, background: "rgba(255,255,255,0.05)", overflow: "hidden" }}>
                          {graded ? (
                            <div className="growbar" style={{ height: "100%", borderRadius: 3, width: fillPct, background: tc }} />
                          ) : (
                            <div style={{ height: "100%", borderRadius: 3, width: "100%", background: "repeating-linear-gradient(90deg,rgba(255,255,255,0.08) 0 5px,transparent 5px 10px)" }} />
                          )}
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, fontFamily: MONO, fontSize: 9.5, color: "#5E6E8A" }}>
                          <span>{categoryLabel(cat, langState[0])}</span>
                          {graded ? (
                            outcomeDependent && live.bestOutcome ? (
                              <span title={`${live.bestOutcome} · ${live.bestTier || tier}`} style={{ color: tc, maxWidth: "64%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "right" }}>
                                {langState[0] === "es" ? "mejor: " : "best: "}{live.bestOutcome} · {tierLabel(live.bestTier || tier, langState[0])}
                              </span>
                            ) : (
                              <span style={{ color: "#5E6E8A", opacity: 0.9 }}>{langState[0] === "es" ? "ver evidencia →" : "view evidence →"}</span>
                            )
                          ) : (
                            <span style={{ color: "#5E6E8A", opacity: 0.8 }}>{langState[0] === "es" ? "aún sin calificar" : "not graded yet"}</span>
                          )}
                        </div>
                      </motion.div>
                    );
                  };

                  // Peptide view: group into families with section headers.
                  if (catFilter === "peptide") {
                    let idx = 0;
                    const byFam = {};
                    filtered.forEach((c) => {
                      const f = peptideFamilyOf(c[0]);
                      (byFam[f] = byFam[f] || []).push(c);
                    });
                    return (
                      <div style={{ paddingBottom: 60 }}>
                        {PEPTIDE_FAMILIES.filter((fam) => (byFam[fam.key] || []).length).map((fam) => (
                          <div key={fam.key} style={{ marginBottom: 30 }}>
                            <div style={{ marginBottom: 12 }}>
                              <div style={{ fontSize: 15.5, fontWeight: 700, letterSpacing: -0.3 }}>{langState[0] === "es" ? (PEPTIDE_FAMILY_ES[fam.key]?.label || fam.label) : fam.label}</div>
                              <div style={{ fontSize: 12.5, color: "#8B9AB6", lineHeight: 1.5, marginTop: 3, maxWidth: 620 }}>{langState[0] === "es" ? (PEPTIDE_FAMILY_ES[fam.key]?.blurb || fam.blurb) : fam.blurb}</div>
                            </div>
                            <div className="catgrid">
                              {byFam[fam.key].map((c) => renderCard(c, idx++))}
                            </div>
                          </div>
                        ))}

                        {/* BLENDS — not graded; components + honest "why" + links */}
                        <div style={{ marginBottom: 30, marginTop: 8 }}>
                          <div style={{ marginBottom: 6 }}>
                            <div style={{ fontSize: 15.5, fontWeight: 700, letterSpacing: -0.3 }}>Blends</div>
                            <div style={{ fontSize: 12.5, color: "#8B9AB6", lineHeight: 1.55, marginTop: 3, maxWidth: 660 }}>
                              Multi-peptide combos sold as one product. We don't grade blends — no study tests the specific combination, so a grade would be inventing evidence that doesn't exist. Instead we show what's inside and link to the real evidence for each part.
                            </div>
                          </div>
                          <div style={{ borderRadius: 12, padding: "14px 16px", marginBottom: 14, background: "rgba(154,140,245,0.05)", border: "1px solid rgba(154,140,245,0.2)", fontSize: 12.5, lineHeight: 1.6, color: "#A9B8CE", maxWidth: 680 }}>
                            <b style={{ color: VIOLET }}>Why they're sold as blends:</b> the components usually target the same goal through different mechanisms, so vendors combine them for convenience (one injection) and a synergy rationale. Important: "sold together" reflects that rationale and marketing — <b>not</b> evidence that the combination works better than the parts. No trials test these specific mixes.
                          </div>
                          <div className="catgrid">
                            {BLENDS.map((b) => (
                              <div key={b.name} style={{ borderRadius: 14, padding: "16px 17px", background: "rgba(255,255,255,0.025)", border: "1px solid rgba(255,255,255,0.07)", display: "flex", flexDirection: "column", gap: 10 }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                                  <span style={{ fontSize: 14.5, fontWeight: 600 }}>{b.name}</span>
                                  <span style={{ fontFamily: MONO, fontSize: 9, color: VIOLET, border: `1px solid ${VIOLET}55`, borderRadius: 5, padding: "2px 6px", whiteSpace: "nowrap" }}>BLEND</span>
                                </div>
                                <div style={{ fontSize: 12.5, color: "#8B9AB6", lineHeight: 1.5 }}>{b.pitch}</div>
                                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                  {b.components.map((comp) => (
                                    <button key={comp} onClick={() => runResearch(comp, "peptide")}
                                      style={{ fontFamily: MONO, fontSize: 10.5, color: TEAL, background: "rgba(52,224,190,0.08)", border: `1px solid rgba(52,224,190,0.3)`, borderRadius: 6, padding: "3px 8px", cursor: "pointer" }}>
                                      {comp} →
                                    </button>
                                  ))}
                                </div>
                                {b.unverified ? (
                                  <div style={{ fontFamily: MONO, fontSize: 9, color: "#8B9AB6" }}>exact composition not independently verified by Clarity</div>
                                ) : null}
                                <a href={buildAffiliateUrl(b.name)} target="_blank" rel="noreferrer nofollow sponsored"
                                  style={{ fontFamily: MONO, fontSize: 10.5, color: INK, background: TEAL, borderRadius: 7, padding: "6px 10px", textAlign: "center", textDecoration: "none", fontWeight: 700, marginTop: 2 }}>
                                  Shop {b.name} ↗
                                </a>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    );
                  }

                  // All other views: flat grid.
                  return (
                    <div className="catgrid" style={{ paddingBottom: 60 }}>
                      {filtered.map((c, i) => renderCard(c, i))}
                    </div>
                  );
                })()}
                {filtered.length === 0 && (
                  <div style={{ textAlign: "center", padding: "40px 0 80px", color: MUTE, fontFamily: MONO, fontSize: 13 }}>
                    No topics match. Try clearing filters.
                  </div>
                )}
              </main>
            </div>
          </>
        )}
      </div>
    </div>
    </LangContext.Provider>
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
// Curated pharmacokinetics — REAL, CITED values only (see pharmacokinetics.py
// Pharmacokinetics comes from the backend's curated, cited pharmacokinetics.py.
// The frontend never carries an independent scientific PK dataset.
// Pharmacokinetics: concentration-time curve + parameter cards. Renders only
// when curated, cited data exists for the compound.
function PharmacokineticsBlock({ pk }) {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  if (!pk) return null;
  pk = { ...pk, route: pk.route || pk.display_route || "oral", tmaxLabel: pk.tmaxLabel || pk.tmax_label, halfLifeLabel: pk.halfLifeLabel || pk.half_life_label, bioavailLabel: pk.bioavailLabel || pk.bioavailability_label, cmaxLabel: pk.cmaxLabel || pk.cmax_label, vdLabel: pk.vdLabel || pk.vd_label };
  const W = 620, Hgt = 210, padL = 44, padB = 34, padT = 28, padR = 16;
  const maxH = pk.curve[pk.curve.length - 1][0];
  const xu = pk.xUnit || "h";
  const X = (h) => padL + (h / maxH) * (W - padL - padR);
  const Y = (p) => padT + (1 - p / 100) * (Hgt - padT - padB);
  const line = pk.curve.map((pt, i) => `${i === 0 ? "M" : "L"}${X(pt[0]).toFixed(1)},${Y(pt[1]).toFixed(1)}`).join(" ");
  const area = `${line} L${X(maxH).toFixed(1)},${Y(0).toFixed(1)} L${X(0).toFixed(1)},${Y(0).toFixed(1)} Z`;
  const tmaxPt = pk.curve.reduce((a, b) => (b[1] > a[1] ? b : a), pk.curve[0]);
  const cards = [
    { label: es ? "TIEMPO AL PICO (Tmax)" : "TIME TO PEAK (Tmax)", value: pk.tmaxLabel },
    { label: es ? "SEMIVIDA (t½)" : "HALF-LIFE (t½)", value: pk.halfLifeLabel },
    { label: es ? "BIODISPONIBILIDAD ORAL" : "ORAL BIOAVAILABILITY", value: pk.bioavailLabel },
    { label: es ? "CONC. MÁXIMA (Cmax)" : "PEAK CONC. (Cmax)", value: pk.cmaxLabel },
    { label: es ? "VOL. DE DISTRIBUCIÓN" : "VOL. OF DISTRIBUTION", value: pk.vdLabel },
    { label: es ? "METABOLISMO" : "METABOLISM", value: pk.metabolism },
  ];
  return (
    <div style={{ padding:"24px 0", background:"transparent", borderBottom:"1px solid rgba(255,255,255,.055)", marginBottom:20 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline", justifyContent: "space-between", marginBottom: 6 }}>
        <div style={{ fontSize:14, fontWeight:650, color:"#C9D5E4" }}>{es?"Farmacocinética":"Pharmacokinetics"} <span style={{fontWeight:450,color:MUTE}}>— {es?"cómo se mueve por el organismo":"how it moves through the body"}</span></div>
        <div style={{ fontFamily: MONO, fontSize: 10, color: "#5E6E8A" }}>{pk.route.toUpperCase()} · {es?"ADULTOS SANOS":"HEALTHY ADULTS"}</div>
      </div>
      <div style={{ fontSize: 13, lineHeight: 1.6, color: "#A9B8CE", marginBottom: 18, maxWidth: 640, textWrap: "pretty" }}>
        {es ? "Concentración plasmática relativa tras una dosis única: ascenso al pico (Tmax) y descenso gobernado por la semivida. La forma está basada en datos citados; el eje representa % del pico, no una dosis absoluta." : "Relative plasma concentration after a single dose — the rise to peak (Tmax) and the fall governed by half-life. Shape is real and cited; the axis is % of peak, not an absolute dose."}
      </div>

      {/* Curve */}
      <svg viewBox={`0 0 ${W} ${Hgt}`} style={{ width: "100%", maxWidth: 640, marginBottom: 20 }}>
        <defs>
          <linearGradient id={`pkfill-${pk.route}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={TEAL} stopOpacity="0.28" />
            <stop offset="100%" stopColor={TEAL} stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* gridlines */}
        {[0, 25, 50, 75, 100].map((p) => (
          <g key={p}>
            <line x1={padL} y1={Y(p)} x2={W - padR} y2={Y(p)} stroke="rgba(255,255,255,0.06)" strokeWidth="1" />
            <text x={padL - 8} y={Y(p) + 3} fill="#5E6E8A" fontSize="9" textAnchor="end" fontFamily="JetBrains Mono">{p}</text>
          </g>
        ))}
        {/* x ticks — skip labels too close to the y-axis to avoid 0h/0.75h overlap */}
        {pk.curve.filter((pt, i) => i % 3 === 0 && pt[0] >= 1).map((pt) => (
          <text key={pt[0]} x={X(pt[0])} y={Hgt - padB + 16} fill="#5E6E8A" fontSize="9" textAnchor="middle" fontFamily="JetBrains Mono">{pt[0]}{xu}</text>
        ))}
        <text x={padL} y={Hgt - padB + 16} fill="#5E6E8A" fontSize="9" textAnchor="middle" fontFamily="JetBrains Mono">0{xu}</text>
        <path d={area} fill={`url(#pkfill-${pk.route})`} style={{ animation: "fadeUp .6s .2s both" }} />
        <path d={line} fill="none" stroke={TEAL} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" style={{ animation: "fadeUp .6s both" }} />
        {/* Tmax marker */}
        <line x1={X(tmaxPt[0])} y1={Y(tmaxPt[1])} x2={X(tmaxPt[0])} y2={Y(0)} stroke={TEAL} strokeWidth="1" strokeDasharray="3 3" opacity="0.5" />
        <circle cx={X(tmaxPt[0])} cy={Y(tmaxPt[1])} r="5" fill={TEAL} style={{ animation: "fadeUp .4s .6s both" }} />
        <text x={X(tmaxPt[0]) + 14} y={Y(tmaxPt[1]) - 12} fill={TEAL} fontSize="10" textAnchor="start" fontFamily="JetBrains Mono">peak · {tmaxPt[0]}{xu}</text>
      </svg>

      {/* Parameter cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(150px,1fr))", gap: 8, marginBottom: 14 }}>
        {cards.map((c, i) => (
          <div key={i} style={{ padding:"10px 2px 11px", borderBottom:"1px solid rgba(255,255,255,.055)" }}>
            <div style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: 1, color: "#5E6E8A", marginBottom: 6 }}>{c.label}</div>
            <div style={{ fontFamily: MONO, fontSize: 12.5, lineHeight: 1.4, color: TEXT, wordBreak: "break-word" }}>{c.value}</div>
          </div>
        ))}
      </div>

      {pk.notes ? <div style={{ fontSize: 12.5, lineHeight: 1.6, color: "#8B9AB6", marginBottom: 12, textWrap: "pretty" }}>{pk.notes}</div> : null}

      <div style={{ borderTop: "1px solid rgba(255,255,255,0.07)", paddingTop: 12, fontFamily: MONO, fontSize: 10, color: "#5E6E8A" }}>
        {pk.sources.map((s, i) => (
          <a key={i} href={s.url} target="_blank" rel="noreferrer" style={{ color: "#6FA8F2", textDecoration: "none", display: "block", marginBottom: 3 }}>{s.label} ↗</a>
        ))}
      </div>
    </div>
  );
}

function ChemistryBlock({ chem, meaning }) {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  const [open, setOpen] = useState(false);
  if (!chem || !chem.formula) return null;

  const properties = [];
  if (chem.formula) properties.push({ label: es ? "FÓRMULA MOLECULAR" : "MOLECULAR FORMULA", value: chem.formula, accent: TEAL, span: 2 });
  if (chem.weight) properties.push({ label: es ? "MASA MOLAR" : "MOLAR MASS", value: `${chem.weight} g/mol` });
  if (chem.xlogp !== null && chem.xlogp !== undefined) properties.push({ label: "XLOGP", value: String(chem.xlogp), note: es ? "lipofilia" : "lipophilicity" });
  if (chem.tpsa !== null && chem.tpsa !== undefined) properties.push({ label: "TPSA", value: `${chem.tpsa} Å²`, note: es ? "superficie polar" : "polar surface area" });
  if ((chem.hbond_donors !== null && chem.hbond_donors !== undefined) || (chem.hbond_acceptors !== null && chem.hbond_acceptors !== undefined)) {
    properties.push({ label: es ? "PUENTES H DON / ACEP" : "H-BOND DON / ACC", value: `${chem.hbond_donors ?? "—"} / ${chem.hbond_acceptors ?? "—"}` });
  }
  if (chem.inchikey) properties.push({ label: "INCHIKEY", value: chem.inchikey, monoSmall: true, span: 2 });
  if (chem.synonyms && chem.synonyms.length) properties.push({ label: es ? "OTROS NOMBRES" : "ALSO KNOWN AS", value: chem.synonyms.slice(0, 4).join(", "), monoSmall: true, span: 2 });

  const img = chem.image_url || (chem.cid ? `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/${chem.cid}/PNG?record_type=2d&image_size=320x260` : null);
  return (
    <section id="chemistry" style={{ overflow:"hidden", background:"transparent", borderTop:"1px solid rgba(255,255,255,.075)", borderBottom:"1px solid rgba(255,255,255,.055)", marginBottom:20 }}>
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", gap:12, flexWrap:"wrap", padding:"16px 0", borderBottom:"1px solid rgba(255,255,255,.055)", background:"transparent" }}>
        <div style={{ display:"flex", alignItems:"center", gap:10 }}>
          <div style={{ width:30, height:30, borderRadius:9, background:`${TEAL}12`, border:`1px solid ${TEAL}30`, display:"grid", placeItems:"center", color:TEAL }}>{IconFlask}</div>
          <div><div style={{ fontSize:14, fontWeight:650, color:"#C9D5E4" }}>{es ? "Química" : "Chemistry"}</div><div style={{ fontSize:11.5, color:MUTE, marginTop:2 }}>{es ? "Identidad y propiedades verificadas" : "Verified identity & molecular properties"}</div></div>
        </div>
        {chem.cid ? <div style={{ fontFamily:MONO, fontSize:9.5, color:"#667893", padding:"5px 8px", borderRadius:8, border:`1px solid ${LINE}`, background:"rgba(255,255,255,.02)" }}>PUBCHEM CID {chem.cid}</div> : null}
      </div>

      <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit,minmax(260px,1fr))", gap:0 }}>
        <div className="chem-visual" style={{ padding:22, background:"rgba(255,255,255,.012)" }}>
          {img ? <div style={{ width:"100%", maxWidth:270, aspectRatio:"1.18", margin:"0 auto", borderRadius:16, background:"rgba(255,255,255,.96)", border:"1px solid rgba(255,255,255,.15)", display:"grid", placeItems:"center", overflow:"hidden" }}><img src={img} alt={`PubChem 2D structure of ${chem.matched_query || "compound"}`} style={{ width:"100%", height:"100%", objectFit:"contain" }} /></div> : null}
          <div style={{ display:"flex", justifyContent:"space-between", gap:10, alignItems:"center", marginTop:12 }}><div style={{ fontFamily:MONO, fontSize:9.5, lineHeight:1.55, color:"#5E6E8A" }}>{es ? "representación 2D estandarizada" : "standardized 2D depiction"}</div>{chem.pubchem_url ? <a href={chem.pubchem_url} target="_blank" rel="noreferrer" style={{ color:"#6FA8F2", fontFamily:MONO, fontSize:10, textDecoration:"none", whiteSpace:"nowrap" }}>{es ? "Fuente" : "Source"} ↗</a> : null}</div>
        </div>

        <div style={{ padding:"22px 0 22px 22px" }}>
          <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit,minmax(145px,1fr))", gap:9 }}>
            {properties.map((c, i) => <div key={i} style={{ gridColumn:c.span===2?"1 / -1":undefined, minWidth:0, padding:"11px 2px 12px", borderBottom:"1px solid rgba(255,255,255,.06)" }}><div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", gap:8, marginBottom:7 }}><div style={{ fontFamily:MONO, fontSize:9.2, letterSpacing:1.05, color:"#667893" }}>{c.label}</div>{c.note ? <div style={{ fontFamily:MONO, fontSize:8.8, color:"#4E6079" }}>{c.note}</div> : null}</div><div style={{ fontFamily:MONO, fontSize:c.monoSmall?11.3:13.5, lineHeight:1.38, color:c.accent||TEXT, wordBreak:"break-word" }}>{c.value}</div></div>)}
          </div>
          {meaning ? <div style={{ background:"transparent", borderTop:"1px solid rgba(255,255,255,.06)", marginTop:12, overflow:"hidden" }}><motion.button whileHover={{ backgroundColor:"rgba(255,255,255,.032)" }} whileTap={{ scale:.997 }} onClick={()=>setOpen(!open)} aria-expanded={open} style={{ width:"100%", cursor:"pointer", display:"flex", gap:12, alignItems:"center", padding:"13px 15px", border:"none", background:"transparent", color:TEXT, textAlign:"left" }}><span style={{ color:TEAL, display:"grid", flexShrink:0 }}>{IconFlask}</span><div style={{ flex:1 }}><div style={{ fontFamily:MONO, fontSize:9.5, color:TEAL, letterSpacing:1.1 }}>{es ? "INTERPRETACIÓN" : "INTERPRETATION"}</div><div style={{ fontSize:13.5, color:"#C9D6E7", marginTop:2 }}>{es ? "Qué significan estas propiedades" : "What these properties actually mean"}</div></div><motion.span animate={{ rotate:open?180:0 }} transition={{ duration:.25 }} style={{ color:"#5E6E8A", fontSize:12 }}>▾</motion.span></motion.button><AnimatePresence initial={false}>{open ? <motion.div initial={{ height:0, opacity:0 }} animate={{ height:"auto", opacity:1 }} exit={{ height:0, opacity:0 }} transition={{ duration:.32, ease:MOTION_EASE }} style={{ overflow:"hidden" }}><div style={{ padding:"0 15px 15px 47px", fontSize:13.5, lineHeight:1.7, color:"#A9B8CE", textWrap:"pretty" }}>{meaning}</div></motion.div> : null}</AnimatePresence></div> : null}
        </div>
      </div>
    </section>
  );
}
const IconFlask = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="20" height="20"><path d="M9 3h6" /><path d="M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3" /><path d="M7.5 15h9" /></svg>;

// Critical appraisal — the "how this could be wrong" layer. Deliberately COOLER
// than the rest of the page (slate, not teal) so it reads as a separate voice:
// the methodologist reviewing the evidence rather than the app presenting it.
function AppraisalSection({ ap }) {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  if (!ap || !ap.headline) return null;
  const sev = { high: D.coral, moderate: D.amber, low: D.dim };
  return (
    <div style={{ marginTop: 34, paddingTop: 26, borderTop: `1px solid ${D.line}` }}>
      <Eyebrow color={D.dim}>{es ? "Cómo podría estar equivocado" : "How this could be wrong"}</Eyebrow>
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
          <Eyebrow color={D.blue}>{es ? "¿El mecanismo respalda la afirmación?" : "Does the mechanism support the claim?"}</Eyebrow>
          <div style={{ color: D.text2, fontSize: 13.5, lineHeight: 1.7 }}>{ap.mechanism_check}</div>
        </Panel>
      ) : null}

      {ap.strongest_counterargument ? (
        <Panel style={{ marginTop: 12, padding: "16px 18px" }}>
          <Eyebrow color={D.coral}>{es ? "El argumento más fuerte en contra" : "The strongest case against"}</Eyebrow>
          <div style={{ color: D.text2, fontSize: 13.5, lineHeight: 1.7 }}>{ap.strongest_counterargument}</div>
        </Panel>
      ) : null}

      {ap.what_would_change_the_picture ? (
        <div style={{ marginTop: 14, color: D.muted, fontSize: 12.5, lineHeight: 1.65 }}>
          <span style={{ color: D.teal }}>{es ? "Qué ayudaría a resolverlo: " : "What would settle it: "}</span>{ap.what_would_change_the_picture}
        </div>
      ) : null}
    </div>
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

function plainTier(tier, hasHuman, lang = "en") {
  const es = lang === "es";
  switch (tier) {
    case "Strong": return es ? "Bien respaldado por evidencia humana — de lo más establecido dentro de este perfil." : "Well-supported by human evidence within this outcome.";
    case "Moderate": return es ? "Buena evidencia humana, aunque todavía no es definitiva." : "Good human evidence, though not yet airtight.";
    case "Emerging": return es ? "Solo señales tempranas — todavía hay muy pocos datos humanos para confiar en el efecto." : "Early signs only — too little human data to rely on yet.";
    case "Preliminary": return hasHuman ? (es ? "Evidencia humana muy limitada hasta ahora." : "Very limited human evidence so far.") : (es ? "Principalmente datos de laboratorio o animales — no demostrado en personas." : "Mostly lab or animal data — unproven in people.");
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

function effectNullValue(metric) {
  const m = String(metric || "").toLowerCase();
  // Ratio measures are null at 1. Difference/standardized-difference measures
  // are null at 0. Keep this centralized so every figure and sentence agrees.
  return /(^|_|\b)(or|rr|hr)(_|\b)|odds[_ ]?ratio|risk[_ ]?ratio|hazard[_ ]?ratio|rate[_ ]?ratio/.test(m) ? 1 : 0;
}

function effectCrossesNull(eff) {
  if (!eff || typeof eff.ciLow !== "number" || typeof eff.ciHigh !== "number") return null;
  const n = effectNullValue(eff.metric);
  return eff.ciLow <= n && eff.ciHigh >= n;
}

function effectPrecisionText(eff, lang = "en") {
  const es = lang === "es";
  if (!eff || typeof eff.ciLow !== "number" || typeof eff.ciHigh !== "number") return es ? "precisión no informada" : "precision not reported";
  const crosses = effectCrossesNull(eff);
  const n = effectNullValue(eff.metric);
  if (crosses) return es ? `el IC del 95% incluye el valor sin efecto (${n}), por lo que no se confirma un efecto claro` : `95% CI includes the no-effect value (${n}), so a clear effect is not confirmed`;
  return es ? `el IC del 95% permanece a un lado del valor sin efecto (${n})` : `95% CI stays on one side of the no-effect value (${n})`;
}

function layerDescriptor(score, lang = "en") {
  const es = lang === "es";
  const n = Number(score || 0);
  if (n >= 75) return es ? "alto" : "high";
  if (n >= 45) return es ? "moderado" : "moderate";
  if (n > 0) return es ? "temprano" : "early";
  return es ? "sin señal" : "no signal";
}

function humanEvidenceMeaning(o, lang = "en") {
  const es = lang === "es";
  const nH = (o.layers && o.layers.nHuman) || 0;
  const nA = (o.layers && o.layers.nAnimal) || 0;
  if (o.tier === "Strong") return es
    ? `Hay una base humana sustancial para este resultado (${nH} estudios identificados en personas), por lo que la confianza general es alta.`
    : `There is a substantial human evidence base for this outcome (${nH} identified human studies), so overall confidence is high.`;
  if (o.tier === "Moderate") return es
    ? `Existe evidencia humana significativa (${nH} estudios), pero todavía hay suficiente incertidumbre como para no llamarla definitiva.`
    : `There is meaningful human evidence (${nH} studies), but enough uncertainty remains that it is not considered definitive.`;
  if (o.tier === "Emerging") return nH > 0
    ? (es ? `Hay una señal humana temprana (${nH} ${nH===1?"estudio":"estudios"}), pero la evidencia todavía es demasiado limitada para una conclusión firme.` : `There is an early human signal (${nH} ${nH===1?"study":"studies"}), but the evidence is still too limited for a firm conclusion.`)
    : (es ? `La señal proviene de mecanismos o modelos animales (${nA} estudios animales) y todavía no establece un beneficio en personas.` : `The signal comes from mechanistic or animal work (${nA} animal studies) and does not yet establish a benefit in people.`);
  return nH > 0
    ? (es ? `La evidencia humana es muy escasa (${nH} ${nH===1?"estudio":"estudios"}); interprétala como una pregunta abierta, no como una respuesta.` : `Human evidence is very sparse (${nH} ${nH===1?"study":"studies"}); treat this as an open question, not an answer.`)
    : (es ? `No se identificaron estudios humanos para este resultado. Los datos preclínicos pueden ser informativos, pero no prueban que funcione en personas.` : `No human studies were identified for this outcome. Preclinical data can be informative, but it does not prove the effect works in people.`);
}

function plainEffectMeaning(o, lang = "en") {
  const es = lang === "es";
  const eff = o.headlineEffect;
  if (!eff || eff.value == null) return es
    ? "No hay un tamaño de efecto combinado suficientemente verificable para resumirlo en un solo número."
    : "There is no sufficiently verified pooled effect size to summarize this outcome with one number.";
  if (typeof eff.ciLow !== "number" || typeof eff.ciHigh !== "number") return es
    ? `Se extrajo una estimación de efecto (${eff.value}), pero no una banda de incertidumbre verificable; no conviene sobreinterpretar el número.`
    : `An effect estimate (${eff.value}) was extracted, but not a verified uncertainty range, so the number should not be over-interpreted.`;
  const crosses = effectCrossesNull(eff);
  const n = effectNullValue(eff.metric);
  if (crosses) return es
    ? `El intervalo del 95% incluye el punto de “sin efecto” (${n}). Eso significa que esta estimación concreta todavía es compatible con poco o ningún efecto, aunque la calificación general también considera el resto del cuerpo de evidencia.`
    : `The 95% confidence interval includes the “no effect” point (${n}). That means this particular estimate is still compatible with little or no effect, even though the overall grade also considers the rest of the evidence base.`;
  return es
    ? `El intervalo del 95% permanece a un solo lado del punto de “sin efecto” (${n}), por lo que esta estimación es más consistente con una diferencia real. Eso no elimina otros límites del conjunto de estudios.`
    : `The 95% confidence interval stays on one side of the “no effect” point (${n}), so this estimate is more consistent with a real difference. That does not remove other limitations in the evidence base.`;
}

function consumerEvidenceSummary(o, lang = "en") {
  const es = lang === "es";
  const dir = o.weighted && o.weighted.direction;
  let directionText = "";
  if (dir === "favors_control") directionText = es ? " La dirección observada favorece al comparador, no al tratamiento." : " The observed direction favors the comparator rather than the treatment.";
  else if (dir === "null_result") directionText = es ? " El conjunto de datos no muestra un beneficio claro." : " The evidence does not show a clear benefit.";
  else if (dir === "favors_treatment") directionText = es ? " La dirección general favorece al tratamiento." : " The overall direction favors treatment.";
  return `${humanEvidenceMeaning(o, lang)} ${plainEffectMeaning(o, lang)}${directionText}`;
}

function studyDesignCounts(studies) {
  const rows = Array.isArray(studies) ? studies : [];
  const counts = { meta: 0, rct: 0, trial: 0, observational: 0, animal: 0, invitro: 0, other: 0 };
  for (const s of rows) {
    const d = String(s.design || "").toLowerCase();
    if (d.includes("meta") || d.includes("systematic")) counts.meta += 1;
    else if (d === "rct" || d.includes("random")) counts.rct += 1;
    else if (d.includes("clinical trial") || d === "trial") counts.trial += 1;
    else if (d.includes("observ")) counts.observational += 1;
    else if (d.includes("animal") || String(s.population || "").toLowerCase() === "animal") counts.animal += 1;
    else if (d.includes("vitro")) counts.invitro += 1;
    else counts.other += 1;
  }
  return counts;
}

function EvidenceComposition({ studies, color }) {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  if (!studies || !studies.length) return null;
  const c = studyDesignCounts(studies);
  const items = [
    [es ? "Metanálisis / revisiones" : "Meta / reviews", c.meta], ["RCTs", c.rct], [es ? "Ensayos clínicos" : "Clinical trials", c.trial],
    [es ? "Observacionales" : "Observational", c.observational], [es ? "Animal" : "Animal", c.animal], [es ? "In vitro" : "In vitro", c.invitro],
  ].filter(([, n]) => n > 0);
  if (!items.length) return null;
  const max = Math.max(...items.map(([, n]) => n), 1);
  return (
    <div style={{ margin: "14px 0 16px", padding: "13px 14px", borderRadius: 11, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(255,255,255,0.07)" }}>
      <div style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: 1.2, color: "#5E6E8A", marginBottom: 10 }}>{es ? "COMPOSICIÓN DE LA BASE DE EVIDENCIA" : "EVIDENCE-BASE COMPOSITION"}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(112px,1fr))", gap: 9 }}>
        {items.map(([label, n]) => (
          <div key={label}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 6, fontFamily: MONO, fontSize: 9.5, color: "#8B9AB6", marginBottom: 4 }}><span>{label}</span><span>{n}</span></div>
            <div style={{ height: 5, borderRadius: 3, background: "rgba(255,255,255,0.055)", overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${Math.max(8, (n / max) * 100)}%`, borderRadius: 3, background: color }} />
            </div>
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
  const lo = typeof eff.ciLow === "number" ? eff.ciLow : eff.value;
  const hi = typeof eff.ciHigh === "number" ? eff.ciHigh : eff.value;
  const nullV = effectNullValue(eff.metric);
  const span = Math.max(Math.abs(hi - lo), Math.abs(eff.value - nullV), 0.25);
  const xmin = Math.min(nullV, lo, eff.value) - span * 0.3;
  const xmax = Math.max(nullV, hi, eff.value) + span * 0.3;
  const sx = (v) => 20 + ((v - xmin) / Math.max(1e-9, xmax - xmin)) * 180;
  const crosses = effectCrossesNull({ ...eff, ciLow: lo, ciHigh: hi });
  const col = crosses ? AMBER : TEAL;
  return (
    <div>
      <div style={{ color: "#5A6B87", fontSize: 10, marginBottom: 6 }}>POOLED EFFECT + UNCERTAINTY</div>
      <svg viewBox="0 0 220 44" width="100%" role="img" aria-label={`Pooled effect ${eff.value}, CI ${lo} to ${hi}; no-effect value ${nullV}`}>
        <line x1="20" y1="22" x2="200" y2="22" stroke={LINE} strokeWidth="1" />
        <line x1={sx(nullV)} y1="8" x2={sx(nullV)} y2="36" stroke="#5A6B87" strokeWidth="1" />
        <text x={sx(nullV)} y="6" fill="#5A6B87" fontSize="8" textAnchor="middle" fontFamily="Inter">null {nullV}</text>
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

function SectionHeading({ index, title, subtitle, action }) {
  return <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-end", gap:16, flexWrap:"wrap", margin:"48px 0 18px" }}>
    <div style={{ minWidth:0 }}>
      {index ? <div style={{fontFamily:MONO,fontSize:9.5,color:TEAL,letterSpacing:.8,marginBottom:7}}>{index}</div> : null}
      <h2 style={{margin:0,fontSize:25,fontWeight:680,letterSpacing:-.7,color:TEXT}}>{title}</h2>
      {subtitle ? <p style={{margin:"7px 0 0",fontSize:13.5,lineHeight:1.6,color:MUTE,maxWidth:760}}>{subtitle}</p> : null}
    </div>
    {action || null}
  </div>;
}

function EvidenceMap({ outcomes, ex }) {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const tierRank = { Strong: 3, Moderate: 2, Emerging: 1, Preliminary: 0 };
  const rows = [...outcomes].sort((a, b) => {
    const t = (tierRank[b.tier] || 0) - (tierRank[a.tier] || 0);
    if (t !== 0) return t;
    return ((b.weighted && b.weighted.score) || 0) - ((a.weighted && a.weighted.score) || 0);
  });
  const tierBase = { Preliminary: 14, Emerging: 32, Moderate: 64, Strong: 90 };
  const pctFor = (o) => {
    const base = tierBase[o.tier] ?? 30;
    return Math.min(97, base + (((o.weighted && o.weighted.score) || 0) / 100) * 7.5);
  };
  const qualityFlags = (o) => {
    const flags = [];
    const dir = o.weighted && o.weighted.direction;
    const nH = (o.layers && o.layers.nHuman) || 0;
    if (dir === "favors_control" || dir === "null_result") {
      flags.push(es ? "hallazgos mixtos" : "mixed findings");
    }
    if (nH === 1) flags.push(es ? "1 estudio humano" : "1 human study");
    else if (nH === 0 && (o.tier === "Emerging" || o.tier === "Preliminary")) flags.push(es ? "sin estudios humanos" : "no human studies");
    return flags;
  };
  const fillBackground = (o) => {
    const c = o.tierColor;
    if (o.tier === "Strong") return `linear-gradient(90deg, ${c}, ${c})`;
    if (o.tier === "Moderate") return `linear-gradient(90deg, ${c}, ${c})`;
    if (o.tier === "Emerging") return `repeating-linear-gradient(90deg, ${c} 0 10px, transparent 10px 16px)`;
    return `repeating-linear-gradient(90deg, ${c} 0 4px, transparent 4px 10px)`;
  };
  const fillShell = (o) => {
    const c = o.tierColor;
    if (o.tier === "Strong") return { background: `${c}18`, border: `1px solid ${c}33`, boxShadow: `0 0 18px ${c}2e` };
    if (o.tier === "Moderate") return { background: `${c}16`, border: `1px solid ${c}2c`, boxShadow: `0 0 14px ${c}24` };
    if (o.tier === "Emerging") return { background: `${c}0C`, border: `1px dashed ${c}40`, boxShadow: "none" };
    return { background: `${c}0A`, border: `1px dotted ${c}55`, boxShadow: "none" };
  };
  const sublabel = (o) => {
    const nH = (o.layers && o.layers.nHuman) || 0;
    const he = o.headlineEffect;
    const bits = [];
    if (nH > 0) bits.push(`${nH} ${es ? (nH === 1 ? "estudio humano" : "estudios humanos") : `${nH === 1 ? "human study" : "human studies"}`}`);
    if (he && he.value != null) bits.push(`${(he.metric || "SMD").toUpperCase()} ${he.value}`);
    else if (nH > 0) bits.push(es ? "sin tamaño combinado" : "no pooled size");
    return bits.join(" · ");
  };
  const counts = outcomes.reduce((m, o) => { m[o.tier] = (m[o.tier] || 0) + 1; return m; }, {});
  const countLine = ["Strong", "Moderate", "Emerging", "Preliminary"]
    .filter((t) => counts[t]).map((t) => `${counts[t]} ${tierLabel(t, lang).toUpperCase()}`).join(" · ");
  const top = rows[0];
  const topDetail = top ? findDetail(ex, top.outcome) : null;
  const topName = top ? (es ? (topDetail?.outcome_es || topDetail?.outcome || top.outcome) : top.outcome) : "";
  const summary = top
    ? (es
      ? `${cap(topName)} ${top.tier === "Strong" ? "supera el umbral de Fuerte. " : `lidera con nivel ${tierLabel(top.tier, lang)}. `}Las barras sólidas reflejan una base humana más asentada; las segmentadas, una señal más temprana.`
      : `${top.tier === "Strong" ? "Only " : ""}${cap(top.outcome)} ${top.tier === "Strong" ? "clears the bar for Strong. " : `leads at ${top.tier}. `}Solid fills reflect a more established human base; segmented fills signal earlier-stage evidence.`)
    : evidenceMapSummary(outcomes);

  return (
    <div style={{ padding: "4px 0 24px", marginBottom: 10, borderBottom:"1px solid rgba(255,255,255,.065)" }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
        <div style={{ fontSize: 14, fontWeight: 650, color: "#D6E0EC" }}>{es ? "Resultados ordenados por certeza" : "Outcomes ranked by evidence certainty"}</div>
        <div style={{ fontSize: 10.5, color: "#667893" }}>{outcomes.length} {es ? "resultados" : "outcomes"} · {countLine}</div>
      </div>
      <div style={{ color: "#A9B8CE", fontSize: 13.5, lineHeight: 1.62, marginBottom: 22, maxWidth: 760, textWrap: "pretty" }}>{summary}</div>

      <div className="evidence-axis" style={{ marginBottom: 12 }}>
        <span style={{ fontFamily:MONO,fontSize:9.5,letterSpacing:1,color:"#5E6E8A" }}>{es ? "TEMPRANO" : "EARLY"}</span>
        <span style={{ fontFamily:MONO,fontSize:9.5,letterSpacing:1,color:"#5E6E8A" }}>{tierLabel("Moderate", lang).toUpperCase()}</span>
        <span style={{ fontFamily:MONO,fontSize:9.2,letterSpacing:.9,color:"#5E6E8A", whiteSpace:"normal", lineHeight:1.25 }}>{es ? "MÁS ESTABLECIDO EN HUMANOS" : "MORE ESTABLISHED IN HUMANS"}</span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        {rows.map((o, i) => {
          const pct = pctFor(o);
          const shell = fillShell(o);
          const flags = qualityFlags(o);
          const detail = findDetail(ex, o.outcome);
          const outcomeLabel = es ? (detail?.outcome_es || detail?.outcome || o.outcome) : o.outcome;
          const dir = o.weighted && o.weighted.direction;
          const mixed = dir === "favors_control" || dir === "null_result";
          return (
            <div key={o.outcome} className="evidence-row">
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 16, fontWeight: 650, color: TEXT, textTransform: "capitalize", lineHeight: 1.2 }}>{cap(outcomeLabel)}</div>
                <div style={{ fontFamily: MONO, fontSize: 11, color: "#5E6E8A", marginTop: 4 }}>{sublabel(o)}</div>
                {flags.length ? (
                  <div style={{ display:"flex", flexWrap:"wrap", gap:6, marginTop:7 }}>
                    {flags.map((f) => <span key={f} style={{ fontFamily:MONO, fontSize:9.5, color:mixed?AMBER:MUTE, padding:"3px 7px", borderRadius:999, border:`1px solid ${mixed ? `${AMBER}55` : LINE}`, background:mixed ? `${AMBER}10` : "rgba(255,255,255,.03)" }}>{f}</span>)}
                  </div>
                ) : null}
              </div>
              <div style={{ position: "relative", height: 18, minWidth:0 }}>
                <div style={{ position: "absolute", inset: "2px 0", borderRadius: 999, background: "rgba(255,255,255,0.045)", border: "1px solid rgba(255,255,255,.03)" }} />
                <motion.div
                  initial={{ width: 0, opacity: 0.7 }} whileInView={{ width: `${pct}%`, opacity: 1 }} viewport={{ once: true }}
                  transition={{ delay: 0.04 + i * 0.08, duration: 0.78, ease: [0.22, 0.61, 0.36, 1] }}
                  style={{ position: "absolute", left: 0, top: 0, bottom: 0, borderRadius: 999, overflow: "hidden", ...shell }}>
                  <div style={{ position:"absolute", inset:0, background: fillBackground(o) }} />
                  {mixed ? <div style={{ position:"absolute", inset:0, background:`repeating-linear-gradient(135deg, transparent 0 7px, rgba(255,255,255,.18) 7px 10px)` }} /> : null}
                </motion.div>
                <motion.div initial={{ left: 0, opacity: 0 }} whileInView={{ left: `calc(${pct}% - 7px)`, opacity: 1 }} viewport={{ once: true }} transition={{ delay: 0.10 + i * 0.08, duration: 0.7, ease: [0.22, 0.61, 0.36, 1] }} style={{ position:"absolute", top:3, width:12, height:12, borderRadius:"50%", background:o.tierColor, boxShadow:`0 0 12px ${o.tierColor}66` }} />
              </div>
              <div className="evidence-tier-right">
                <div style={{ fontFamily: MONO, fontSize: 11, color: o.tierColor, letterSpacing: 0.5 }}>{tierLabel(o.tier, lang).toUpperCase()}</div>
                {o.weighted && o.weighted.score != null ? <div style={{ fontFamily: DISPLAY, fontSize: 10.5, color: MUTE, marginTop: 4 }}>{Math.round(o.weighted.score)}/100</div> : null}
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ borderTop: "1px solid rgba(255,255,255,0.07)", marginTop: 20, paddingTop: 14, display:"grid", gridTemplateColumns:"repeat(auto-fit,minmax(160px,1fr))", gap:10 }}>
        {[
          { k:"Strong", label: es ? "Fuerte" : "Strong", sample:`linear-gradient(90deg, ${TEAL}, ${TEAL})`, border:`1px solid ${TEAL}33` },
          { k:"Moderate", label: es ? "Moderada" : "Moderate", sample:`linear-gradient(90deg, ${AMBER}, ${AMBER})`, border:`1px solid ${AMBER}2c` },
          { k:"Emerging", label: es ? "Emergente" : "Emerging", sample:`repeating-linear-gradient(90deg, ${VIOLET} 0 10px, transparent 10px 16px)`, border:`1px dashed ${VIOLET}40` },
          { k:"Preliminary", label: es ? "Preliminar" : "Preliminary", sample:`repeating-linear-gradient(90deg, ${CORAL} 0 4px, transparent 4px 10px)`, border:`1px dotted ${CORAL}55` },
        ].map((it) => (
          <div key={it.k} style={{ display:"flex", alignItems:"center", gap:10, padding:"5px 0" }}>
            <div style={{ width:62, height:12, borderRadius:999, background:"rgba(255,255,255,.045)", position:"relative", overflow:"hidden", ...({ border: it.border }) }}>
              <div style={{ position:"absolute", inset:0, background:it.sample }} />
            </div>
            <div style={{ minWidth:0 }}>
              <div style={{ fontFamily:MONO, fontSize:10.5, color:TEXT }}>{it.label}</div>
              <div style={{ fontFamily:MONO, fontSize:9.5, color:MUTE }}>{it.k === "Strong" ? (es ? "base humana sólida" : "solid human-backed base") : it.k === "Moderate" ? (es ? "evidencia humana más limitada" : "meaningful but thinner human evidence") : it.k === "Emerging" ? (es ? "señal temprana" : "early-stage signal") : (es ? "evidencia muy delgada" : "very thin signal")}</div>
            </div>
          </div>
        ))}
      </div>
      <div style={{ fontFamily: MONO, fontSize: 10, color: "#5E6E8A", display:"flex", flexWrap:"wrap", gap: 14, marginTop: 12 }}>
        <span>{es ? "insignias ámbar = hallazgos mixtos o nulos" : "amber badge = mixed or null findings"}</span>
        <span>{es ? "insignias grises = un solo estudio humano o ninguno" : "gray badge = one human study or none"}</span>
      </div>
    </div>
  );
}

function findDetail(ex, outcome) {
  if (!ex || !ex.outcome_detail || !outcome) return null;
  const t = String(outcome).toLowerCase().trim();
  return ex.outcome_detail.find((d) => String(d.outcome_key || d.outcome || "").toLowerCase().trim() === t)
    || ex.outcome_detail.find((d) => String(d.outcome || "").toLowerCase().trim() === t)
    || null;
}

// Shared figure-direction mode + hovered-outcome across all outcome cards.
// mode: "stack"|"rings"|"ladder"; hover: [hoveredKey, setHoveredKey].
const FigureModeContext = React.createContext(["stack", () => {}]);
const HoverContext = React.createContext([null, () => {}]);

// Layer visualization — three drawing modes of the same human/animal/test-tube
// values. Empty animal layer renders as a dashed "none found" placeholder (honest).
function LayerViz({ mode, human, animal, mech, tc }) {
  const H = 172;
  const px = (v) => Math.max(10, Math.round((v / 100) * H));
  const hasAnimal = animal > 0;
  if (mode === "rings") {
    const ring = (r, val, color, dash, delay) => (
      <>
        <circle cx="50" cy="50" r={r} pathLength="100" fill="none" stroke={dash ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.07)"} strokeWidth="9" strokeDasharray={dash ? "3 4" : undefined} />
        {val > 0 ? (
          <circle cx="50" cy="50" r={r} pathLength="100" fill="none" stroke={color} strokeWidth="9" strokeLinecap="round"
            strokeDasharray={`${val} 100`} strokeDashoffset={val}
            style={{ animation: `ringDraw .9s ${delay}s cubic-bezier(.2,1,.3,1) both`, ["--dash"]: val }} />
        ) : null}
      </>
    );
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 20, height: H }}>
        <svg viewBox="0 0 100 100" style={{ width: 150, height: 150, transform: "rotate(-90deg)" }}>
          {ring(42, human, tc, false, 0.35)}
          {ring(30, animal, VIOLET, !hasAnimal, 0.2)}
          {ring(18, mech, "#6FA8F2", false, 0.05)}
        </svg>
        <div style={{ fontFamily: MONO, fontSize: 11, display: "flex", flexDirection: "column", gap: 9 }}>
          <span style={{ color: tc }}>outer · human {human}</span>
          <span style={{ color: hasAnimal ? VIOLET : "#6E7C97" }}>mid · animal {hasAnimal ? animal : "empty"}</span>
          <span style={{ color: "#6FA8F2" }}>core · test tube {mech}</span>
        </div>
      </div>
    );
  }
  if (mode === "ladder") {
    const rung = (label, val, color, ml, dashed) => (
      <div style={{ marginLeft: ml }}>
        <div style={{ fontFamily: MONO, fontSize: 10, color: color, marginBottom: 4 }}>{label}</div>
        {dashed ? (
          <div style={{ height: 14, borderRadius: 7, border: `1.5px dashed rgba(154,140,245,0.45)`, background: "repeating-linear-gradient(135deg,rgba(154,140,245,0.1) 0 4px,transparent 4px 9px)" }} />
        ) : (
          <div style={{ height: val > 60 ? 18 : 14, borderRadius: 9, background: "rgba(255,255,255,0.05)", overflow: "hidden" }}>
            <div style={{ width: `${val}%`, height: "100%", borderRadius: 9, background: color, transformOrigin: "left", animation: "growbar .7s both" }} />
          </div>
        )}
      </div>
    );
    return (
      <div style={{ display: "flex", flexDirection: "column-reverse", gap: 10, height: H, justifyContent: "center" }}>
        {rung("TEST TUBE " + mech, mech, "#6FA8F2", 0, false)}
        {hasAnimal ? rung("ANIMAL " + animal, animal, VIOLET, 14, false) : rung("ANIMAL — RUNG SKIPPED", 0, "#6E7C97", 14, true)}
        {rung("HUMAN " + human + (human >= 85 ? " · TOP RUNG REACHED" : ""), human, tc, 28, false)}
      </div>
    );
  }
  // default: stack
  const emptyBlock = (h, label) => (
    <div style={{ height: h, borderRadius: 6, border: "1.5px dashed rgba(255,255,255,0.18)", background: "repeating-linear-gradient(135deg,rgba(255,255,255,0.04) 0 4px,transparent 4px 9px)", display: "grid", placeItems: "center" }}>
      <span style={{ fontFamily: MONO, fontSize: 8.5, color: "#6E7C97" }}>{label}</span>
    </div>
  );
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 18, height: H }}>
      <div style={{ display: "flex", flexDirection: "column", justifyContent: "flex-end", gap: 4, width: 76, height: H }}>
        {human > 0 ? (
          <div style={{ height: px(human), borderRadius: "8px 8px 3px 3px", background: `linear-gradient(180deg,${tc},${tc}99)`, transformOrigin: "bottom", animation: "growY .85s .45s cubic-bezier(.2,1.1,.3,1.04) both", boxShadow: `0 0 26px ${tc}4D` }} />
        ) : emptyBlock(24, "none")}
        {animal > 0 ? (
          <div style={{ height: px(animal), borderRadius: 3, background: "linear-gradient(180deg,#9A8CF5,#6455C4)", transformOrigin: "bottom", animation: "growY .85s .25s cubic-bezier(.2,1.1,.3,1.04) both" }} />
        ) : emptyBlock(24, "none")}
        {mech > 0 ? (
          <div style={{ height: px(mech), borderRadius: "0 0 8px 8px", background: "linear-gradient(180deg,#6FA8F2,#3B6FB0)", transformOrigin: "bottom", animation: "growY .85s .05s cubic-bezier(.2,1.1,.3,1.04) both" }} />
        ) : emptyBlock(24, "none")}
      </div>
      <div style={{ display: "flex", flexDirection: "column", justifyContent: "flex-end", gap: 4, height: H, fontFamily: MONO, fontSize: 11 }}>
        <div style={{ height: human > 0 ? px(human) : 24, display: "flex", alignItems: "center", color: human > 0 ? tc : "#6E7C97" }}>human · {human > 0 ? human : "none"}</div>
        <div style={{ height: animal > 0 ? px(animal) : 24, display: "flex", alignItems: "center", color: animal > 0 ? VIOLET : "#6E7C97" }}>animal · {animal > 0 ? animal : "none"}</div>
        <div style={{ height: mech > 0 ? px(mech) : 24, display: "flex", alignItems: "center", color: mech > 0 ? "#6FA8F2" : "#6E7C97" }}>test tube · {mech > 0 ? mech : "none"}</div>
      </div>
    </div>
  );
}

// Forest-plot CI bar (the "how big, how sure" figure), or an honest empty state.
function EffectFigure({ eff, tc }) {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  if (!eff || eff.value == null || eff.ciLow == null || eff.ciHigh == null) {
    return (
      <div style={{ maxWidth: 400, borderRadius: 12, border: "1.5px dashed rgba(255,255,255,0.18)", background: "repeating-linear-gradient(135deg,rgba(255,255,255,0.035) 0 6px,transparent 6px 13px)", padding: "18px 0" }}>
        <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: 1.2, color: "#8B9AB6", marginBottom: 7 }}>{es ? "SIN TAMAÑO DE EFECTO COMBINADO" : "NO POOLED EFFECT SIZE"}</div>
        <div style={{ fontSize: 13.5, lineHeight: 1.65, color: "#A9B8CE", textWrap: "pretty" }}>{es ? "Los estudios no informan cifras que podamos combinar legítimamente, así que no hay una barra que dibujar. Dejamos el espacio vacío en lugar de inventar una." : "The studies don't report numbers we can legitimately pool, so there is no bar to draw. We leave the space empty rather than invent one."}</div>
      </div>
    );
  }
  const nullV = effectNullValue(eff.metric);
  const lo = eff.ciLow, hi = eff.ciHigh, val = eff.value;
  const spread = Math.max(Math.abs(hi - lo), Math.abs(val - nullV), 0.1);
  const axMin = Math.min(nullV, lo, val) - spread * 0.25;
  const axMax = Math.max(nullV, hi, val) + spread * 0.25;
  const X = (v) => 30 + ((v - axMin) / Math.max(1e-9, axMax - axMin)) * 315;
  return (
    <div>
      <svg viewBox="0 0 360 84" style={{ width: "100%", maxWidth: 400 }} role="img" aria-label={`Effect ${val}; 95% CI ${lo} to ${hi}; no-effect value ${nullV}`}>
        <line x1="30" y1="52" x2="345" y2="52" stroke="rgba(255,255,255,0.12)" strokeWidth="1" />
        <line x1={X(nullV)} y1="24" x2={X(nullV)} y2="66" stroke="#F07D74" strokeWidth="1.5" strokeDasharray="4 4" />
        <text x={X(nullV)} y="16" fill="#F07D74" fontSize="10" textAnchor="middle" fontFamily="JetBrains Mono">{es ? "sin efecto" : "no effect"} · {nullV}</text>
        <rect x={X(lo)} y="47" width={Math.max(2, X(hi) - X(lo))} height="10" rx="5" fill={`${tc}47`} style={{ animation: "growbar .9s .3s both", transformOrigin: "center" }} />
        <line x1={X(lo)} y1="40" x2={X(lo)} y2="64" stroke={tc} strokeWidth="2" />
        <line x1={X(hi)} y1="40" x2={X(hi)} y2="64" stroke={tc} strokeWidth="2" />
        <circle cx={X(val)} cy="52" r="7" fill={tc} style={{ animation: "fadeUp .5s .9s both" }} />
        <text x={X(lo)} y="79" fill="#8B9AB6" fontSize="10" textAnchor="middle" fontFamily="JetBrains Mono">{lo}</text>
        <text x={X(val)} y="34" fill={tc} fontSize="12" textAnchor="middle" fontFamily="JetBrains Mono">{val}</text>
        <text x={X(hi)} y="79" fill="#8B9AB6" fontSize="10" textAnchor="middle" fontFamily="JetBrains Mono">{hi}</text>
      </svg>
      <div style={{ fontSize: 12, color: "#8B9AB6", lineHeight: 1.5, marginTop: 3 }}>{effectPrecisionText(eff, lang)}{eff.estimated ? (es ? " · precisión del IC estimada" : " · CI precision estimated") : ""}.</div>
    </div>
  );
}

function OutcomeGraphicCard({ o, detail }) {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  const [mode] = React.useContext(FigureModeContext);
  const [hovered, setHovered] = React.useContext(HoverContext);
  const tc = o.tierColor;
  const L = o.layers;
  const eff = o.headlineEffect;
  const detailText = (detail && detail.what_studies_show) || (es && o.summary_es) || o.summary || (o.reasons && o.reasons[0]) || plainTier(o.tier, o.hasHuman, lang);
  const displayOutcome = es ? (detail?.outcome_es || detail?.outcome_label || detail?.outcome || o.outcome) : o.outcome;
  const dimmed = hovered && hovered !== o.outcome;
  const layerItems = [
    { k:es?"SEÑAL MECANÍSTICA":"LAB / MECHANISM", score:L.mechanistic, count:null, color:"#5FA8F5", meaning:es?"plausibilidad biológica":"biological plausibility" },
    { k:es?"EVIDENCIA ANIMAL":"ANIMAL EVIDENCE", score:L.nAnimal>0?L.preclinical:0, count:L.nAnimal||0, color:VIOLET, meaning:es?"apoyo preclínico":"preclinical support" },
    { k:es?"EVIDENCIA HUMANA":"HUMAN EVIDENCE", score:L.human, count:L.nHuman||0, color:TEAL, meaning:es?"evidencia directa en personas":"direct evidence in people" },
  ];
  const factItems = [];
  if (o.nStudies) factItems.push({ label:es?"ESTUDIOS CALIFICADOS":"STUDIES GRADED", value:o.nStudies, note:es?"para este resultado":"for this outcome" });
  if (eff && eff.value != null) factItems.push({ label:es?"EFECTO ESTIMADO":"ESTIMATED EFFECT", value:eff.value, note:`${String(eff.metric||"SMD").replaceAll("_"," ")} · ${eff.ciLow!=null?`95% CI ${eff.ciLow}–${eff.ciHigh}`:(es?"IC no disponible":"CI unavailable")}` });
  if (o.weighted && o.weighted.score != null) factItems.push({ label:es?"FUERZA DE EVIDENCIA":"EVIDENCE STRENGTH", value:`${Math.round(o.weighted.score)}/100`, note:es?"no es probabilidad de beneficio":"not probability of benefit" });
  if (L.nHuman || L.nAnimal) factItems.push({ label:es?"POBLACIÓN":"POPULATION", value:L.nHuman?`${L.nHuman} ${es?"humanos":"human"}`:`${L.nAnimal||0} ${es?"animales":"animal"}`, note:L.nHuman&&L.nAnimal?`${L.nAnimal} ${es?"animales adicionales":"animal studies too"}`:(L.nHuman? (es?"evidencia directa en personas":"direct human evidence") : (es?"sin estudios humanos":"no human studies")) });
  if (o.preprintsExcluded) factItems.push({ label:es?"PREPRINTS EXCLUIDOS":"PREPRINTS EXCLUDED", value:o.preprintsExcluded, note:es?"visibles en búsqueda, no elevan el nivel":"discovery only; do not raise the tier" });
  const direction = o.weighted && o.weighted.direction;
  const directionLabel = direction === "favors_control" ? (es?"desfavorable":"unfavorable") : direction === "null_result" ? (es?"sin beneficio claro":"no clear benefit") : direction === "favors_treatment" ? (es?"favorece tratamiento":"favors treatment") : null;

  return (
    <motion.article layout onMouseEnter={()=>setHovered(o.outcome)} onMouseLeave={()=>setHovered(null)} initial={{ opacity:0, y:12 }} animate={{ opacity:dimmed ? 0.48 : 1, y:hovered===o.outcome?-2:0 }} transition={MOTION_SPRING} style={{ borderRadius:16, marginBottom:22, overflow:"hidden", background:"rgba(255,255,255,.014)", borderTop:`1px solid ${o.tier==="Strong"?"rgba(52,224,190,.26)":o.tier==="Moderate"?"rgba(245,181,68,.24)":"rgba(255,255,255,.10)"}`, borderBottom:"1px solid rgba(255,255,255,.055)" }}>
      <div style={{ display:"flex", justifyContent:"space-between", gap:14, alignItems:"flex-start", flexWrap:"wrap", padding:"20px 22px 16px", borderBottom:"1px solid rgba(255,255,255,.065)" }}>
        <div style={{ minWidth:0 }}><div style={{ display:"flex", alignItems:"center", gap:9, flexWrap:"wrap" }}><h2 style={{ margin:0, fontSize:25, fontWeight:700, letterSpacing:-.8, textTransform:"capitalize" }}>{displayOutcome}</h2>{directionLabel ? <span style={{ fontFamily:MONO, fontSize:9.5, color:direction==="favors_treatment"?TEAL:AMBER, padding:"3px 7px", borderRadius:999, background:direction==="favors_treatment"?`${TEAL}0D`:`${AMBER}0D`, border:`1px solid ${direction==="favors_treatment"?`${TEAL}35`:`${AMBER}35`}` }}>{directionLabel}</span> : null}</div><div style={{ fontSize:13.5, color:"#A9B8CE", lineHeight:1.55, marginTop:7, maxWidth:720, textWrap:"pretty" }}>{detailText}</div></div>
        <div style={{ display:"flex", alignItems:"center", gap:9 }}>{o.weighted&&o.weighted.score!=null?<span style={{ fontFamily:MONO, fontSize:10.5, color:MUTE }}>{Math.round(o.weighted.score)}/100</span>:null}<span style={{ padding:"5px 12px", borderRadius:999, background:`${tc}15`, border:`1px solid ${tc}88`, color:tc, fontFamily:MONO, fontSize:10.5, fontWeight:650, letterSpacing:.55 }}>{String(tierLabel(o.tier,lang)).toUpperCase()}</span></div>
      </div>

      <div style={{ margin:"14px 22px 0", padding:"13px 0 2px", display:"flex", gap:11, alignItems:"flex-start" }}>
        <div style={{ width:26, height:26, borderRadius:8, background:`${tc}10`, display:"grid", placeItems:"center", flexShrink:0 }}><Sparkles size={14} color={tc}/></div>
        <div>
          <div style={{ fontFamily:MONO, fontSize:9.3, letterSpacing:1.1, color:tc, marginBottom:5 }}>{es?"EN LENGUAJE CLARO":"IN PLAIN ENGLISH"}</div>
          <div style={{ fontSize:13.4, lineHeight:1.64, color:"#C4D0DF", textWrap:"pretty" }}>{consumerEvidenceSummary(o, lang)}</div>
        </div>
      </div>

      {(["failed","unavailable","unclear"].includes(o.directionStatus) && (o.tier === "Strong" || o.tier === "Moderate")) ? <div style={{ margin:"10px 20px 0", padding:"9px 11px", borderRadius:10, background:`${AMBER}08`, border:`1px solid ${AMBER}25`, fontFamily:MONO, fontSize:9.5, lineHeight:1.5, color:"#B89451" }}>{es?"La dirección del efecto no pudo verificarse de forma concluyente; el nivel superior se retiene de manera conservadora.":"Effect direction could not be verified conclusively; the top tier is conservatively withheld."}</div> : null}

      <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit,minmax(320px,1fr))", gap:0 }}>
        <div style={{ padding:"19px 20px 20px", borderRight:"1px solid rgba(255,255,255,.055)" }}>
          <div style={{ fontFamily:MONO, fontSize:9.5, color:"#667893", letterSpacing:1.2, marginBottom:11 }}>{es?"CAPAS DE EVIDENCIA":"EVIDENCE LAYERS"}</div>
          <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", marginBottom:14, borderTop:"1px solid rgba(255,255,255,.055)", borderBottom:"1px solid rgba(255,255,255,.055)" }}>{layerItems.map((it,idx)=><div key={it.k} style={{ padding:"11px 10px 10px", borderRight:idx<2?"1px solid rgba(255,255,255,.055)":"none" }}><div style={{ fontSize:9.5, color:"#667893", marginBottom:5, fontWeight:600 }}>{it.k}</div><div style={{ display:"flex", alignItems:"baseline", gap:5 }}><span style={{ fontFamily:MONO, fontSize:18, color:it.color, fontWeight:650 }}>{it.score}</span><span style={{ fontFamily:MONO, fontSize:8.5, color:MUTE }}>/100</span><span style={{ fontSize:9.5, color:it.color, marginLeft:"auto" }}>{layerDescriptor(it.score,lang)}</span></div><div style={{ fontSize:9.7, color:MUTE, marginTop:4 }}>{it.meaning}{it.count!==null?` · ${it.count} ${es?"estudios":"studies"}`:""}</div></div>)}</div>
          <div style={{ padding:"10px 4px 4px" }}><LayerViz key={mode} mode={mode} human={L.human} animal={L.nAnimal>0?L.preclinical:0} mech={L.mechanistic} tc={tc}/></div>
        </div>
        <div style={{ padding:"19px 20px 20px", minWidth:0 }}>
          <div style={{ fontFamily:MONO, fontSize:9.5, color:"#667893", letterSpacing:1.2, marginBottom:11 }}>{es?"LECTURA RÁPIDA":"QUICK READ"}</div>
          <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit,minmax(145px,1fr))", columnGap:18, rowGap:0, marginBottom:13, borderTop:"1px solid rgba(255,255,255,.055)" }}>{factItems.map((f,i)=><div key={i} style={{ padding:"11px 1px 12px", borderBottom:"1px solid rgba(255,255,255,.055)" }}><div style={{ fontSize:9.2, fontWeight:600, color:"#667893", marginBottom:6 }}>{f.label}</div><div style={{ fontFamily:MONO, fontSize:13, color:tc, fontWeight:600 }}>{f.value}</div><div style={{ fontSize:10.5, lineHeight:1.35, color:MUTE, marginTop:4 }}>{f.note}</div></div>)}</div>
          <EvidenceComposition studies={o.studies} color={tc}/>
          {detail&&detail.what_studies_show? <div style={{ marginTop:14, paddingTop:13, borderTop:"1px solid rgba(255,255,255,.06)" }}><div style={{ fontFamily:MONO, fontSize:9.2, letterSpacing:1.05, color:"#667893", marginBottom:6 }}>{es?"LO QUE MUESTRAN LOS ESTUDIOS":"WHAT THE STUDIES SHOW"}</div><div style={{ fontSize:13.3, lineHeight:1.65, color:"#A9B8CE", textWrap:"pretty" }}>{detail.what_studies_show}</div></div>:null}
          {eff&&eff.value!=null? <div style={{ marginTop:14, paddingTop:13, borderTop:"1px solid rgba(255,255,255,.06)" }}><div style={{ display:"flex", justifyContent:"space-between", gap:8, flexWrap:"wrap", alignItems:"baseline", marginBottom:8 }}><div style={{ fontFamily:MONO, fontSize:9.2, letterSpacing:1.05, color:"#667893" }}>{es?"EFECTO Y PRECISIÓN":"EFFECT & PRECISION"}</div><div style={{ fontFamily:MONO, fontSize:9.5, color:MUTE }}>{(eff.metric||"SMD").toUpperCase()} {eff.value}{eff.ciLow!=null?` · 95% CI ${eff.ciLow}–${eff.ciHigh}`:""}</div></div><EffectFigure key={mode} eff={eff} tc={tc} mode={mode}/></div>:null}
          {detail&&detail.why_this_grade? <div style={{ marginTop:14, paddingTop:13, borderTop:"1px solid rgba(255,255,255,.06)" }}><div style={{ fontFamily:MONO, fontSize:9.2, letterSpacing:1.05, color:"#667893", marginBottom:6 }}>{es?"POR QUÉ ESTA CALIFICACIÓN":"WHY THIS GRADE"}</div><div style={{ fontSize:13.2, lineHeight:1.62, color:"#A9B8CE", textWrap:"pretty" }}>{detail.why_this_grade}</div></div>:null}
          <div style={{ marginTop:14, paddingTop:12, borderTop:"1px solid rgba(255,255,255,.06)" }}><StudyToggle pmids={o.pmids} studies={o.studies} nStudies={o.nStudies} outcome={displayOutcome} direction={direction}/></div>
        </div>
      </div>
    </motion.article>
  );
}

// Figure-direction switcher — sets the shared mode for all cards below.
function FigureSwitcher() {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  const [mode, setMode] = React.useContext(FigureModeContext);
  const opts = es ? [
    ["stack", "Capas", "apiladas"],
    ["rings", "Anillos", "concéntricos"],
    ["ladder", "Escalera", "por etapas"],
  ] : [
    ["stack", "Layers", "stacked"],
    ["rings", "Rings", "nested"],
    ["ladder", "Ladder", "staged"],
  ];
  return (
    <div style={{ display:"flex", flexWrap:"wrap", justifyContent:"space-between", alignItems:"center", gap:12, padding:"12px 0 14px", borderTop:"1px solid rgba(255,255,255,.06)", borderBottom:"1px solid rgba(255,255,255,.06)", margin:"4px 0 18px" }}>
      <div style={{ fontSize:11.5, color:MUTE, lineHeight:1.45 }}>{es ? "Mismos datos, tres vistas." : "Same evidence, three views."}</div>
      <div role="group" aria-label={es?"Vista de capas de evidencia":"Evidence-layer view"} style={{ display:"inline-flex", alignItems:"center", gap:2, padding:3, borderRadius:10, background:"rgba(255,255,255,.025)" }}>
        {opts.map(([key,label,sub])=><button key={key} onClick={()=>setMode(key)} aria-pressed={mode===key} title={sub} style={{ border:0, cursor:"pointer", background:mode===key?"rgba(52,224,190,.10)":"transparent", color:mode===key?TEAL:MUTE, borderRadius:8, padding:"7px 10px", fontSize:11.5, fontWeight:mode===key?650:500 }}>{label}</button>)}
      </div>
    </div>
  );
}

function StudyToggle({ pmids, studies, nStudies, outcome, direction }) {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("strength");
  const records = Array.isArray(studies) ? studies : [];
  const ids = (pmids || []).map((pid) => String(pid));
  const idHref = (id) => {
    const raw = String(id || "");
    if (raw.startsWith("PMID:")) return `https://pubmed.ncbi.nlm.nih.gov/${raw.slice(5)}/`;
    if (raw.startsWith("DOI:")) return `https://doi.org/${raw.slice(4)}`;
    if (raw.startsWith("EPMC:")) { const v = raw.slice(5); const [src, ...rest] = v.split(":"); const eid = rest.join(":"); return eid ? `https://europepmc.org/article/${String(src).toUpperCase()}/${eid}` : null; }
    return /^\d+$/.test(raw) ? `https://pubmed.ncbi.nlm.nih.gov/${raw}/` : null;
  };
  const strengthRank = (d) => {
    const x=String(d||"").toLowerCase();
    if (x.includes("meta")) return 6;
    if (x.includes("systematic")) return 5;
    if (x === "rct" || x.includes("random")) return 4;
    if (x.includes("clinical")) return 3;
    if (x.includes("observ")) return 2;
    if (x.includes("animal")) return 1;
    return 0;
  };
  const visibleRecords = useMemo(() => {
    let rows=[...records];
    if (filter === "human") rows=rows.filter((r)=>String(r.population||"").toLowerCase()==="human");
    if (filter === "animal") rows=rows.filter((r)=>String(r.population||"").toLowerCase()==="animal");
    if (filter === "synthesis") rows=rows.filter((r)=>/meta|systematic/i.test(String(r.design||"")));
    if (filter === "rct") rows=rows.filter((r)=>/rct|random/i.test(String(r.design||"")));
    rows.sort((a,b)=> sort === "newest"
      ? (Number(b.year)||0)-(Number(a.year)||0)
      : strengthRank(b.design)-strengthRank(a.design) || (Number(b.year)||0)-(Number(a.year)||0));
    return rows;
  }, [records, filter, sort]);
  const directionText = direction === "favors_treatment" ? (es?"favorece tratamiento":"favors treatment") : direction === "null_result" ? (es?"sin beneficio claro":"no clear benefit") : direction === "favors_control" ? (es?"favorece control":"favors control") : (es?"dirección no verificada":"direction not verified");
  if (!ids.length && !records.length) return <span style={{ color: MUTE }}>{nStudies} {es ? "estudios revisados" : "studies reviewed"}</span>;
  return (
    <div>
      <button onClick={() => setOpen(!open)} aria-expanded={open}
        style={{ background: "transparent", border: "none", padding: 0, color: "#78BDF8", cursor: "pointer", fontFamily: DISPLAY, fontSize: 13, fontWeight:600 }}>
        {open ? (es ? "Ocultar matriz de estudios" : "Hide study matrix") : (es ? `Examinar ${records.length || ids.length} estudios` : `Inspect ${records.length || ids.length} studies`)} <span aria-hidden="true">{open?"↑":"↓"}</span>
      </button>
      {open && (
        <div style={{ marginTop: 12, borderTop: `1px solid rgba(255,255,255,.075)`, paddingTop:14 }}>
          <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", gap:12, flexWrap:"wrap", marginBottom:12 }}>
            <div style={{ fontSize:11.5, color:MUTE, lineHeight:1.5 }}>
              <span style={{color:TEXT,fontWeight:650,textTransform:"capitalize"}}>{outcome || (es?"Resultado":"Outcome")}</span>
              <span style={{color:"#44536A",padding:"0 7px"}}>·</span>{directionText}
              <span style={{color:"#44536A",padding:"0 7px"}}>·</span>{visibleRecords.length}/{records.length} {es?"estudios visibles":"studies shown"}
            </div>
            <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
              {[["all",es?"Todos":"All"],["human",es?"Humanos":"Human"],["rct","RCT"],["synthesis",es?"Síntesis":"Synthesis"],["animal",es?"Animal":"Animal"]].map(([k,l])=><button key={k} onClick={()=>setFilter(k)} aria-pressed={filter===k} style={{border:0,borderBottom:`1px solid ${filter===k?TEAL:"transparent"}`,background:"transparent",color:filter===k?TEAL:MUTE,padding:"5px 3px",cursor:"pointer",fontSize:10.5,fontWeight:600}}>{l}</button>)}
              <span style={{width:1,background:LINE,margin:"2px 3px"}}/>
              <button onClick={()=>setSort(sort==="strength"?"newest":"strength")} style={{border:0,background:"transparent",color:MUTE,padding:"5px 3px",cursor:"pointer",fontSize:10.5}}>{sort==="strength"?(es?"Mejor diseño":"Best design"):(es?"Más recientes":"Newest")} ↕</button>
            </div>
          </div>
          {records.length ? (
            <div style={{overflowX:"auto"}}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 720, fontSize: 12.5 }}>
              <thead>
                <tr style={{ color: MUTE, fontSize: 10, letterSpacing: 0.15 }}>
                  {(es ? ['Estudio', 'Diseño', 'Población', 'N', 'Año', 'Fuente'] : ['Study', 'Design', 'Population', 'N', 'Year', 'Source']).map((h) => <th key={h} style={{ textAlign: "left", fontWeight:600, padding: "9px 10px", borderBottom: `1px solid rgba(255,255,255,.09)` }}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {visibleRecords.map((st, i) => {
                  const sourceId = st.pmid ? `PMID:${st.pmid}` : (st.doi ? `DOI:${st.doi}` : (st.epmc_id ? `EPMC:${st.epmc_id}` : ids[i] || st.id || ""));
                  const href = st.url || idHref(sourceId);
                  const sourceLabel = st.pmid ? `PMID ${st.pmid}` : st.doi ? "DOI" : st.epmc_id ? "Europe PMC" : "—";
                  return (
                    <tr key={sourceId || i} style={{ borderBottom: i < visibleRecords.length - 1 ? `1px solid rgba(255,255,255,0.045)` : "none" }}>
                      <td style={{ padding: "12px 10px", maxWidth: 390 }}>
                        {href ? <a href={href} target="_blank" rel="noreferrer" style={{ color: "#D4DFEC", textDecoration: "none", lineHeight: 1.4 }}>{st.title || sourceId} <span style={{ color: "#78BDF8" }}>↗</span></a> : <span>{st.title || (es ? "Estudio sin título" : "Untitled study")}</span>}
                      </td>
                      <td style={{ padding: "12px 10px", color: "#A9B8CE" }}>{st.design || "—"}</td>
                      <td style={{ padding: "12px 10px", color: "#A9B8CE", textTransform: "capitalize" }}>{st.population || "—"}</td>
                      <td style={{ padding: "12px 10px", color: st.n ? TEXT : MUTE, fontFamily: MONO }}>{st.n ?? "—"}</td>
                      <td style={{ padding: "12px 10px", color: "#A9B8CE", fontFamily: MONO }}>{st.year || "—"}</td>
                      <td style={{ padding: "12px 10px" }}>{href?<a href={href} target="_blank" rel="noreferrer" style={{color:"#78BDF8",textDecoration:"none",fontSize:10.5}}>{sourceLabel}</a>:<span style={{color:MUTE}}>—</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table></div>
          ) : (
            <div style={{ padding: "10px 0", display: "flex", flexWrap: "wrap", gap: 6 }}>
              {ids.map((id) => { const href=idHref(id); return href ? <a key={id} href={href} target="_blank" rel="noreferrer" style={{ fontFamily: MONO, fontSize: 11, color: "#78BDF8", textDecoration: "none", borderBottom: `1px solid rgba(120,189,248,.35)`, padding: "3px 2px" }}>{id.replace(/^PMID:/,"")}</a> : <span key={id} style={{fontFamily:MONO,fontSize:11,color:MUTE}}>{id}</span>; })}
            </div>
          )}
          <div style={{ paddingTop: 9, borderTop: `1px solid rgba(255,255,255,.06)`, fontSize: 10.5, color: "#667893", lineHeight:1.5 }}>
            {es ? "Los tamaños de muestra faltantes se muestran como — porque el resumen no los verificó; Clarity no adivina. La dirección mostrada arriba corresponde al resultado completo, no a cada estudio individual." : "Missing sample sizes are shown as — because the abstract did not verify them; Clarity does not guess. Direction above is the outcome-level assessment, not a study-by-study label."}
          </div>
        </div>
      )}
    </div>
  );
}

// "How certain is certain — read the texture, not the word." Each tier gets a
// DISTINCT visual treatment so the reader learns evidence strength from the
// texture, not just the label: Strong fills solid, Moderate part-way, Emerging
// is dashed/hatched and deliberately doesn't fill, Preliminary is dotted.
function TextureLegend() {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  const items = [
    { label: "Strong", color: TEAL, note: es ? "evidencia humana consistente" : "consistent human evidence", sample:`linear-gradient(90deg,${TEAL},${TEAL})`, border:`1px solid ${TEAL}44` },
    { label: "Moderate", color: AMBER, note: es ? "evidencia humana útil, más limitada" : "meaningful but thinner human evidence", sample:`linear-gradient(90deg,${AMBER},${AMBER})`, border:`1px solid ${AMBER}3C` },
    { label: "Emerging", color: VIOLET, note: es ? "señal temprana o todavía incierta" : "early or still unsettled signal", sample:`repeating-linear-gradient(90deg,${VIOLET} 0 8px,transparent 8px 13px)`, border:`1px dashed ${VIOLET}55` },
    { label: "Preliminary", color: CORAL, note: es ? "evidencia muy temprana / preclínica" : "very early / preclinical evidence", sample:`repeating-linear-gradient(90deg,${CORAL} 0 3px,transparent 3px 8px)`, border:`1px dotted ${CORAL}66` },
  ];
  return (
    <div style={{ margin:"4px 0 26px", padding:"13px 0 15px", borderTop:"1px solid rgba(255,255,255,.065)", borderBottom:"1px solid rgba(255,255,255,.065)" }}>
      <div style={{ display:"flex", alignItems:"baseline", justifyContent:"space-between", gap:12, flexWrap:"wrap", marginBottom:12 }}>
        <div style={{ fontSize:12.5, fontWeight:650, color:"#C7D2E1" }}>{es ? "Cómo leer la certeza" : "How to read certainty"}</div>
        <div style={{ fontSize:10.5, color:MUTE }}>{es ? "El color y la textura significan lo mismo en toda la página." : "Color and texture mean the same thing throughout the page."}</div>
      </div>
      <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit,minmax(180px,1fr))", gap:"10px 18px" }}>
        {items.map((it)=><div key={it.label} style={{minWidth:0}}>
          <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:5}}><span style={{width:48,height:8,borderRadius:999,background:"rgba(255,255,255,.035)",position:"relative",overflow:"hidden",border:it.border}}><span style={{position:"absolute",inset:0,background:it.sample}}/></span><span style={{fontSize:12,fontWeight:650,color:it.color}}>{tierLabel(it.label,lang)}</span></div>
          <div style={{fontSize:10.5,color:MUTE,lineHeight:1.4,paddingLeft:56}}>{it.note}</div>
        </div>)}
      </div>
    </div>
  );
}

// "Where to buy" — a DISCLOSED affiliate link. Honest by construction: it shows
// the compound's real tier right next to the buy button (the grade travels with
// the link), frames it as "if you've decided to try this" rather than a
// recommendation, and discloses the commission plainly (FTC-required and
// trust-building). The affiliate relationship never changes the grade.
const AFFILIATE = {
  base: "https://aminoclub.com",
  params: "utm_source=affiliate_marketing&code=JORGE05",
  supplier: "Amino Club",
};
function buildAffiliateUrl(name) {
  // A search/deep link to the supplier with the affiliate code attached.
  const q = encodeURIComponent(name || "");
  return `${AFFILIATE.base}/?${AFFILIATE.params}&q=${q}`;
}
function WhereToBuy({ name, tier, tierColor, category }) {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  // Only shown for peptides (the affiliate supplier's catalog). Adjust the
  // gate if the supplier carries other categories.
  const isPeptide = (category || "").toLowerCase() === "peptide";
  if (!isPeptide) return null;
  const weak = tier === "Preliminary" || tier === "Emerging";
  return (
    <div style={{ marginTop: 34, borderRadius: 18, border: `1px solid ${LINE}`, background: "rgba(255,255,255,0.02)", overflow: "hidden" }}>
      <div style={{ padding: "18px 22px" }}>
        <div style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: 1.5, color: MUTE, marginBottom: 10 }}>{es ? "DÓNDE COMPRAR" : "WHERE TO BUY"}</div>

        {/* The grade travels with the link — honesty guardrail. */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 12 }}>
          <span style={{ fontSize: 14.5, color: TEXT }}>{es ? `Calificación de Clarity para ${name}:` : `Clarity's grade for ${name}:`}</span>
          <span style={{ padding: "3px 11px", borderRadius: 14, background: `${tierColor}22`, border: `1px solid ${tierColor}`, color: tierColor, fontSize: 12, fontWeight: 600 }}>{String(tierLabel(tier, lang)).toUpperCase()}</span>
        </div>

        {/* Honest framing — especially for weak-evidence compounds. */}
        <div style={{ fontSize: 13.5, lineHeight: 1.65, color: "#A9B8CE", marginBottom: 16, maxWidth: 620, textWrap: "pretty" }}>
          {weak
            ? (es ? `La evidencia humana para ${name} es limitada (consulta la calificación de arriba). Si, sabiendo eso, decidiste probarlo, este es un proveedor con el que colaboramos; comprar mediante este enlace ayuda a mantener Clarity sin costo adicional para ti.` : `The human evidence for ${name} is limited (see the grade above). If, knowing that, you've decided to try it, this is a supplier we've partnered with — buying through this link helps support Clarity at no extra cost to you.`)
            : (es ? `Si decidiste probar ${name}, este es un proveedor con el que colaboramos. Comprar mediante este enlace ayuda a mantener Clarity sin costo adicional para ti.` : `If you've decided to try ${name}, this is a supplier we've partnered with. Buying through this link helps support Clarity at no extra cost to you.`)}
        </div>

        <a href={buildAffiliateUrl(name)} target="_blank" rel="noreferrer nofollow sponsored"
          style={{ display: "inline-flex", alignItems: "center", gap: 8, background: TEAL, color: INK, fontWeight: 700, fontSize: 14, padding: "11px 20px", borderRadius: 11, textDecoration: "none" }}>
          {es ? `Comprar ${name} en ${AFFILIATE.supplier}` : `Shop ${name} at ${AFFILIATE.supplier}`} ↗
        </a>
      </div>

      {/* Disclosure — FTC-required, and it builds trust. */}
      <div style={{ padding: "11px 22px", background: "rgba(255,255,255,0.02)", borderTop: `1px solid ${LINE}`, fontFamily: MONO, fontSize: 10, lineHeight: 1.6, color: "#5E6E8A" }}>
        {es ? "DIVULGACIÓN DE AFILIADO: Clarity recibe una comisión si compras mediante este enlace. Esto nunca afecta cómo calificamos un compuesto; la calificación de evidencia anterior es independiente de cualquier relación comercial. No es consejo médico." : "AFFILIATE DISCLOSURE: Clarity earns a commission if you buy through this link. This never affects how we grade a compound — the evidence rating above is independent of any commercial relationship. Not medical advice."}
      </div>
    </div>
  );
}


// Grounded evidence assistant — answers only from the graded profile.
function AskClarity({ topic, category, compoundName, outcomes }) {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  const [messages, setMessages] = useState([]);   // assistant messages can carry evidence metadata
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyPhase, setBusyPhase] = useState(0);
  const scrollRef = useRef(null);

  const topOutcome = outcomes && outcomes.length ? outcomes[0].outcome : null;
  const suggestions = (es ? [
    "¿Qué muestran realmente los estudios en humanos?",
    topOutcome ? `Explícame la evidencia para ${topOutcome} en lenguaje sencillo.` : "Explícame la evidencia en lenguaje sencillo.",
    "¿Cuál es la mayor debilidad de la evidencia y por qué?",
    "¿Qué sabemos sobre seguridad y qué sigue sin saberse?",
  ] : [
    "What do the human studies actually show?",
    topOutcome ? `Explain the evidence for ${topOutcome} in plain English.` : "Explain the evidence in plain English.",
    "What's the biggest weakness in the evidence, and why?",
    "What do we know about safety, and what is still unknown?",
  ]).filter(Boolean).slice(0, 4);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, busy]);

  useEffect(() => {
    if (!busy) { setBusyPhase(0); return; }
    const a = setTimeout(() => setBusyPhase(1), 650);
    const b = setTimeout(() => setBusyPhase(2), 1800);
    return () => { clearTimeout(a); clearTimeout(b); };
  }, [busy]);

  const send = async (q) => {
    const question = (q ?? input).trim();
    if (!question || busy) return;
    setInput("");
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    const next = [...messages, { role: "user", content: question }];
    setMessages(next);
    setBusy(true);
    try {
      const result = await apiAsk(topic, category, question, history, lang);
      setMessages([...next, {
        role: "assistant",
        content: result.answer,
        grounded: result.grounded !== false,
        pmids: result.pmids || [],
        sourceRefs: result.source_refs || (result.pmids || []).map((x)=>`PMID:${x}`),
        coverage: result.coverage,
        retrievedStudies: result.retrieved_studies || 0,
        matchedOutcomes: result.matched_outcomes || [],
        eventId: result.event_id || null,
        mode: result.mode || (result.model_used ? "synthesis" : "structured"),
        timing: result.timing || null,
        cacheHit: !!result.cache_hit,
        feedback: null,
      }]);
    } catch (e) {
      setMessages([...next, { role: "assistant", content: e.message || "Something went wrong.", grounded: false }]);
    } finally {
      setBusy(false);
    }
  };

  const leaveFeedback = async (idx, helpful) => {
    const m = messages[idx];
    if (!m || !m.eventId || m.feedback !== null) return;
    setMessages((rows) => rows.map((x, i) => i === idx ? { ...x, feedback: helpful } : x));
    await apiAskFeedback(m.eventId, helpful);
  };

  const askSource = (ref) => {
    const raw = String(ref || "");
    if (raw.startsWith("PMID:")) return { label:`PMID ${raw.slice(5)}`, url:`https://pubmed.ncbi.nlm.nih.gov/${raw.slice(5)}/` };
    if (raw.startsWith("DOI:")) return { label:`DOI ${raw.slice(4)}`, url:`https://doi.org/${raw.slice(4)}` };
    if (raw.startsWith("EPMC:")) {
      const id = raw.slice(5); const parts=id.split(":");
      const url = parts.length>1 ? `https://europepmc.org/article/${String(parts[0]).toUpperCase()}/${parts.slice(1).join(":")}` : `https://europepmc.org/article/${id}`;
      return { label:`EPMC ${id}`, url };
    }
    return null;
  };

  return (
    <div style={{ margin:"0 0 34px", borderTop:`1px solid rgba(52,224,190,.28)`, borderBottom:`1px solid rgba(255,255,255,.065)`, background:"linear-gradient(180deg,rgba(52,224,190,.025),transparent)", overflow:"hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 11, padding: "18px 0 15px", borderBottom: `1px solid rgba(255,255,255,0.07)` }}>
        <div style={{ width: 34, height: 34, borderRadius: 10, background: `linear-gradient(135deg,${TEAL},${"#1B7A6C"})`, display: "grid", placeItems: "center", flexShrink: 0 }}>
          <MessageCircle size={18} color={INK} />
        </div>
        <div style={{ flex:1, minWidth:0 }}>
          <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: -0.2 }}>{es ? "Pregunta a Clarity sobre este compuesto" : "Ask Clarity about this compound"}</div>
          <div style={{ fontFamily: DISPLAY, fontSize: 11.5, color: MUTE, lineHeight:1.5, marginTop:3 }}>
            {es
              ? `Busca la evidencia relevante para tu pregunta exacta — resultados, estudios, efectos y resúmenes cuando están disponibles — y explica qué significa sin añadir hechos externos.`
              : `Searches the evidence relevant to your exact question — outcomes, study records, effect estimates, and abstracts when available — then explains what they mean without adding outside facts.`}
          </div>
        </div>
        <span style={{ fontFamily:MONO, fontSize:9.2, color:TEAL, border:`1px solid ${TEAL}35`, background:`${TEAL}0B`, padding:"4px 8px", borderRadius:999, whiteSpace:"nowrap" }}>{es?"EVIDENCIA CERRADA":"CLOSED-EVIDENCE AI"}</span>
      </div>

      {messages.length > 0 && (
        <div ref={scrollRef} style={{ maxHeight: 520, overflowY: "auto", padding: "18px 0", display: "flex", flexDirection: "column", gap: 15 }}>
          {messages.map((m, i) => (
            <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
              <div style={{ maxWidth: m.role === "user" ? "82%" : "92%", minWidth:m.role === "assistant"?"min(560px,92%)":"auto" }}>
                <div style={{ fontSize: 13.8, lineHeight: 1.7,
                  background: m.role === "user" ? "rgba(52,224,190,0.12)" : "rgba(255,255,255,0.035)",
                  border: `1px solid ${m.role === "user" ? "rgba(52,224,190,0.25)" : "rgba(255,255,255,0.08)"}`,
                  color: m.role === "user" ? TEXT : "#C6D2E2",
                  borderRadius: 14, padding: "11px 14px", whiteSpace: "pre-wrap" }}>
                  {m.content}
                </div>
                {m.role === "assistant" && m.grounded !== false ? (
                  <div style={{ marginTop:7, display:"flex", flexWrap:"wrap", alignItems:"center", gap:7 }}>
                    <span style={{ fontFamily:MONO, fontSize:9.2, color:TEAL, padding:"3px 7px", borderRadius:999, background:`${TEAL}0B`, border:`1px solid ${TEAL}2C` }}>
                      {m.mode === "instant"
                        ? (es ? "respuesta estructurada instantánea" : "instant structured answer")
                        : m.mode === "synthesis"
                          ? (es ? `síntesis IA · ${m.retrievedStudies || 0} estudios relevantes` : `AI synthesis · ${m.retrievedStudies || 0} relevant studies`)
                          : (es ? "basado en evidencia calificada" : "grounded in graded evidence")}
                    </span>
                    {m.timing && m.timing.total_ms != null ? <span style={{ fontFamily:MONO, fontSize:9.2, color:MUTE }}>{m.cacheHit ? (es?"caché":"cached") : `${(m.timing.total_ms/1000).toFixed(m.timing.total_ms<1000?2:1)}s`}</span> : null}
                    {m.coverage ? <span style={{ fontFamily:MONO, fontSize:9.2, color:MUTE }}>{es?"cobertura":"coverage"}: {m.coverage}</span> : null}
                    {(m.sourceRefs || (m.pmids || []).map((x)=>`PMID:${x}`)).slice(0,5).map((ref) => {
                      const src=askSource(ref);
                      return src ? <a key={ref} href={src.url} target="_blank" rel="noreferrer" style={{ fontFamily:MONO, fontSize:9.2, color:"#64B5FF", textDecoration:"none", border:"1px solid rgba(100,181,255,.24)", borderRadius:999, padding:"3px 7px" }}>{src.label} ↗</a> : null;
                    })}
                  </div>
                ) : null}
                {m.role === "assistant" && m.grounded === false ? (
                  <div style={{ marginTop: 6, fontFamily: MONO, fontSize: 9.5, color: AMBER }}>{es ? "No pude producir una respuesta basada únicamente en la evidencia disponible." : "I couldn't produce an answer grounded only in the available evidence."}</div>
                ) : null}
                {m.role === "assistant" && m.eventId ? (
                  <div style={{ marginTop:8, display:"flex", alignItems:"center", gap:7, fontFamily:MONO, fontSize:9.5, color:MUTE }}>
                    <span>{es?"¿Fue útil?":"Was this useful?"}</span>
                    <button onClick={()=>leaveFeedback(i,true)} disabled={m.feedback!==null} style={{ border:`1px solid ${m.feedback===true?`${TEAL}66`:LINE}`, background:m.feedback===true?`${TEAL}12`:"transparent", color:m.feedback===true?TEAL:MUTE, borderRadius:8, padding:"3px 7px", cursor:m.feedback===null?"pointer":"default", fontFamily:MONO, fontSize:9.2 }}>✓ {es?"Sí":"Yes"}</button>
                    <button onClick={()=>leaveFeedback(i,false)} disabled={m.feedback!==null} style={{ border:`1px solid ${m.feedback===false?`${CORAL}66`:LINE}`, background:m.feedback===false?`${CORAL}12`:"transparent", color:m.feedback===false?CORAL:MUTE, borderRadius:8, padding:"3px 7px", cursor:m.feedback===null?"pointer":"default", fontFamily:MONO, fontSize:9.2 }}>× {es?"No":"No"}</button>
                  </div>
                ) : null}
              </div>
            </div>
          ))}
          {busy && (
            <div style={{ display: "flex", justifyContent: "flex-start" }}>
              <div style={{ fontFamily: MONO, fontSize: 12, color: MUTE, padding: "10px 14px" }}>
                <span className="ask-dots">{es
                  ? (["buscando la evidencia relevante", "comparando resultados y estudios", "redactando una respuesta basada en evidencia"][busyPhase] || "leyendo la evidencia")
                  : (["finding the relevant evidence", "comparing outcomes and studies", "writing a grounded answer"][busyPhase] || "reading the evidence")}</span>
              </div>
            </div>
          )}
        </div>
      )}

      {messages.length === 0 && (
        <div style={{ padding: "16px 0 4px", display: "flex", flexWrap: "wrap", gap: 8 }}>
          {suggestions.map((s) => (
            <button key={s} onClick={() => send(s)} style={{ background: "rgba(255,255,255,0.035)", border: `1px solid ${LINE}`,
              color: "#B9C6D8", borderRadius: 20, padding: "8px 12px", fontSize: 12.5, cursor: "pointer", fontFamily: DISPLAY, textAlign:"left" }}>
              {s}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 9, padding: "15px 0 14px" }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") send(); }}
          placeholder={es ? `Pregunta cualquier cosa sobre ${compoundName}…` : `Ask anything about ${compoundName}…`} disabled={busy}
          style={{ flex: 1, minWidth: 0, background: "rgba(255,255,255,0.04)", border: `1px solid ${LINE}`,
            borderRadius: 11, padding: "12px 14px", color: TEXT, fontSize: 14, fontFamily: DISPLAY, outline: "none" }} />
        <button onClick={() => send()} disabled={busy || !input.trim()} aria-label="Send"
          style={{ background: input.trim() && !busy ? TEAL : "rgba(255,255,255,0.06)",
            color: input.trim() && !busy ? INK : MUTE, border: "none", borderRadius: 11,
            width: 44, height: 44, display: "grid", placeItems: "center", cursor: input.trim() && !busy ? "pointer" : "default", flexShrink: 0 }}>
          <Send size={18} />
        </button>
      </div>
      <div style={{ padding: "0 0 16px", fontFamily: MONO, fontSize: 9.8, color: "#5E6E8A", lineHeight: 1.55 }}>
        {es
          ? "No es consejo médico. Clarity solo sintetiza la evidencia de este perfil. Por defecto no almacenamos el texto de tus preguntas; solo metadatos técnicos y comentarios de utilidad. Las preguntas complejas pueden procesarse mediante un proveedor de modelo externo. Evita incluir información personal identificable."
          : "Not medical advice. Clarity only synthesizes evidence in this profile. By default we do not store your raw question text; only technical quality metadata and optional helpful/not-helpful feedback. Complex questions may be processed by an external model provider. Avoid including identifying personal information."}
      </div>
    </div>
  );
}

// Icon-led expandable card: collapsed shows a one-line summary; click expands to
// the detail. Matches the compound-page mockup (what it is / how it works / safety).
function ExpandCard({ icon, eyebrow, line, children, accent = TEAL, tone = "default" }) {
  const [open, setOpen] = useState(false);
  const [lang] = React.useContext(LangContext);
  const bg = "transparent";
  const border = tone === "warn" ? "rgba(245,181,68,0.18)" : "rgba(255,255,255,0.065)";
  const eyebrowColor = tone === "warn" ? "#A9761F" : "#5E6E8A";
  const chipBg = tone === "warn" ? "rgba(245,181,68,0.10)" : "rgba(52,224,190,0.08)";
  const chipBorder = tone === "warn" ? "rgba(245,181,68,0.28)" : "rgba(52,224,190,0.20)";
  const chipText = tone === "warn" ? "#D89C36" : "#9CCFC5";
  const detailsLabel = lang === "es" ? (open ? "Ocultar detalle" : "Más detalle") : (open ? "Hide detail" : "More detail");
  const clickHint = lang === "es" ? (open ? "Haz clic para contraer" : "Haz clic en la tarjeta para expandir") : (open ? "Click to collapse" : "Click anywhere on the card to expand");
  return (
    <div style={{ borderRadius:0, background:bg, borderTop:`1px solid ${border}`, borderBottom:`1px solid ${border}`, transition:"border-color .25s ease, background .25s ease", backgroundColor:open?`${accent}04`:"transparent", alignSelf:"start", width:"100%" }}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        style={{ width: "100%", background: "transparent", border: 0, color: "inherit", cursor: "pointer", display: "block", textAlign: "left", padding: 0 }}>
        <div style={{ display: "flex", gap: 14, alignItems: "flex-start", padding: "18px 20px 14px" }}>
          <div style={{ width: 22, height: 22, flexShrink: 0, marginTop: 1, color: accent }}>{icon}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: DISPLAY, fontSize: 11.5, fontWeight:650, letterSpacing: 0, color: eyebrowColor, marginBottom: 6 }}>{eyebrow}</div>
            <div style={{ fontSize: 15, lineHeight: 1.5, fontWeight: 500, color: TEXT, textWrap: "pretty" }}>{line}</div>
          </div>
          <span style={{ flexShrink: 0, display: "inline-flex", alignItems: "center", gap: 8, padding: "7px 10px", borderRadius: 999, border: `1px solid ${chipBorder}`, background: chipBg, color: chipText, fontFamily: MONO, fontSize: 10.5, whiteSpace: "nowrap" }}>
            {detailsLabel}<span style={{ color: eyebrowColor, fontSize: 12, transition: "transform .3s ease", transform: open ? "rotate(180deg)" : "none", display: "inline-block" }}>▾</span>
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "0 20px 14px 56px" }}>
          <div style={{ fontFamily: DISPLAY, fontSize: 10.5, color: MUTE }}>{clickHint}</div>
          <div style={{ width: 46, height: 2, borderRadius: 999, background: open ? accent : "rgba(255,255,255,0.10)", boxShadow: open ? `0 0 10px ${accent}55` : "none" }} />
        </div>
      </button>
      <div style={{ overflow: "hidden", transition: "max-height .45s cubic-bezier(.2,.9,.25,1), opacity .3s ease", maxHeight: open ? 600 : 0, opacity: open ? 1 : 0 }}>
        <div style={{ padding: "14px 20px 18px 56px", borderTop: "1px solid rgba(255,255,255,0.05)" }}>{children}</div>
      </div>
    </div>
  );
}

// Small inline SVG icons (stroke-based, match the mockup).
const IconInfo = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="22" height="22"><circle cx="12" cy="12" r="9" /><path d="M12 16v-5" /><path d="M12 8h.01" /></svg>;
const IconBolt = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="22" height="22"><path d="M13 3 5 14h6l-1 7 8-11h-6l1-7z" /></svg>;
const IconShield = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="22" height="22"><path d="M12 3l7 3v6c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6l7-3z" /><path d="M12 9.5v3.2" /><path d="M12 16h.01" /></svg>;

// The rebuilt explainer: evidence-square grid on the left, the three expandable
// cards (what it is / how it works / safety) on the right. Falls back gracefully
// when a compound has no generated explanation yet.
function ExplainerSection({ ex, view }) {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  if (!ex) return null;

  const unique = new Map();
  (view.outcomes || []).forEach((o, oi) => (o.studies || []).forEach((st, si) => {
    const key = String(st.pmid || st.id || st.title || `${oi}-${si}`);
    if (!unique.has(key)) unique.set(key, st);
  }));
  const records = [...unique.values()];
  const hasRecords = records.length > 0;
  const totalStudies = hasRecords ? records.length : (view.studyCount || 0);
  const popOf = (st) => String(st.population || st.pop || "").toLowerCase();
  const nHuman = hasRecords ? records.filter((st)=>popOf(st).includes("human")).length : Math.min(totalStudies, view.outcomes.reduce((n,o)=>n+(o.layers?.nHuman||0),0));
  const nAnimal = hasRecords ? records.filter((st)=>popOf(st).includes("animal")).length : Math.min(Math.max(0,totalStudies-nHuman), view.outcomes.reduce((n,o)=>n+(o.layers?.nAnimal||0),0));
  const nUnlabelled = Math.max(0,totalStudies-nHuman-nAnimal);
  const shown = Math.min(totalStudies,120);
  const squares=[];
  for(let i=0;i<shown;i++){ const kind=i<nHuman?"human":i<nHuman+nAnimal?"animal":"unknown"; squares.push({kind,delay:Math.min(i*.009,.55)}); }
  const pct=(n)=>totalStudies?Math.round(n/totalStudies*100):0;

  return (
    <div style={{ marginBottom:22 }}>
      {/* The basics come first. A reader should know what the compound is before seeing technical evidence graphics. */}
      <div style={{ marginBottom:15 }}>
        <h2 style={{margin:0,fontSize:22,fontWeight:680,letterSpacing:-.55}}>{es?"Entiende el compuesto":"Understand the compound"}</h2>
        <div style={{ fontSize:13, lineHeight:1.55, color:MUTE, marginTop:5 }}>{es?"Qué es, cómo se propone que funcione y qué sabemos sobre seguridad.":"What it is, how it is proposed to work, and what the evidence says about safety."}</div>
      </div>
      <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit,minmax(250px,1fr))", gap:10, marginBottom:16, alignItems:"start" }}>
        {(ex.what_it_is_line||ex.what_it_is)?<ExpandCard icon={IconInfo} eyebrow={es?"QUÉ ES":"WHAT IT IS"} line={ex.what_it_is_line||ex.what_it_is} accent={TEAL}><div style={{fontSize:13.5,lineHeight:1.7,color:"#A9B8CE",textWrap:"pretty"}}>{ex.what_it_is}</div></ExpandCard>:null}
        {(ex.how_it_works_line||ex.how_it_works)?<ExpandCard icon={IconBolt} eyebrow={es?"CÓMO FUNCIONA":"HOW IT WORKS"} line={ex.how_it_works_line||ex.how_it_works} accent={TEAL}><div style={{fontSize:13.5,lineHeight:1.7,color:"#A9B8CE",textWrap:"pretty"}}>{ex.how_it_works}</div></ExpandCard>:null}
        {(ex.safety_line||ex.safety_detail||ex.caveats)?<ExpandCard icon={IconShield} eyebrow={es?"SEÑALES DE SEGURIDAD EN LA EVIDENCIA":"SAFETY SIGNALS IN THE EVIDENCE"} line={ex.safety_line||ex.caveats||(es?"Consulta lo que informaron los ensayos.":"See what the trials reported.")} accent={AMBER} tone="warn">{ex.safety_detail?<div style={{fontSize:13.5,lineHeight:1.7,color:"#A9B8CE",marginBottom:(ex.safety_bullets&&ex.safety_bullets.length)?12:0,textWrap:"pretty"}}>{ex.safety_detail}</div>:null}{ex.safety_bullets&&ex.safety_bullets.length?<div style={{display:"flex",flexDirection:"column",gap:7}}>{ex.safety_bullets.map((b,i)=><div key={i} style={{display:"flex",gap:9,alignItems:"baseline",fontSize:13,lineHeight:1.55,color:"#C9D6E7"}}><span style={{color:AMBER,fontFamily:MONO,fontSize:11}}>·</span>{b}</div>)}</div>:null}{!ex.safety_detail&&!ex.safety_bullets&&ex.caveats?<div style={{fontSize:13.5,lineHeight:1.7,color:"#A9B8CE"}}>{ex.caveats}</div>:null}<div style={{fontFamily:MONO,fontSize:9.2,lineHeight:1.5,color:"#756A52",marginTop:10}}>{es?"Resume señales reportadas en la evidencia revisada; no es un comprobador completo de interacciones farmacológicas.":"Summarizes signals reported in the reviewed evidence; this is not a comprehensive drug-interaction checker."}</div></ExpandCard>:null}
      </div>

      {/* Evidence composition is secondary: useful, but it should not compete with the basic explanation. */}
      <section style={{ padding:"17px 0", borderTop:"1px solid rgba(255,255,255,.065)", borderBottom:"1px solid rgba(255,255,255,.055)" }}>
        <div style={{ display:"flex", justifyContent:"space-between", gap:10, alignItems:"baseline", flexWrap:"wrap", marginBottom:12 }}>
          <div><div style={{ fontSize:13,fontWeight:650,color:"#C9D5E4" }}>{es?"Composición de la evidencia":"Evidence composition"}</div><div style={{ fontSize:11.5,color:MUTE,marginTop:3 }}>{es?"Un cuadrado por estudio único":"One square per unique study"}</div></div>
          <div style={{ fontFamily:MONO,fontSize:9.5,color:"#667893" }}>{totalStudies} {es?"estudios únicos":"unique studies"}</div>
        </div>
        <div style={{ display:"grid", gridTemplateColumns:"minmax(220px,.9fr) minmax(280px,1.4fr)", gap:18, alignItems:"center" }} className="evidence-composition-grid">
          <div>
            <div style={{ height:9, display:"flex", overflow:"hidden", borderRadius:999, background:"rgba(255,255,255,.045)", border:"1px solid rgba(255,255,255,.04)", marginBottom:10 }}>{nHuman?<motion.div initial={{width:0}} whileInView={{width:`${pct(nHuman)}%`}} viewport={{once:true}} transition={{duration:.6,ease:MOTION_EASE}} style={{background:TEAL}}/>:null}{nAnimal?<motion.div initial={{width:0}} whileInView={{width:`${pct(nAnimal)}%`}} viewport={{once:true}} transition={{duration:.6,delay:.08,ease:MOTION_EASE}} style={{background:VIOLET}}/>:null}{nUnlabelled?<motion.div initial={{width:0}} whileInView={{width:`${pct(nUnlabelled)}%`}} viewport={{once:true}} transition={{duration:.6,delay:.12,ease:MOTION_EASE}} style={{background:"rgba(255,255,255,.13)"}}/>:null}</div>
            <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:6 }}>{[{label:es?"HUMANO":"HUMAN",n:nHuman,p:pct(nHuman),c:TEAL},{label:es?"ANIMAL":"ANIMAL",n:nAnimal,p:pct(nAnimal),c:VIOLET},{label:es?"SIN ETIQUETA":"UNLABELLED",n:nUnlabelled,p:pct(nUnlabelled),c:"#71809A"}].map((it)=><div key={it.label} style={{borderRadius:9,padding:"8px 9px",background:`${it.c}07`,border:`1px solid ${it.c}1F`}}><div style={{fontFamily:MONO,fontSize:8,color:"#667893"}}>{it.label}</div><div style={{display:"flex",alignItems:"baseline",gap:5,marginTop:4}}><span style={{fontFamily:MONO,fontSize:16,color:it.c,fontWeight:650}}>{it.n}</span><span style={{fontFamily:MONO,fontSize:8.5,color:MUTE}}>{it.p}%</span></div></div>)}</div>
          </div>
          <div>
            <div className="study-matrix" style={{ display:"grid", gap:3, marginBottom:9 }}>{squares.map((s,i)=><motion.div key={i} initial={{opacity:0,scale:.65}} whileInView={{opacity:1,scale:1}} viewport={{once:true}} transition={{duration:.2,delay:s.delay}} title={s.kind} style={{aspectRatio:"1",borderRadius:2.3,background:s.kind==="human"?TEAL:s.kind==="animal"?VIOLET:"transparent",border:s.kind==="unknown"?"1px solid rgba(255,255,255,.20)":"none",boxShadow:s.kind==="human"?`0 0 5px ${TEAL}20`:"none"}}/>)}</div>
            <div style={{ fontSize:11.8,lineHeight:1.55,color:"#8FA0B8",textWrap:"pretty" }}>{es?"Esmeralda = humano; violeta = animal. Los artículos se deduplican por PMID, DOI o identificador de Europe PMC cuando está disponible.":"Emerald = human; violet = animal. Papers are deduplicated by PMID, DOI, or Europe PMC identifier when available."}</div>
          </div>
        </div>
      </section>
    </div>
  );
}

function MethodologyPage({ onBack }) {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  const tiers = es ? [
    { name: "Strong", color: TEAL, plain: "Muchos estudios en humanos coinciden.",
      detail: "Múltiples ensayos en humanos — idealmente con metanálisis — apuntan en la misma dirección y estudian a suficientes personas para tener confianza. Es de lo más sólido que suele ofrecer la ciencia de suplementos." },
    { name: "Moderate", color: AMBER, plain: "Evidencia humana real, pero más limitada.",
      detail: "Hay estudios en humanos y son alentadores, pero son menos, más pequeños o todavía no existe un análisis combinado que confirme que todos coinciden. Prometedor, no definitivo." },
    { name: "Emerging", color: VIOLET, plain: "Señales tempranas — animales o una pista en personas.",
      detail: "La evidencia es preliminar: estudios animales, celulares o uno o dos ensayos humanos pequeños. Interesante, pero todavía no demuestra un efecto fiable en personas." },
    { name: "Preliminary", color: CORAL, plain: "Un solo hilo de evidencia — trátalo como una pregunta.",
      detail: "Hay muy poco en qué apoyarse: a menudo un único estudio o trabajo de laboratorio/animal. Lo mostramos para que sepas qué existe, no porque esté establecido." },
  ] : [
    { name: "Strong", color: TEAL, plain: "Many human studies support the same conclusion.",
      detail: "Multiple human trials — ideally including pooled syntheses — support the same conclusion with enough people studied to justify high confidence in the evidence." },
    { name: "Moderate", color: AMBER, plain: "Real human evidence, but thinner.",
      detail: "There are human studies and they're encouraging, but there are fewer of them, or they're smaller, or no pooled analysis has confirmed they all agree. Promising, not proven-beyond-doubt." },
    { name: "Emerging", color: VIOLET, plain: "Early signals — mostly animal or a hint in people.",
      detail: "The evidence is preliminary: animal studies, cell studies, or one or two small human trials. Interesting, but not yet shown to reliably work in people." },
    { name: "Preliminary", color: CORAL, plain: "A single thread — treat it as a question.",
      detail: "Very little to go on — often a lone study, or lab/animal work only. We show it so you know what exists, not because it's established." },
  ];
  const steps = es ? [
    ["Buscamos los estudios reales", "Para cada compuesto y resultado de salud, buscamos en PubMed y Europe PMC, combinamos y deduplicamos los registros, y priorizamos metanálisis y ensayos en humanos."],
    ["Separamos humanos de animales", "Un estudio en ratones no es evidencia sobre personas. Clasificamos cada estudio por población, y solo la evidencia humana puede elevar una calificación a los niveles superiores."],
    ["Comprobamos hacia dónde apuntan los resultados", "Muchos estudios que concluyen 'sin efecto' no son evidencia de beneficio. Evaluamos la dirección por separado de la fuerza; si no puede verificarse de forma concluyente, Clarity retiene el nivel superior en lugar de asumir beneficio."],
    ["Calificamos certeza, no publicidad", "El nivel refleja cuánta confianza permite la evidencia: cantidad y diseño de estudios, humanos frente a animales, consistencia, precisión y disponibilidad de tamaños de efecto. Si falta un dato, mostramos el hueco."],
  ] : [
    ["We pull the real studies", "For each compound and health outcome, we search PubMed and Europe PMC, merge and deduplicate the records, and prioritize meta-analyses and human trials."],
    ["We separate human from animal", "A study in mice is not evidence about people. We classify every study by who (or what) it was done in, and only human evidence can lift a grade to the top tiers. Animal and cell data are shown, but they can't inflate the grade."],
    ["We check which way it points", "A big pile of studies concluding 'no effect' is not evidence of benefit. We assess direction separately from evidence strength; if direction cannot be verified conclusively, Clarity withholds the top efficacy tier rather than assuming benefit."],
    ["We grade on certainty, not hype", "The tier reflects how confident the evidence lets us be — study count, quality, human vs. animal, consistency, and whether effect sizes were even reported. Where a number doesn't exist, we show the gap rather than invent one."],
  ];
  return (
    <div className="rise" style={{ paddingBottom: 90, paddingTop: 8, maxWidth: 820, margin: "0 auto" }}>
      <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: 1.6, color: TEAL, marginBottom: 12 }}>{es ? "CÓMO FUNCIONAN LAS CALIFICACIONES" : "HOW GRADING WORKS"}</div>
      <h1 style={{ margin: "0 0 16px", fontSize: 40, lineHeight: 1.05, letterSpacing: -1.6, fontWeight: 700, textWrap: "pretty" }}>{es ? "Cada calificación se remonta a estudios reales — y también a los estudios que faltan." : "Every grade traces back to real studies — and to the studies that are missing."}</h1>
      <p style={{ fontSize: 15.5, lineHeight: 1.7, color: "#A9B8CE", marginBottom: 20, maxWidth: 660, textWrap: "pretty" }}>
        {es ? "Muchos sitios de suplementos te dicen lo que vende. Clarity te muestra lo que realmente indica la investigación publicada, incluyendo dónde hay muy poca evidencia. Así es como un compuesto obtiene su calificación." : "Most supplement sites tell you what sells. Clarity tells you what the published research actually shows — including, honestly, where it shows very little. Here's exactly how a compound earns its grade."}
      </p>
      <div style={{ borderRadius:14, padding:"16px 18px", background:"rgba(95,168,245,.055)", border:"1px solid rgba(95,168,245,.20)", marginBottom:30 }}>
        <div style={{ fontFamily:MONO, fontSize:9.5, letterSpacing:1.2, color:"#75B8FF", marginBottom:7 }}>{es?"MARCO AUTOMATIZADO, INFORMADO POR GRADE":"AUTOMATED, GRADE-INFORMED FRAMEWORK"}</div>
        <div style={{ fontSize:12.8, lineHeight:1.65, color:"#A9B8CE" }}>{es?"Clarity usa reglas transparentes inspiradas en principios de GRADE para evaluar diseño del estudio, población humana frente a animal, precisión disponible, replicación/síntesis y dirección del efecto. No equivale a una evaluación GRADE manual realizada por un panel de expertos y no puede medir automáticamente todos los dominios de riesgo de sesgo, heterogeneidad o sesgo de publicación. Los preprints pueden aparecer durante la búsqueda, pero se excluyen del cálculo del nivel publicado.":"Clarity uses transparent rules informed by GRADE principles to assess study design, human versus animal evidence, available precision, replication/synthesis, and effect direction. It is not a formal expert-panel GRADE assessment and cannot automatically evaluate every risk-of-bias, heterogeneity, or publication-bias domain. Preprints may be discovered during retrieval, but they are excluded from the published tier calculation."}</div>
      </div>

      <div style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: 1.4, color: MUTE, marginBottom: 16 }}>{es ? "LOS CUATRO NIVELES" : "THE FOUR TIERS"}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 40 }}>
        {tiers.map((tr) => (
          <div key={tr.name} style={{ borderRadius: 14, padding: "18px 0", background: `${tr.color}0D`, border: `1px solid ${tr.color}44` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <span style={{ width: 11, height: 11, borderRadius: 3, background: tr.color }} />
              <span style={{ fontSize: 17, fontWeight: 700, color: tr.color }}>{tierLabel(tr.name, lang)}</span>
              <span style={{ fontSize: 14.5, color: TEXT, fontWeight: 500 }}>— {tr.plain}</span>
            </div>
            <div style={{ fontSize: 13.5, lineHeight: 1.65, color: "#A9B8CE", paddingLeft: 21, textWrap: "pretty" }}>{tr.detail}</div>
          </div>
        ))}
      </div>

      <div style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: 1.4, color: MUTE, marginBottom: 16 }}>{es ? "CÓMO LLEGAMOS AHÍ — CUATRO PASOS" : "HOW WE GET THERE — FOUR STEPS"}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 40 }}>
        {steps.map(([title, body], i) => (
          <div key={i} style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
            <div style={{ flexShrink: 0, width: 34, height: 34, borderRadius: 10, background: "rgba(52,224,190,0.1)", border: "1px solid rgba(52,224,190,0.3)", display: "grid", placeItems: "center", fontFamily: MONO, fontSize: 13, color: TEAL, fontWeight: 600 }}>{i + 1}</div>
            <div>
              <div style={{ fontSize: 15.5, fontWeight: 650, marginBottom: 4 }}>{title}</div>
              <div style={{ fontSize: 13.5, lineHeight: 1.65, color: "#A9B8CE", textWrap: "pretty" }}>{body}</div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ borderRadius: 14, padding: "20px 22px", background: "rgba(154,140,245,0.06)", border: "1px solid rgba(154,140,245,0.22)", marginBottom: 20 }}>
        <div style={{ fontSize: 15, fontWeight: 650, marginBottom: 8, color: VIOLET }}>{es ? "Por qué tantos péptidos son Emergentes o Preliminares" : "Why so many peptides are Emerging or Preliminary"}</div>
        <div style={{ fontSize: 13.5, lineHeight: 1.7, color: "#A9B8CE", textWrap: "pretty" }}>
          {es ? "Muchos péptidos muestran resultados llamativos en animales, pero todavía tienen pocos o ningún ensayo humano adecuado. Una calificación baja no significa 'no funciona'; significa 'todavía no se ha demostrado que funcione en personas'." : "Many peptides have striking results in animals but few or no proper human trials yet. That's not us being harsh — it's the honest state of the research. A low tier doesn't mean 'doesn't work'; it means 'not yet shown to work in people.' We think you deserve to know which is which before you decide anything."}
        </div>
      </div>

      <div style={{ fontFamily: MONO, fontSize: 11, color: "#5E6E8A", lineHeight: 1.6 }}>
        {es ? "Las calificaciones y los gráficos se generan a partir de evidencia recuperada de PubMed y Europe PMC. Clarity es una herramienta de investigación y educación, no consejo médico." : "Grades and charts are generated from evidence retrieved through PubMed and Europe PMC. Clarity is a research and education tool, not medical advice — talk to a clinician about your own health decisions."}
      </div>
    </div>
  );
}

function ProfileView({ view, source, onBack, onLearn }) {
  if (!view) return null;
  const [lang] = React.useContext(LangContext);
  const t = STRINGS[lang] || STRINGS.en;
  const es = lang === "es";
  const ex = (lang === "es" && view.explanation_es) ? view.explanation_es : (view.explanation || null);
  const appraisalPick = (lang === "es" && view.appraisal_es) ? view.appraisal_es : view.appraisal;
  const figMode = useState("stack");
  const hoverState = useState(null);
  const [guided, setGuided] = useState(false);
  const proven = view.outcomes.filter((o) => o.tier === "Strong" || o.tier === "Moderate");
  const promising = view.outcomes.filter((o) => o.tier === "Emerging" || o.tier === "Preliminary");
  const humanRun = Number.isFinite(view.uniqueHumanStudyCount) ? view.uniqueHumanStudyCount : view.outcomes.reduce((n, o) => n + (o.layers?.nHuman || 0), 0);
  const verdictLead = es
    ? (view.established?.length && !view.promising?.length ? "Respaldado por evidencia humana en sus principales resultados."
      : view.promising?.length && !view.established?.length ? "Prometedor en mecanismos o estudios animales, pero aún no demostrado en humanos."
      : view.established?.length && view.promising?.length ? "Respaldado por evidencia humana para algunos resultados; todavía temprano o incierto para otros."
      : "Evidencia temprana o limitada; interpreta las afirmaciones con cautela.")
    : view.verdict;
  const updatedLabel = view.generatedAt ? new Date(view.generatedAt).toLocaleDateString(lang === "es" ? "es-ES" : "en-US", { year:"numeric", month:"short", day:"numeric" }) : null;
  const sourceLabel = (view.sources || []).map((x) => String(x).replace("europe_pmc","Europe PMC").replace("pubmed","PubMed")).join(" + ") || "PubMed + Europe PMC";
  const badgeText = view.outcomeDependent ? (es ? "DEPENDE DEL RESULTADO" : "OUTCOME-DEPENDENT") : String(tierLabel(view.bestTier || view.tier, lang)).toUpperCase();
  const snapshotFacts = [
    { label: es ? "estudios únicos calificados" : "unique studies graded", value: view.studyCount, accent: TEXT },
    { label: t.outcomes_graded, value: view.outcomes.length, accent: TEXT },
    { label: t.run_in_people, value: humanRun, accent: TEAL },
  ];
  return (
    <div className="rise" style={{ paddingBottom: 90, paddingTop: 8 }}>
      <div style={{ display:"flex", justifyContent:"flex-end", marginBottom:16 }}>
        <motion.button whileHover={{ y:-1 }} whileTap={{ scale:.98 }} transition={MOTION_SPRING} onClick={() => setGuided((v)=>!v)} style={{ display:"inline-flex",alignItems:"center",gap:8,border:`1px solid ${guided ? TEAL : LINE}`,background:guided?`${TEAL}12`:PANEL2,color:guided?TEAL:MUTE,borderRadius:20,padding:"8px 13px",cursor:"pointer",fontFamily:MONO,fontSize:10.5 }}>
          <BookOpen size={14}/>{es ? (guided ? "Ocultar ayuda" : "Ayúdame a entender esta página") : (guided ? "Hide guide" : "Help me understand this page")}
        </motion.button>
      </div>

      {/* HEADER — simple scientific overview. Keep the first screen readable. */}
      <div style={{ display:"flex", flexWrap:"wrap", gap:36, alignItems:"flex-end", padding:"2px 0 28px" }}>
        <div style={{ flex:"1 1 520px", minWidth:300 }}>
          <div style={{ fontFamily:MONO, fontSize:11, letterSpacing:1.6, color:TEAL, marginBottom:13, textTransform:"uppercase" }}>{categoryLabel(view.cat, lang)}</div>
          <h1 style={{ margin:"0 0 16px", fontSize:50, lineHeight:1.0, letterSpacing:-2.3, fontWeight:700, textTransform:"capitalize", textWrap:"pretty" }}>{view.name}</h1>
          <p style={{ margin:"0 0 18px", maxWidth:660, fontSize:15.5, lineHeight:1.68, color:"#A9B8CE", textWrap:"pretty" }}>
            {verdictLead} {es ? "Cuando no existe un número, mostramos el vacío en lugar de rellenarlo con una afirmación de marketing." : "Where a number doesn't exist, you'll see the hole where it should be — not a marketing claim."}
          </p>

          {view.chemistry && view.chemistry.formula ? (
            <a href={view.chemistry.pubchem_url || "#chemistry"} target={view.chemistry.pubchem_url?"_blank":undefined} rel={view.chemistry.pubchem_url?"noreferrer":undefined} style={{ display:"inline-flex", maxWidth:"100%", flexWrap:"wrap", gap:10, alignItems:"center", marginBottom:20, padding:"6px 0", color:"inherit", textDecoration:"none" }}>
              {view.chemistry.image_url ? <div style={{width:42,height:42,borderRadius:9,background:"rgba(255,255,255,.94)",display:"grid",placeItems:"center",overflow:"hidden",flexShrink:0}}><img src={view.chemistry.image_url} alt="" style={{width:38,height:38,objectFit:"contain"}}/></div> : <div style={{width:34,height:34,borderRadius:9,display:"grid",placeItems:"center",background:`${TEAL}09`}}><FlaskConical size={16} color={TEAL}/></div>}
              <div style={{minWidth:0}}><div style={{fontSize:11.5,fontWeight:650,color:"#C9D5E4"}}>{es?"Identidad molecular":"Molecular identity"}</div><div style={{display:"flex",flexWrap:"wrap",gap:7,alignItems:"baseline",marginTop:3,fontFamily:MONO,fontSize:9.8,color:"#7F91AA"}}><span style={{color:TEAL}}>{view.chemistry.formula}</span>{view.chemistry.weight?<><span>·</span><span>{view.chemistry.weight} g/mol</span></>:null}{view.chemistry.cid?<><span>·</span><span>PubChem {view.chemistry.cid}</span></>:null}<span style={{color:"#78BDF8"}}>↗</span></div></div>
            </a>
          ) : null}

          <div style={{ display:"flex", flexWrap:"wrap", gap:24, alignItems:"baseline" }}>
            <div><span style={{ fontFamily:MONO, fontSize:26, fontWeight:650, color:TEXT }}>{view.studyCount}</span><span style={{ fontSize:12, color:MUTE }}> {es?"estudios únicos calificados":"unique studies graded"}</span></div>
            <div><span style={{ fontFamily:MONO, fontSize:26, fontWeight:650, color:TEXT }}>{view.outcomes.length}</span><span style={{ fontSize:12, color:MUTE }}> {t.outcomes_graded}</span></div>
            <div><span style={{ fontFamily:MONO, fontSize:26, fontWeight:650, color:TEAL }}>{humanRun}</span><span style={{ fontSize:12, color:MUTE }}> {t.run_in_people}</span></div>
          </div>
          <div style={{ display:"flex", flexWrap:"wrap", gap:8, alignItems:"center", marginTop:14, fontSize:10.5, color:"#667893" }}>
            <span>{sourceLabel}</span>{updatedLabel ? <><span style={{opacity:.45}}>·</span><span>{es?"actualizado":"updated"} {updatedLabel}</span></> : null}{view.engineVersion ? <><span style={{opacity:.45}}>·</span><span>engine {view.engineVersion}</span></> : null}
          </div>
        </div>

        <div style={{ flex:"0 0 250px", alignSelf:"stretch", display:"flex", flexDirection:"column", justifyContent:"flex-end" }}>
          <div style={{ padding:"16px 0 14px 18px", borderLeft:`2px solid ${view.tierColor}`, borderTop:"1px solid rgba(255,255,255,.06)", borderBottom:"1px solid rgba(255,255,255,.06)" }}>
            <div style={{fontSize:10.5,fontWeight:650,color:MUTE,marginBottom:7}}>{es?"Clasificación de evidencia":"Evidence classification"}</div>
            <div style={{fontSize:view.outcomeDependent?15:26,fontWeight:720,letterSpacing:-.4,color:view.tierColor,lineHeight:1.08}}>{badgeText}</div>
            <div style={{fontSize:10.5,color:"#7F91AA",lineHeight:1.45,marginTop:8}}>{view.outcomeDependent ? (es?`Mejor resultado humano: ${view.bestOutcome || "—"} · ${tierLabel(view.bestTier||view.tier,lang)}`:`Best-supported human outcome: ${view.bestOutcome || "—"} · ${view.bestTier||view.tier}`) : (es?"Nivel humano más fuerte entre los resultados identificados":"Strongest human-supported tier among identified outcomes")}</div>
            {view.weighted ? <div style={{display:"flex",alignItems:"baseline",gap:6,marginTop:11}}><span style={{fontFamily:MONO,fontSize:15,color:TEXT,fontWeight:650}}>{view.weighted.score}</span><span style={{fontSize:10,color:MUTE}}>/100 {es?"fuerza de evidencia":"evidence strength"}</span></div> : null}
          </div>
        </div>
      </div>


      <AnimatePresence initial={false}>
      {guided ? (
        <motion.div key="reading-guide" initial={{ opacity:0, height:0, y:-8 }} animate={{ opacity:1, height:"auto", y:0 }} exit={{ opacity:0, height:0, y:-6 }} transition={{ duration:.38, ease:MOTION_EASE }} style={{ margin:"0 0 22px", padding:"20px", borderRadius:17, border:`1px solid ${TEAL}45`, background:"linear-gradient(135deg,rgba(52,224,190,.07),rgba(154,140,245,.035))", overflow:"hidden" }}>
          <div style={{ display:"flex",justifyContent:"space-between",gap:12,alignItems:"flex-start",flexWrap:"wrap",marginBottom:15 }}>
            <div><div style={{ fontFamily:MONO,fontSize:9.5,letterSpacing:1.4,color:TEAL,marginBottom:5 }}>{es ? "GUÍA DE LECTURA" : "READING GUIDE"}</div><div style={{ fontSize:18,fontWeight:700 }}>{es ? "Qué significan estos números" : "What these numbers mean"}</div></div>
            {onLearn ? <button onClick={()=>onLearn("evidence")} style={{ border:"none",background:"transparent",color:TEAL,cursor:"pointer",fontFamily:MONO,fontSize:10 }}>{es ? "Guía completa de evidencia" : "Full evidence guide"} →</button> : null}
          </div>
          <div style={{ display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(220px,1fr))",gap:10 }}>
            <div style={{ padding:15,borderRadius:12,background:"rgba(255,255,255,.025)",border:`1px solid ${LINE}` }}><div style={{ fontFamily:MONO,fontSize:9.5,color:VIOLET,marginBottom:7 }}>{es ? "ESTUDIOS" : "STUDIES"}</div><div style={{ fontSize:13,lineHeight:1.58,color:"#B8C6D8" }}>{es ? `${view.studyCount} estudios únicos están vinculados a los resultados mostrados; ${humanRun} son estudios humanos únicos. Un mismo estudio puede contribuir a más de un resultado sin contarse dos veces aquí.` : `${view.studyCount} unique studies are tied to the outcomes shown; ${humanRun} are unique human studies. The same paper can inform more than one outcome without being counted twice here.`}</div></div>
            <div style={{ padding:15,borderRadius:12,background:"rgba(255,255,255,.025)",border:`1px solid ${LINE}` }}><div style={{ fontFamily:MONO,fontSize:9.5,color:view.tierColor,marginBottom:7 }}>{es ? "NIVEL Y PUNTUACIÓN" : "TIER & SCORE"}</div><div style={{ fontSize:13,lineHeight:1.58,color:"#B8C6D8" }}>{es ? `El titular refleja el resultado humano mejor respaldado${view.outcomeDependent ? "; otros resultados tienen niveles distintos" : ""}. ${view.weighted ? `La puntuación ${view.weighted.score}/100 mide fuerza de evidencia; no es la probabilidad de que funcione.` : "Cuando no hay puntuación ponderada, no inventamos una."}` : `The headline reflects the best-supported human outcome${view.outcomeDependent ? "; other outcomes have different tiers" : ""}. ${view.weighted ? `The ${view.weighted.score}/100 score measures evidence strength; it is not the probability that it works.` : "When a weighted score is unavailable, we do not invent one."}`}</div></div>
            <div style={{ padding:15,borderRadius:12,background:"rgba(255,255,255,.025)",border:`1px solid ${LINE}` }}><div style={{ fontFamily:MONO,fontSize:9.5,color:TEAL,marginBottom:7 }}>{es ? "CAPAS" : "LAYERS"}</div><div style={{ fontSize:13,lineHeight:1.58,color:"#B8C6D8" }}>{es ? "Mecanismo y datos animales pueden hacer que una señal sea científicamente interesante. Para afirmar un beneficio en personas, la evidencia debe sostenerse también en humanos. Por eso mostramos las tres capas por separado." : "Mechanistic and animal data can make a signal scientifically interesting. To support a claim about benefit in people, the evidence also has to hold up in humans. That is why the three layers stay separate."}</div></div>
          </div>
        </motion.div>
      ) : null}
      </AnimatePresence>

      {/* TEXTURE LEGend — how certain is certain */}
      {view.thinEvidence ? (
        <div style={{ display: "flex", gap: 12, alignItems: "flex-start", padding: "14px 18px", borderRadius: 12, marginBottom: 18,
          background: "rgba(245,181,68,0.08)", border: "1px solid rgba(245,181,68,0.35)" }}>
          <AlertTriangle size={17} color={AMBER} style={{ flexShrink: 0, marginTop: 1 }} />
          <div style={{ fontSize: 13.5, lineHeight: 1.6, color: "#E8D9B8" }}>
            {view.thinEvidenceNote || (es ? "Muy pocos estudios pasaron nuestro filtro de calidad para este compuesto; trata la calificación como una señal temprana, no como evidencia establecida." : "Very few studies passed our quality screen for this compound — treat the grade as an early signal, not settled evidence.")}
          </div>
        </div>
      ) : null}

      {/* Explain the compound before asking the reader to interpret grading graphics. */}
      <ExplainerSection ex={ex} view={view} />

      <TextureLegend />

      <SectionHeading index="01" title={es?"Evidencia de un vistazo":"Evidence at a glance"} subtitle={es?"Primero el patrón general: qué resultados están mejor respaldados y dónde la evidencia sigue siendo temprana.":"Start with the pattern: which outcomes are best supported and where the evidence is still early."}/>
      <EvidenceMap outcomes={view.outcomes} ex={ex} />

      <SectionHeading index="02" title={es?"Pregunta a Clarity":"Ask Clarity"} subtitle={es?"Haz una pregunta específica y Clarity buscará únicamente dentro de los estudios y datos calificados de este compuesto.":"Ask a specific question and Clarity will search only within this compound's graded studies and evidence data."}/>
      <AskClarity topic={view.name} category={view.cat} compoundName={view.name} outcomes={view.outcomes} />

      {ex && ex.evidence_base ? (
        <div style={{ marginBottom: 30 }}>
          <div style={{ color:"#C9D5E4", fontSize:14, fontWeight:650, marginBottom:8 }}>{es ? "La investigación que lo respalda" : "The research behind it"}</div>
          <div style={{ color: "#C6D2E2", fontSize: 15, lineHeight: 1.8, letterSpacing: 0.01 }}>{ex.evidence_base}</div>
        </div>
      ) : null}

      <SectionHeading index="03" title={es?"Evidencia detallada por resultado":"Detailed evidence by outcome"} subtitle={es?"Aquí aparecen las capas de evidencia, estimaciones de efecto, limitaciones y estudios individuales detrás de cada resultado.":"Inspect evidence layers, effect estimates, limitations, and the individual studies behind each outcome."}/>
      <FigureModeContext.Provider value={figMode}>
      <HoverContext.Provider value={hoverState}>
      <div style={{ marginBottom: 22 }}>
        <FigureSwitcher />

        {/* Layer legend */}
        <div style={{ fontSize: 12.5, color: "#8B9AB6", lineHeight: 1.5, marginBottom: 10, maxWidth: 640 }}>
          {es ? <>Cada barra muestra cuánta <em>fuerza de evidencia</em> (0–100) existe en cada etapa de investigación. Para alcanzar una calificación alta, la evidencia debe sostenerse en personas; una barra alta en células o animales con una barra humana baja significa que el efecto aún no se ha demostrado en humanos.</> : <>Each bar shows how much <em>evidence strength</em> (0–100) exists at each research stage. Evidence has to hold up in people to reach a high grade — a tall test-tube or animal bar with a short human bar means the effect hasn't been proven in humans yet.</>}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "center", marginBottom: 22, fontFamily: MONO, fontSize: 11.5, color: MUTE }}>
          <span style={{ display: "flex", alignItems: "center", gap: 7 }}><span style={{ width: 9, height: 9, borderRadius: 2, background: "#6FA8F2" }} />{es ? "TUBO DE ENSAYO — células y química" : "TEST TUBE — cells and chemistry"}</span>
          <span style={{ color: "#3D4B63" }}>→</span>
          <span style={{ display: "flex", alignItems: "center", gap: 7 }}><span style={{ width: 9, height: 9, borderRadius: 2, background: VIOLET }} />{es ? "ANIMAL — ratones y ratas" : "ANIMAL — mice and rats"}</span>
          <span style={{ color: "#3D4B63" }}>→</span>
          <span style={{ display: "flex", alignItems: "center", gap: 7 }}><span style={{ width: 9, height: 9, borderRadius: 2, background: TEAL }} />{es ? "HUMANO — personas, idealmente muchas" : "HUMAN — people, ideally many"}</span>
        </div>

        {proven.map((o) => <OutcomeGraphicCard key={o.outcome} o={o} detail={findDetail(ex, o.outcome)} />)}
        {promising.map((o) => <OutcomeGraphicCard key={o.outcome} o={o} detail={findDetail(ex, o.outcome)} />)}
      </div>
      </HoverContext.Provider>
      </FigureModeContext.Provider>

      {(view.chemistry || view.pharmacokinetics) ? <SectionHeading index="04" title={es?"Identidad química y farmacocinética":"Chemistry & pharmacokinetics"} subtitle={es?"Datos técnicos verificados y, cuando existen, parámetros farmacocinéticos con fuente. Esta sección describe el compuesto; no demuestra eficacia.":"Verified technical identity and, when available, sourced pharmacokinetic parameters. This section describes the compound; it does not establish efficacy."}/> : null}
      <ChemistryBlock chem={view.chemistry} meaning={ex && ex.chem_meaning} />
      <PharmacokineticsBlock pk={view.pharmacokinetics} />

      {ex && ex.open_questions ? (
        <div style={{ borderTop:`1px solid rgba(154,140,245,.20)`, padding:"16px 0 6px", marginBottom:14 }}>
          <div style={{ color: VIOLET, fontSize:14, fontWeight:650, marginBottom:7 }}>{es ? "Lo que todavía no sabemos" : "What we still don't know"}</div>
          <div style={{ color: "#C6D2E2", fontSize: 13.5, lineHeight: 1.7 }}>{ex.open_questions}</div>
        </div>
      ) : null}

      <AppraisalSection ap={appraisalPick} />

      <WhereToBuy name={view.name} tier={view.tier} tierColor={view.tierColor} category={view.cat} />

      <div style={{ borderTop: `0.5px solid ${LINE}`, paddingTop: 14, marginTop: 34, color: "#5A6B87", fontSize: 11, textAlign: "center", lineHeight: 1.6 }}>
        {ex ? (es ? "Explicación generada por IA a partir de la evidencia calificada · " : "Explanation AI-generated from the graded evidence · ") : ""}{es ? "calificaciones y gráficos basados en evidencia de PubMed + Europe PMC · investigación y educación, no consejo médico" : "grades & charts from PubMed + Europe PMC evidence · research & education, not medical advice"}
      </div>
    </div>
  );
}

// Expandable study card
// Legacy profile/regimen prototype removed from the production bundle.

function GuideLanguageToggle({ langState }) {
  return (
    <div style={{ display: "flex", gap: 4, padding: 3, borderRadius: 10, border: `1px solid ${LINE}`, background: "rgba(255,255,255,0.025)" }}>
      {[["en", "EN"], ["es", "ES"]].map(([code, label]) => (
        <motion.button key={code} whileTap={{ scale: 0.94 }} onClick={() => langState[1](code)} style={{ border: "none", cursor: "pointer", padding: "5px 9px", borderRadius: 7, fontFamily: MONO, fontSize: 10.5, fontWeight: 700, position:"relative", overflow:"hidden",
          color: langState[0] === code ? INK : MUTE, background: "transparent" }}>
          {langState[0] === code ? <motion.span layoutId="guide-language-active" transition={MOTION_SPRING} style={{ position:"absolute", inset:0, borderRadius:7, background:TEAL, zIndex:0 }} /> : null}
          <span style={{ position:"relative", zIndex:1 }}>{label}</span>
        </motion.button>
      ))}
    </div>
  );
}

function TopNavLinks({ active, onHome, onResearch, onLearn, lang="en" }) {
  const es=lang==="es";
  const items=[
    ["home",es?"Inicio":"Home",onHome],
    ["research",es?"Investigar":"Research",onResearch],
    ["learn",es?"Aprender":"Learn",onLearn],
  ];
  return <nav className="desktop-top-nav" aria-label={es?"Navegación principal":"Primary navigation"} style={{display:"flex",alignItems:"center",gap:4}}>
    {items.map(([k,label,fn])=><button key={k} onClick={()=>fn?.()} aria-current={active===k?"page":undefined} style={{border:0,background:"transparent",cursor:"pointer",padding:"7px 10px",borderRadius:8,color:active===k?TEAL:MUTE,fontSize:11.5,fontWeight:active===k?650:500,borderBottom:`1px solid ${active===k?TEAL:"transparent"}`}}>{label}</button>)}
  </nav>;
}

function GuideTopBar({ langState, onResearch, onHome, onLearn, active="home" }) {
  const c = guideCopy(langState[0]);
  return (
    <motion.div initial={{ opacity:0, y:-10 }} animate={{ opacity:1, y:0 }} transition={{ duration:.4, ease:MOTION_EASE }} style={{ height: 54, borderBottom: `1px solid ${LINE}`, padding: "0 22px", display: "flex", alignItems: "center", gap: 11, position: "sticky", top: 0, background: `${INK}F3`, backdropFilter: "blur(10px)", zIndex: 30 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <div style={{ width: 27, height: 27, borderRadius: 8, background: `linear-gradient(135deg,${TEAL},${TEAL_DIM})`, display: "grid", placeItems: "center" }}><Activity size={15} color={INK} strokeWidth={2.6}/></div>
        <span style={{ fontWeight: 800, letterSpacing: -0.4, fontSize: 16 }}>Clarity</span>
        <span className="guide-tagline" style={{ paddingLeft: 11, borderLeft: `1px solid ${LINE}`, fontSize: 12, color: MUTE }}>{c.top_tagline}</span>
      </div>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
        <TopNavLinks active={active} onHome={onHome} onResearch={()=>onResearch?.(null,null)} onLearn={()=>onLearn?.("basics")} lang={langState[0]} />
        <GuideLanguageToggle langState={langState} />
      </div>
    </motion.div>
  );
}

function GuideRouteCard({ icon: Icon, title, body, cta, color, onClick }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.button
      initial={reduceMotion ? false : { opacity:0, y:16 }}
      whileInView={{ opacity:1, y:0 }} viewport={{ once:true, amount:.25 }}
      whileHover={reduceMotion ? undefined : { y: -3, boxShadow: `0 14px 38px ${color}10` }}
      whileTap={reduceMotion ? undefined : { scale: 0.985 }}
      transition={MOTION_SPRING} onClick={onClick}
      style={{ minHeight: 190, textAlign: "left", padding: "20px 20px 18px", borderRadius: 16, border: `1px solid ${color}28`, background: `linear-gradient(145deg,${color}07,rgba(255,255,255,0.009))`, color: TEXT, cursor: "pointer", display: "flex", flexDirection: "column", overflow:"hidden", position:"relative" }}>
      <motion.div variants={{ hover:{ scale:1.08, rotate:-3 } }} style={{ width: 38, height: 38, display: "grid", placeItems: "center", borderRadius: 11, background: `${color}17`, border: `1px solid ${color}40`, marginBottom: 18 }}><Icon size={19} color={color}/></motion.div>
      <div style={{ fontSize: 17, fontWeight: 700, letterSpacing: -0.35, marginBottom: 7 }}>{title}</div>
      <div style={{ fontSize: 13, color: "#9DACC2", lineHeight: 1.55 }}>{body}</div>
      <motion.div whileHover={reduceMotion ? undefined : { x:3 }} style={{ marginTop: "auto", paddingTop: 18, fontFamily: MONO, fontSize: 10.5, color }}>{cta} →</motion.div>
    </motion.button>
  );
}

function GoalExploreCard({ goal, copy, onResearch, reduceMotion, gradeVersion }) {
  const [expanded, setExpanded] = useState(false);
  const GoalIcon = goal.icon;
  const visible = expanded ? goal.examples : goal.examples.slice(0, 4);
  return (
    <motion.div
      layout
      whileHover={reduceMotion ? undefined : { y:-6, borderColor:`${goal.color}60`, boxShadow:`0 22px 58px ${goal.color}13` }}
      transition={reduceMotion ? {duration:0} : MOTION_SPRING}
      style={{ position:"relative", overflow:"hidden", padding:18, borderRadius:17, border:`1px solid ${LINE}`, background:"linear-gradient(145deg,rgba(255,255,255,.034),rgba(255,255,255,.015))" }}>
      <div aria-hidden="true" style={{ position:"absolute", inset:"0 0 auto 0", height:2, background:`linear-gradient(90deg,${goal.color},${goal.color}20,transparent)` }}/>
      <div aria-hidden="true" style={{ position:"absolute", width:150,height:150,right:-70,top:-80,borderRadius:"50%",background:`${goal.color}0D`,filter:"blur(8px)",pointerEvents:"none" }}/>
      <div style={{ position:"relative" }}>
        <div style={{ display:"flex",alignItems:"flex-start",gap:11 }}>
          <motion.div whileHover={reduceMotion ? undefined : { rotate:-4, scale:1.06 }} style={{ width:38,height:38,borderRadius:11,display:"grid",placeItems:"center",background:`${goal.color}13`,border:`1px solid ${goal.color}38`,flexShrink:0 }}><GoalIcon size={19} color={goal.color}/></motion.div>
          <div style={{ minWidth:0,flex:1 }}><div style={{ fontWeight:750,fontSize:15.5 }}>{goal.title}</div><div style={{ color:MUTE,fontSize:11.8,marginTop:3 }}>{goal.sub}</div></div>
          <div style={{ fontFamily:MONO,fontSize:8.5,letterSpacing:1,color:goal.color,border:`1px solid ${goal.color}30`,background:`${goal.color}0A`,borderRadius:999,padding:"4px 7px",whiteSpace:"nowrap" }}>{goal.examples.length} {copy.goal_paths}</div>
        </div>
        <motion.div layout style={{ display:"grid",gridTemplateColumns:"1fr 1fr",gap:7,marginTop:16 }}>
          <AnimatePresence initial={false}>
            {visible.map(([name,cat],idx) => {
              const live = liveTier(name);
              const tier = live?.tier;
              const tc = tier ? (TIER_COLORS[tier] || MUTE) : MUTE;
              return <motion.button key={name} layout initial={reduceMotion ? false : {opacity:0,y:6}} animate={{opacity:1,y:0}} exit={reduceMotion ? undefined : {opacity:0,y:-4}} transition={reduceMotion ? {duration:0} : {duration:.22,delay:expanded ? idx*.025 : 0}}
                whileHover={reduceMotion ? undefined : {y:-2,backgroundColor:`${goal.color}12`}} whileTap={reduceMotion ? undefined : {scale:.98}} onClick={()=>onResearch(name,cat)}
                style={{ minWidth:0,textAlign:"left",display:"flex",alignItems:"center",gap:7,border:`1px solid ${goal.color}30`,background:`${goal.color}08`,color:TEXT,borderRadius:9,padding:"8px 9px",cursor:"pointer" }}>
                <span style={{ width:6,height:6,borderRadius:"50%",background:tier?tc:goal.color,boxShadow:tier?`0 0 0 3px ${tc}12`:"none",flexShrink:0 }}/>
                <span style={{ overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap",fontFamily:MONO,fontSize:9.7,color:goal.color,flex:1 }}>{name}</span>
                {tier ? <span title={`${tier} evidence`} style={{ fontFamily:MONO,fontSize:7.8,color:tc,letterSpacing:.4 }}>{tier.slice(0,3).toUpperCase()}</span> : null}
              </motion.button>;
            })}
          </AnimatePresence>
        </motion.div>
        <div style={{ display:"flex",alignItems:"center",justifyContent:"space-between",gap:10,marginTop:12 }}>
          <button onClick={()=>setExpanded((v)=>!v)} style={{ border:"none",background:"transparent",padding:0,cursor:"pointer",fontFamily:MONO,fontSize:9.5,color:MUTE }}>
            {expanded ? copy.goal_less : `+${goal.examples.length - 4} ${copy.goal_more}`} <span style={{display:"inline-block",transform:`rotate(${expanded?180:0}deg)`,transition:"transform .2s ease"}}>⌄</span>
          </button>
          <div style={{ fontFamily:MONO,fontSize:8.8,color:"#5E6E8A" }}>{copy.goal_open} ↗</div>
        </div>
      </div>
    </motion.div>
  );
}

function HomePage({ langState, onResearch, onLearn, onHome }) {
  const c = guideCopy(langState[0]);
  const reduceMotion = useReducedMotion();
  const [q, setQ] = useState("");
  const [homeGradeVersion, setHomeGradeVersion] = useState(0);
  const inputRef = useRef(null);
  useEffect(() => {
    let alive = true;
    apiFetchCatalog().then((n) => { if (alive && n > 0) setHomeGradeVersion((v) => v + 1); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  const submit = () => {
    const topic = q.trim();
    if (!topic) { inputRef.current?.focus(); return; }
    const match = CATALOG.find((x) => x[0].toLowerCase() === topic.toLowerCase()) || CATALOG.find((x) => x[0].toLowerCase().includes(topic.toLowerCase()));
    onResearch(topic, match ? match[1] : "supplement");
  };
  const goals = [
    { title:c.goal_recovery, sub:c.goal_recovery_sub, icon:Dumbbell, color:TEAL, examples:[["Creatine Monohydrate","supplement"],["Beta-Alanine","supplement"],["Whey Protein","supplement"],["Collagen","supplement"],["BPC-157","peptide"],["TB-500","peptide"]] },
    { title:c.goal_sleep, sub:c.goal_sleep_sub, icon:Moon, color:VIOLET, examples:[["Melatonin","supplement"],["Ashwagandha","herb"],["Magnesium","mineral"],["L-Theanine","nootropic"],["Glycine","amino"],["Valerian Root","herb"]] },
    { title:c.goal_cognitive, sub:c.goal_cognitive_sub, icon:Brain, color:"#5FA8F5", examples:[["Caffeine","supplement"],["L-Theanine","nootropic"],["Bacopa Monnieri","nootropic"],["Citicoline (CDP-Choline)","nootropic"],["Rhodiola Rosea","nootropic"],["Lion's Mane","nootropic"]] },
    { title:c.goal_metabolic, sub:c.goal_metabolic_sub, icon:Activity, color:AMBER, examples:[["Semaglutide","peptide"],["Tirzepatide","peptide"],["Berberine","herb"],["Psyllium Fiber","gut"],["Apple Cider Vinegar","supplement"],["Chromium","mineral"]] },
    { title:c.goal_longevity, sub:c.goal_longevity_sub, icon:Clock, color:"#5FD6D0", examples:[["NMN","longevity"],["NR (Nicotinamide Riboside)","longevity"],["Urolithin A","longevity"],["Spermidine","longevity"],["Fisetin","longevity"],["Rapamycin","longevity"]] },
    { title:c.goal_skin, sub:c.goal_skin_sub, icon:Heart, color:"#F28FB4", examples:[["GHK-Cu","peptide"],["Collagen","supplement"],["Vitamin C","vitamin"],["BPC-157","peptide"],["KPV","peptide"],["AHK-Cu","peptide"]] },
  ];
  return (
    <div style={{ minHeight:"100vh", background:INK, color:TEXT, fontFamily:DISPLAY }}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap'); *{box-sizing:border-box}.guide-search-shell{transition:border-color .28s ease,box-shadow .28s ease,background .28s ease,transform .28s cubic-bezier(.22,1,.36,1)}.guide-search-shell:focus-within{border-color:rgba(52,224,190,.55)!important;box-shadow:0 0 0 1px rgba(52,224,190,.16),0 20px 65px rgba(52,224,190,.10)!important;background:rgba(255,255,255,.062)!important}.motion-link{transition:color .2s ease,transform .2s ease}.motion-link:hover{color:${TEAL}!important;transform:translateX(2px)}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}.guide-search-shell{transition:none}} @media(max-width:980px) and (min-width:721px){.guide-goals{grid-template-columns:repeat(2,1fr)!important}}@media(max-width:720px){.guide-hero-title{font-size:42px!important}.guide-routes{grid-template-columns:1fr!important}.guide-goals{grid-template-columns:1fr!important}.guide-evidence{grid-template-columns:1fr!important}.guide-compare{grid-template-columns:1fr!important}.guide-tagline{display:none}}`}</style>
      <GuideTopBar langState={langState} onResearch={onResearch} onHome={onHome} onLearn={onLearn} active="home"/>
      <motion.div aria-hidden="true" animate={reduceMotion ? undefined : { x:[-14,14,-14], scale:[1,1.045,1], opacity:[.72,1,.72] }} transition={reduceMotion ? undefined : { duration:14, repeat:Infinity, ease:"easeInOut" }} style={{ position:"fixed", top:-220, left:"50%", marginLeft:-500, width:1000, height:500, background:"radial-gradient(ellipse,rgba(52,224,190,.12),rgba(52,224,190,0) 68%)", filter:"blur(34px)", pointerEvents:"none" }}/>
      <main style={{ maxWidth:1120, margin:"0 auto", padding:"0 22px 110px", position:"relative" }}>
        <motion.section initial={reduceMotion ? false : "hidden"} animate="show" variants={{ hidden:{}, show:{ transition:{ staggerChildren:.085, delayChildren:.05 } } }} style={{ textAlign:"center", padding:"86px 0 48px" }}>
          <motion.div variants={{ hidden:{opacity:0,y:12}, show:{opacity:1,y:0,transition:{duration:.48,ease:MOTION_EASE}} }} style={{ fontFamily:MONO, fontSize:10.5, letterSpacing:1.8, color:TEAL, marginBottom:18 }}>{c.home_eyebrow}</motion.div>
          <motion.h1 variants={{ hidden:{opacity:0,y:18,filter:"blur(5px)"}, show:{opacity:1,y:0,filter:"blur(0px)",transition:{duration:.62,ease:MOTION_EASE}} }} className="guide-hero-title" style={{ margin:"0 auto", maxWidth:820, fontSize:62, lineHeight:.98, letterSpacing:-2.8, fontWeight:800 }}>{c.home_title_1}<span style={{ color:TEAL }}>{c.home_title_2}</span></motion.h1>
          <motion.p variants={{ hidden:{opacity:0,y:14}, show:{opacity:1,y:0,transition:{duration:.5,ease:MOTION_EASE}} }} style={{ maxWidth:700, margin:"24px auto 30px", color:"#A9B8CE", fontSize:16, lineHeight:1.65 }}>{c.home_sub}</motion.p>
          <div style={{ maxWidth:680, margin:"0 auto" }}>
            <div style={{ textAlign:"left", fontFamily:MONO, color:MUTE, fontSize:9.5, letterSpacing:1.3, margin:"0 0 7px 6px" }}>{c.search_label}</div>
            <motion.div variants={{ hidden:{opacity:0,y:14,scale:.985}, show:{opacity:1,y:0,scale:1,transition:{duration:.5,ease:MOTION_EASE}} }} className="guide-search-shell" whileHover={reduceMotion ? undefined : { scale:1.004 }} style={{ display:"flex", alignItems:"center", gap:10, padding:"10px 11px 10px 15px", borderRadius:15, background:"rgba(255,255,255,.05)", border:"1px solid rgba(255,255,255,.13)", boxShadow:"0 18px 60px rgba(0,0,0,.2)" }}>
              <Search size={18} color={MUTE}/><input ref={inputRef} value={q} onChange={(e)=>setQ(e.target.value)} onKeyDown={(e)=>e.key==="Enter"&&submit()} placeholder={c.search_placeholder} style={{ flex:1,minWidth:0,border:"none",outline:"none",background:"transparent",color:TEXT,fontFamily:DISPLAY,fontSize:15.5,padding:"6px 0" }}/>
              <motion.button whileHover={reduceMotion ? undefined : { y:-1, scale:1.02 }} whileTap={reduceMotion ? undefined : { scale:.97 }} transition={MOTION_SPRING} onClick={submit} style={{ display:"flex",alignItems:"center",gap:7,border:"none",background:TEAL,color:INK,fontWeight:750,borderRadius:9,padding:"10px 15px",cursor:"pointer" }}><motion.span animate={reduceMotion ? undefined : { rotate:[0,6,0] }} transition={reduceMotion ? undefined : { duration:2.8, repeat:Infinity, repeatDelay:2.5 }} style={{ display:"grid" }}><Sparkles size={15}/></motion.span>{c.search_button}</motion.button>
            </motion.div>
          </div>
        </motion.section>

        <Reveal style={{ marginTop:22 }}>
        <section>
          <div style={{ marginBottom:18 }}><h2 style={{ margin:0,fontSize:27,letterSpacing:-.8 }}>{c.new_here}</h2><p style={{ margin:"7px 0 0",color:MUTE,fontSize:14,lineHeight:1.6,maxWidth:720 }}>{c.new_here_sub}</p></div>
          <div className="guide-routes" style={{ display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:12 }}>
            <GuideRouteCard icon={BookOpen} title={c.route_basics} body={c.route_basics_sub} cta={c.route_basics_cta} color={TEAL} onClick={()=>onLearn("basics")}/>
            <GuideRouteCard icon={Search} title={c.route_compound} body={c.route_compound_sub} cta={c.route_compound_cta} color="#5FA8F5" onClick={()=>inputRef.current?.focus()}/>
            <GuideRouteCard icon={Sparkles} title={c.route_goal} body={c.route_goal_sub} cta={c.route_goal_cta} color={VIOLET} onClick={()=>document.getElementById("explore-goals")?.scrollIntoView({behavior:"smooth"})}/>
            <GuideRouteCard icon={FlaskConical} title={c.route_evidence} body={c.route_evidence_sub} cta={c.route_evidence_cta} color={AMBER} onClick={()=>onLearn("evidence")}/>
          </div>
          <motion.button className="motion-link" whileTap={{ scale:.98 }} onClick={()=>onResearch(null,null)} style={{ display:"block",margin:"20px auto 0",border:"none",background:"transparent",color:MUTE,cursor:"pointer",fontFamily:MONO,fontSize:11 }}>{c.browse_all} →</motion.button>
        </section>
        </Reveal>

        <Reveal>
        <section id="explore-goals" style={{ paddingTop:86 }}>
          <div style={{ fontFamily:MONO,fontSize:10,letterSpacing:1.6,color:VIOLET,marginBottom:9 }}>{c.goals_eyebrow}</div>
          <h2 style={{ margin:0,fontSize:32,letterSpacing:-1 }}>{c.goals_title}</h2><p style={{ color:MUTE,maxWidth:760,lineHeight:1.65,fontSize:14 }}>{c.goals_sub}</p>
          <div className="guide-goals" style={{ display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:12,marginTop:22 }}>
            {goals.map((g,i)=><motion.div key={g.title} initial={reduceMotion ? false : {opacity:0,y:14}} whileInView={{opacity:1,y:0}} viewport={{once:true,amount:.2}} transition={reduceMotion ? {duration:0} : {duration:.46,delay:i*.055,ease:MOTION_EASE}}><GoalExploreCard goal={g} copy={c} onResearch={onResearch} reduceMotion={reduceMotion} gradeVersion={homeGradeVersion}/></motion.div>)}
          </div>
        </section>
        </Reveal>

        <Reveal>
        <section style={{ paddingTop:86 }}>
          <div style={{ fontFamily:MONO,fontSize:10,letterSpacing:1.6,color:TEAL,marginBottom:9 }}>{c.evidence_eyebrow}</div><h2 style={{ margin:0,fontSize:32,letterSpacing:-1 }}>{c.evidence_title}</h2><p style={{ color:MUTE,maxWidth:800,lineHeight:1.65,fontSize:14 }}>{c.evidence_sub}</p>
          <div className="guide-evidence" style={{ display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:12,marginTop:22 }}>
            {[[Beaker,c.mech,c.mech_sub,"#5FA8F5"],[Activity,c.animal,c.animal_sub,VIOLET],[Users,c.human,c.human_sub,TEAL]].map(([Ic,title,sub,color],i)=><motion.div key={title} initial={reduceMotion ? false : {opacity:0,y:16,scale:.985}} whileInView={{opacity:1,y:0,scale:1}} viewport={{once:true,amount:.25}} transition={reduceMotion ? {duration:0} : {duration:.5,delay:i*.09,ease:MOTION_EASE}} whileHover={reduceMotion ? undefined : {y:-5,scale:1.008}} style={{ padding:"22px 20px",borderRadius:16,border:`1px solid ${color}38`,background:`linear-gradient(180deg,${color}0B,rgba(255,255,255,.012))` }}><motion.div initial={reduceMotion ? false : {opacity:.4}} whileInView={{opacity:1}} transition={{delay:.15+i*.09}} style={{ fontFamily:MONO,fontSize:9.5,color,letterSpacing:1.2,marginBottom:12 }}>0{i+1}</motion.div><motion.div whileHover={reduceMotion ? undefined : {scale:1.08,rotate:-3}} style={{display:"inline-grid"}}><Ic size={20} color={color}/></motion.div><div style={{ fontSize:18,fontWeight:700,marginTop:13 }}>{title}</div><div style={{ color:"#A9B8CE",fontSize:13,lineHeight:1.58,marginTop:7 }}>{sub}</div></motion.div>)}
          </div>
          <motion.button className="motion-link" whileTap={{scale:.98}} onClick={()=>onLearn("evidence")} style={{ marginTop:18,border:"none",background:"transparent",color:TEAL,cursor:"pointer",fontFamily:MONO,fontSize:11 }}>{c.evidence_cta} →</motion.button>
        </section>
        </Reveal>

        <Reveal>
        <section style={{ paddingTop:86 }}>
          <div style={{ padding:"28px",borderRadius:20,border:`1px solid ${LINE}`,background:"linear-gradient(135deg,rgba(154,140,245,.06),rgba(52,224,190,.045))" }}>
            <div style={{ fontFamily:MONO,fontSize:10,letterSpacing:1.6,color:AMBER,marginBottom:9 }}>{c.compare_eyebrow}</div><h2 style={{ margin:0,fontSize:29,letterSpacing:-.9 }}>{c.compare_title}</h2><p style={{ color:MUTE,maxWidth:760,lineHeight:1.65,fontSize:14 }}>{c.compare_sub}</p>
            <div className="guide-compare" style={{ display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginTop:20 }}>
              {[ ["Semaglutide",c.compare_human,TEAL], ["BPC-157",c.compare_preclinical,VIOLET] ].map(([name,label,color])=><motion.button key={name} whileHover={reduceMotion ? undefined : {y:-4,scale:1.008,boxShadow:`0 16px 48px ${color}12`}} whileTap={reduceMotion ? undefined : {scale:.985}} transition={MOTION_SPRING} onClick={()=>onResearch(name,"peptide")} style={{ textAlign:"left",padding:"18px 19px",borderRadius:14,border:`1px solid ${color}40`,background:`${color}0B`,cursor:"pointer",color:TEXT }}><div style={{ fontFamily:MONO,fontSize:9.5,color,letterSpacing:1.1 }}>{label.toUpperCase()}</div><div style={{ fontSize:22,fontWeight:750,marginTop:6 }}>{name}</div><motion.div animate={reduceMotion ? undefined : {x:[0,2,0]}} transition={reduceMotion ? undefined : {duration:2.4,repeat:Infinity,repeatDelay:2}} style={{ color:MUTE,fontSize:12,marginTop:8 }}>{c.open_profile} →</motion.div></motion.button>)}
            </div>
          </div>
        </section>
        </Reveal>
      </main>
    </div>
  );
}

function LearnPage({ langState, initialSection, onResearch, onHome, onLearn }) {
  const c = guideCopy(langState[0]);
  const reduceMotion = useReducedMotion();
  useEffect(()=>{ jumpToPageTop(); },[initialSection]);
  const steps=[[Beaker,c.step_mechanism,c.step_mechanism_sub,"#5FA8F5"],[FlaskConical,c.step_cells,c.step_cells_sub,"#5FA8F5"],[Activity,c.step_animals,c.step_animals_sub,VIOLET],[Users,c.step_humans,c.step_humans_sub,TEAL],[Shield,c.step_rct,c.step_rct_sub,AMBER],[TrendingUp,c.step_synthesis,c.step_synthesis_sub,TEAL]];
  return <div style={{ minHeight:"100vh",background:INK,color:TEXT,fontFamily:DISPLAY }}>
    <style>{`@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap'); *{box-sizing:border-box}.learn-anchor{scroll-margin-top:74px}@media(max-width:760px){.learn-title{font-size:40px!important}.learn-grid2{grid-template-columns:1fr!important}.learn-steps{grid-template-columns:1fr!important}.guide-tagline{display:none}}`}</style>
    <GuideTopBar langState={langState} onResearch={onResearch} onHome={onHome} onLearn={onLearn} active="learn"/>
    <main style={{ maxWidth:1050,margin:"0 auto",padding:"72px 22px 120px" }}>
      <section id="learn-basics" className="learn-anchor">
        <div style={{ fontFamily:MONO,fontSize:10.5,letterSpacing:1.7,color:TEAL,marginBottom:12 }}>{c.basics_eyebrow}</div><h1 className="learn-title" style={{ margin:0,fontSize:54,lineHeight:1.02,letterSpacing:-2,maxWidth:760 }}>{c.basics_title}</h1><p style={{ color:"#A9B8CE",fontSize:15,lineHeight:1.7,maxWidth:750 }}>{c.basics_sub}</p>
        <div className="learn-grid2" style={{ display:"grid",gridTemplateColumns:"1fr 1fr",gap:13,marginTop:28 }}>
          <motion.div initial={reduceMotion?false:{opacity:0,y:14}} whileInView={{opacity:1,y:0}} viewport={{once:true,amount:.25}} whileHover={reduceMotion?undefined:{y:-4}} transition={MOTION_SPRING} style={{ padding:23,borderRadius:17,border:`1px solid ${VIOLET}40`,background:`${VIOLET}0A` }}><div style={{ display:"flex",gap:10,alignItems:"center",marginBottom:12 }}><Beaker size={19} color={VIOLET}/><h3 style={{ margin:0,fontSize:19 }}>{c.peptides_title}</h3></div><p style={{ margin:0,color:"#A9B8CE",fontSize:13.5,lineHeight:1.7 }}>{c.peptides_body}</p></motion.div>
          <motion.div initial={reduceMotion?false:{opacity:0,y:14}} whileInView={{opacity:1,y:0}} viewport={{once:true,amount:.25}} whileHover={reduceMotion?undefined:{y:-4}} transition={{...MOTION_SPRING,delay:.05}} style={{ padding:23,borderRadius:17,border:`1px solid ${TEAL}40`,background:`${TEAL}08` }}><div style={{ display:"flex",gap:10,alignItems:"center",marginBottom:12 }}><Sparkles size={19} color={TEAL}/><h3 style={{ margin:0,fontSize:19 }}>{c.supplements_title}</h3></div><p style={{ margin:0,color:"#A9B8CE",fontSize:13.5,lineHeight:1.7 }}>{c.supplements_body}</p></motion.div>
        </div>
      </section>

      <section id="learn-evidence" className="learn-anchor" style={{ paddingTop:90 }}>
        <div style={{ fontFamily:MONO,fontSize:10.5,letterSpacing:1.7,color:VIOLET,marginBottom:10 }}>{c.research_eyebrow}</div><h2 style={{ margin:0,fontSize:34,letterSpacing:-1.2 }}>{c.research_title}</h2><p style={{ color:MUTE,fontSize:14,lineHeight:1.65,maxWidth:800 }}>{c.research_sub}</p>
        <div className="learn-steps" style={{ display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:11,marginTop:24 }}>
          {steps.map(([Ic,title,sub,color],i)=><motion.div key={title} initial={reduceMotion?false:{opacity:0,y:15}} whileInView={{opacity:1,y:0}} viewport={{once:true,amount:.2}} whileHover={reduceMotion?undefined:{y:-4,borderColor:`${color}50`}} transition={reduceMotion?{duration:0}:{duration:.48,delay:i*.055,ease:MOTION_EASE}} style={{ padding:19,borderRadius:14,border:`1px solid ${LINE}`,background:"rgba(255,255,255,.02)" }}><div style={{ display:"flex",justifyContent:"space-between",alignItems:"center" }}><motion.div whileHover={reduceMotion?undefined:{scale:1.08,rotate:-3}} style={{ width:34,height:34,display:"grid",placeItems:"center",borderRadius:9,background:`${color}10`,border:`1px solid ${color}35` }}><Ic size={17} color={color}/></motion.div><span style={{ fontFamily:MONO,fontSize:9,color:MUTE }}>0{i+1}</span></div><div style={{ fontSize:16,fontWeight:700,marginTop:14 }}>{title}</div><div style={{ color:"#9DACC2",fontSize:12.5,lineHeight:1.55,marginTop:6 }}>{sub}</div></motion.div>)}
        </div>

        <div className="learn-grid2" style={{ display:"grid",gridTemplateColumns:"1fr 1fr",gap:13,marginTop:28 }}>
          <div style={{ padding:23,borderRadius:17,border:`1px solid ${VIOLET}45`,background:`linear-gradient(180deg,${VIOLET}0C,rgba(255,255,255,.015))` }}><div style={{ fontFamily:MONO,fontSize:9.5,color:VIOLET,letterSpacing:1.3,marginBottom:9 }}>PRECLINICAL</div><h3 style={{ margin:"0 0 9px",fontSize:20 }}>{c.animal_value_title}</h3><p style={{ color:"#A9B8CE",fontSize:13.5,lineHeight:1.7,margin:0 }}>{c.animal_value_body}</p><div style={{ margin:"18px 0",borderTop:`1px solid ${VIOLET}25` }}/><h3 style={{ margin:"0 0 9px",fontSize:17 }}>{c.animal_limit_title}</h3><p style={{ color:"#A9B8CE",fontSize:13,lineHeight:1.65,margin:0 }}>{c.animal_limit_body}</p></div>
          <div style={{ padding:23,borderRadius:17,border:`1px solid ${TEAL}45`,background:`linear-gradient(180deg,${TEAL}0A,rgba(255,255,255,.015))` }}><div style={{ fontFamily:MONO,fontSize:9.5,color:TEAL,letterSpacing:1.3,marginBottom:9 }}>HUMAN</div><h3 style={{ margin:"0 0 9px",fontSize:20 }}>{c.human_value_title}</h3><p style={{ color:"#A9B8CE",fontSize:13.5,lineHeight:1.7,margin:0 }}>{c.human_value_body}</p><div style={{ margin:"18px 0",borderTop:`1px solid ${TEAL}25` }}/><h3 style={{ margin:"0 0 9px",fontSize:17 }}>{c.clarity_rule}</h3><p style={{ color:"#A9B8CE",fontSize:13,lineHeight:1.65,margin:0 }}>{c.clarity_rule_body}</p></div>
        </div>
      </section>

      <section id="learn-tiers" className="learn-anchor" style={{ paddingTop:90 }}>
        <div style={{ fontFamily:MONO,fontSize:10.5,letterSpacing:1.7,color:AMBER,marginBottom:10 }}>{c.tiers_eyebrow}</div><h2 style={{ margin:0,fontSize:34,letterSpacing:-1.2,maxWidth:850 }}>{c.tiers_title}</h2><p style={{ color:MUTE,fontSize:14,lineHeight:1.65,maxWidth:800 }}>{c.tiers_sub}</p>
        <div style={{ marginTop:22 }}><TextureLegend/></div>
        <div style={{ marginTop:12,padding:"20px 22px",borderRadius:15,border:`1px solid ${AMBER}35`,background:`${AMBER}08`,display:"flex",gap:14,alignItems:"flex-start" }}><AlertTriangle size={19} color={AMBER} style={{ flexShrink:0,marginTop:2 }}/><div><div style={{ fontWeight:700,fontSize:16 }}>{c.score_title}</div><div style={{ color:"#A9B8CE",fontSize:13,lineHeight:1.65,marginTop:5 }}>{c.score_body}</div></div></div>
      </section>

      <section style={{ paddingTop:80 }}><div style={{ textAlign:"center",padding:"36px 24px",borderRadius:20,border:`1px solid ${TEAL}35`,background:"linear-gradient(135deg,rgba(52,224,190,.07),rgba(154,140,245,.04))" }}><BookOpen size={24} color={TEAL}/><h2 style={{ fontSize:28,margin:"13px 0 7px" }}>{c.ready_title}</h2><p style={{ color:MUTE,fontSize:14,lineHeight:1.65,maxWidth:680,margin:"0 auto 20px" }}>{c.ready_sub}</p><motion.button whileHover={reduceMotion?undefined:{y:-2,scale:1.02}} whileTap={reduceMotion?undefined:{scale:.97}} transition={MOTION_SPRING} onClick={()=>onResearch(null,null)} style={{ border:"none",background:TEAL,color:INK,borderRadius:10,padding:"11px 17px",fontWeight:750,cursor:"pointer" }}>{c.ready_cta} →</motion.button></div></section>
    </main>
  </div>;
}

// ============================================================
//  CLARITY — unified app shell with tab navigation
//  Research tab = evidence catalog + profiles
//  My Regimen tab = personal stack + passive tracking loop
// ============================================================
function PolicyPage({ kind, onHome, onMethodology }) {
  const [lang] = React.useContext(LangContext);
  const es = lang === "es";
  const privacy = kind === "privacy";
  const title = privacy ? (es ? "Privacidad" : "Privacy") : (es ? "Términos y aviso médico" : "Terms & medical notice");
  const eyebrow = privacy ? "PRIVACY" : "TERMS";
  const blocks = privacy ? (es ? [
    ["Datos que usa Clarity", "No necesitas una cuenta para leer perfiles. El servidor recibe datos técnicos normales de una solicitud web, y el proveedor de alojamiento puede conservar registros operativos según su propia política."],
    ["Pregunta a Clarity", "Las preguntas simples pueden responderse localmente desde el perfil. Para preguntas interpretativas, Clarity puede enviar tu pregunta junto con un paquete pequeño de evidencia recuperada a un proveedor externo de modelos de lenguaje. No incluyas nombres, identificadores ni información médica personal que no sea necesaria."],
    ["Qué almacenamos", "Por defecto, Clarity no guarda el texto de tu pregunta ni la respuesta. Conservamos metadatos técnicos de calidad, un hash unidireccional de la consulta, el compuesto, cobertura, número de estudios recuperados y, si lo envías, si la respuesta fue útil. El texto bruto solo se almacenaría si el operador habilita explícitamente CLARITY_STORE_ASK_TEXT y actualiza esta política."],
    ["Evidencia científica", "Tus mensajes nunca se incorporan automáticamente al conjunto de evidencia ni cambian una calificación científica. Las calificaciones provienen del pipeline de literatura, no de afirmaciones de usuarios."],
  ] : [
    ["Data Clarity uses", "You do not need an account to read profiles. The server receives ordinary technical data required for a web request, and the hosting provider may retain operational logs under its own policies."],
    ["Ask Clarity", "Simple questions can be answered locally from the profile. For interpretive questions, Clarity may send your question together with a compact retrieved evidence packet to an external language-model provider. Do not include names, identifiers, or unnecessary personal medical information."],
    ["What we store", "By default, Clarity does not store your raw question or answer text. We keep technical quality metadata, a one-way query hash, compound, coverage, number of retrieved studies, and—if you submit it—helpful/not-helpful feedback. Raw text would only be stored if the operator explicitly enables CLARITY_STORE_ASK_TEXT and updates this policy."],
    ["Scientific evidence", "Your messages never automatically enter the evidence base or change a scientific grade. Grades come from the literature pipeline, not from user claims."],
  ]) : (es ? [
    ["Investigación y educación", "Clarity resume literatura científica para investigación y educación. No diagnostica, prescribe ni sustituye a un profesional sanitario que conozca tu historia clínica."],
    ["No es un servicio de emergencia", "No uses Clarity para una emergencia médica ni para decidir si debes retrasar atención urgente."],
    ["Limitaciones de la evidencia", "La literatura puede ser incompleta, estar mal indexada o cambiar con nuevos estudios. La clasificación automática está informada por principios de GRADE, pero no equivale a una revisión GRADE manual por un panel de expertos."],
    ["Afiliados", "Clarity puede recibir una comisión cuando compras mediante enlaces de afiliado claramente identificados. La relación comercial no modifica el pipeline de calificación. Los enlaces de compra de péptidos permanecen separados de la evaluación científica y llevan su divulgación correspondiente."],
    ["Decisiones personales", "Verifica las fuentes y consulta a un profesional cualificado antes de usar un compuesto, especialmente si tienes una condición médica, estás embarazada, tomas medicamentos o consideras una sustancia de investigación."],
  ] : [
    ["Research and education", "Clarity summarizes scientific literature for research and educational use. It does not diagnose, prescribe, or replace a clinician who knows your medical history."],
    ["Not an emergency service", "Do not use Clarity for a medical emergency or to decide whether to delay urgent care."],
    ["Evidence limitations", "The literature can be incomplete, misindexed, or change as new studies appear. Clarity's automated framework is informed by GRADE principles, but it is not a formal expert-panel GRADE review."],
    ["Affiliate relationships", "Clarity may earn a commission when you purchase through clearly disclosed affiliate links. Commercial relationships do not alter the grading pipeline. Peptide purchase links remain separate from the scientific assessment and carry their own disclosure."],
    ["Personal decisions", "Verify the sources and consult a qualified professional before using a compound, especially if you have a medical condition, are pregnant, take medications, or are considering a research substance."],
  ]);
  return <div style={{ minHeight:"100vh", background:INK, color:TEXT, fontFamily:DISPLAY }}>
    <header style={{ position:"sticky",top:0,zIndex:40,display:"flex",alignItems:"center",gap:12,padding:"12px 20px",background:"rgba(10,13,20,.92)",backdropFilter:"blur(14px)",borderBottom:`1px solid ${LINE}` }}>
      <button onClick={onHome} aria-label={es?"Volver a inicio":"Back home"} style={{ width:34,height:34,borderRadius:10,border:`1px solid ${LINE}`,background:PANEL2,color:TEXT,cursor:"pointer",display:"grid",placeItems:"center" }}><ArrowLeft size={16}/></button>
      <div style={{ width:28,height:28,borderRadius:8,background:`linear-gradient(135deg,${TEAL},#1B7A6C)`,display:"grid",placeItems:"center" }}><Activity size={15} color={INK}/></div>
      <div style={{fontWeight:750}}>Clarity</div><span style={{color:"#3B4960"}}>|</span><span style={{fontSize:12,color:MUTE}}>{title}</span>
    </header>
    <main style={{ maxWidth:850, margin:"0 auto", padding:"68px 24px 150px" }}>
      <div style={{fontFamily:MONO,fontSize:10.5,letterSpacing:1.6,color:TEAL,marginBottom:10}}>{eyebrow}</div>
      <h1 style={{margin:"0 0 12px",fontSize:42,letterSpacing:-1.5}}>{title}</h1>
      <p style={{margin:"0 0 34px",maxWidth:690,color:MUTE,lineHeight:1.7,fontSize:14}}>{privacy ? (es?"Cómo maneja Clarity las preguntas y los datos técnicos del producto.":"How Clarity handles questions and product telemetry.") : (es?"Condiciones básicas para usar Clarity como recurso de evidencia.":"The basic conditions for using Clarity as an evidence resource.")}</p>
      <div style={{display:"flex",flexDirection:"column",gap:12}}>{blocks.map(([h,b])=><section key={h} style={{padding:"20px 22px",borderRadius:15,border:`1px solid ${LINE}`,background:"rgba(255,255,255,.02)"}}><h2 style={{fontSize:17,margin:"0 0 7px"}}>{h}</h2><p style={{fontSize:13.5,lineHeight:1.72,color:"#A9B8CE",margin:0}}>{b}</p></section>)}</div>
      <div style={{marginTop:24,padding:"17px 19px",borderRadius:14,border:`1px solid ${TEAL}25`,background:`${TEAL}06`,fontSize:12.5,lineHeight:1.65,color:"#9FB1C7"}}>{es?"Para entender exactamente cómo se recuperan y califican los estudios, consulta la metodología.":"For exactly how studies are retrieved and graded, read the methodology."} <button onClick={onMethodology} style={{border:0,background:"transparent",color:TEAL,cursor:"pointer",padding:0,fontWeight:700}}>{es?"Ver metodología":"View methodology"} →</button></div>
    </main>
  </div>;
}

export default function Clarity() {
  const initialRouteRef = useRef(null);
  if (!initialRouteRef.current) initialRouteRef.current = parseBrowserRoute();
  const initialRoute = initialRouteRef.current;
  const [tab, setTab] = useState(initialRoute.tab || "home");
  const reduceMotion = useReducedMotion();
  const langState = useState(() => {
    try { return localStorage.getItem("clarity_lang") || "en"; } catch { return "en"; }
  });
  useEffect(() => {
    try { localStorage.setItem("clarity_lang", langState[0]); } catch {}
    if (typeof document !== "undefined") document.documentElement.lang = langState[0] === "es" ? "es" : "en";
  }, [langState[0]]);
  const c = guideCopy(langState[0]);
  const requestSeq = useRef(initialRoute.request ? 1 : 0);
  const [researchRequest, setResearchRequest] = useState(() => initialRoute.request ? { id:1, ...initialRoute.request } : null);
  const [researchVisited, setResearchVisited] = useState(initialRoute.tab === "research");
  const [learnSection, setLearnSection] = useState(initialRoute.learnSection || "basics");

  const setTitle = (label) => {
    if (typeof document === "undefined") return;
    document.title = label ? `${label} | Clarity` : "Clarity — The Data, Told Straight";
    const description = label
      ? `${label}: graded evidence from PubMed + Europe PMC, with human, animal, and mechanistic evidence kept separate.`
      : "Clarity explains evidence for peptides, supplements, and other compounds using graded PubMed + Europe PMC research.";
    let meta = document.querySelector('meta[name="description"]');
    if (!meta) { meta = document.createElement("meta"); meta.setAttribute("name", "description"); document.head.appendChild(meta); }
    meta.setAttribute("content", description);
    let canonical = document.querySelector('link[rel="canonical"]');
    if (!canonical) { canonical = document.createElement("link"); canonical.setAttribute("rel", "canonical"); document.head.appendChild(canonical); }
    canonical.setAttribute("href", `${window.location.origin}${window.location.pathname}`);
  };

  const goResearch = (topic, category) => {
    jumpToPageTop();
    setResearchVisited(true);
    if (topic) {
      setResearchRequest({ id: ++requestSeq.current, topic, category: category || "supplement" });
      writeBrowserRoute(compoundRoute(topic));
      setTitle(topic);
    } else {
      setResearchRequest({ id: ++requestSeq.current, clear:true });
      writeBrowserRoute("/research");
      setTitle("Research");
    }
    setTab("research");
  };
  const goResearchRoot = () => {
    jumpToPageTop();
    setResearchVisited(true); setResearchRequest({ id:++requestSeq.current, clear:true }); setTab("research");
    writeBrowserRoute("/research"); setTitle("Research");
  };
  const goMethodology = () => {
    jumpToPageTop(); setResearchVisited(true); setResearchRequest({ id:++requestSeq.current, methodology:true }); setTab("research");
    writeBrowserRoute("/methodology"); setTitle("Methodology");
  };
  const goLearn = (section = "basics") => {
    jumpToPageTop(); setLearnSection(section); setTab("learn");
    writeBrowserRoute(section === "evidence" ? "/learn/evidence" : "/learn/basics");
    setTitle(section === "evidence" ? "Evidence guide" : "Learn");
  };
  const goHome = () => { jumpToPageTop(); setTab("home"); writeBrowserRoute("/"); setTitle(null); };
  const goPrivacy = () => { jumpToPageTop(); setTab("privacy"); writeBrowserRoute("/privacy"); setTitle("Privacy"); };
  const goTerms = () => { jumpToPageTop(); setTab("terms"); writeBrowserRoute("/terms"); setTitle("Terms"); };
  const onProfileOpen = (name) => { writeBrowserRoute(compoundRoute(name)); setTitle(name); };

  useEffect(() => {
    const apply = () => {
      const r = parseBrowserRoute();
      jumpToPageTop();
      if (r.tab === "research") {
        setResearchVisited(true); setTab("research");
        setResearchRequest({ id:++requestSeq.current, ...(r.request || {clear:true}) });
        if (r.request?.topic) setTitle(r.request.topic); else if (r.request?.methodology) setTitle("Methodology"); else setTitle("Research");
      } else if (r.tab === "learn") {
        setLearnSection(r.learnSection || "basics"); setTab("learn"); setTitle(r.learnSection === "evidence" ? "Evidence guide" : "Learn");
      } else if (r.tab === "privacy") { setTab("privacy"); setTitle("Privacy"); }
      else if (r.tab === "terms") { setTab("terms"); setTitle("Terms"); }
      else { setTab("home"); setTitle(null); }
    };
    window.addEventListener("popstate", apply);
    apply();
    return () => window.removeEventListener("popstate", apply);
  }, []);

  useEffect(() => { jumpToPageTop(); }, [tab]);

  const tabs = [
    { k:"home", label:c.nav_home, icon:Sparkles },
    { k:"research", label:c.nav_research, icon:BookOpen },
    { k:"learn", label:c.nav_learn, icon:FlaskConical },
  ];

  return (
    <LangContext.Provider value={langState}>
      <div style={{ minHeight:"100vh", background:INK, color:TEXT, fontFamily:DISPLAY }}>
        <style>{`
          :focus-visible{outline:2px solid ${TEAL}!important;outline-offset:3px}
          button:focus-visible,input:focus-visible,a:focus-visible{box-shadow:0 0 0 4px rgba(52,224,190,.12)}
          @media(prefers-reduced-motion:reduce){html{scroll-behavior:auto!important}}
          .mobile-bottom-nav{display:none!important}.desktop-top-nav{display:flex!important}
          @media(max-width:760px){.mobile-bottom-nav{display:flex!important}.desktop-top-nav{display:none!important}.page-with-mobile-dock{padding-bottom:124px!important}}
        `}</style>
        <div className="page-with-mobile-dock" style={{ paddingBottom:40 }}>
          <AnimatePresence mode="popLayout" initial={false}>
            {tab === "home" ? <motion.div key="home-page" style={{width:"100%"}} initial={reduceMotion?false:{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={reduceMotion?undefined:{opacity:0,y:-6}} transition={reduceMotion?{duration:0}:PAGE_TRANSITION}><HomePage langState={langState} onResearch={goResearch} onLearn={goLearn} onHome={goHome}/></motion.div> : null}
            {tab === "learn" ? <motion.div key="learn-page" style={{width:"100%"}} initial={reduceMotion?false:{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={reduceMotion?undefined:{opacity:0,y:-6}} transition={reduceMotion?{duration:0}:PAGE_TRANSITION}><LearnPage langState={langState} initialSection={learnSection} onResearch={goResearch} onHome={goHome} onLearn={goLearn}/></motion.div> : null}
            {tab === "privacy" ? <motion.div key="privacy-page" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}><PolicyPage kind="privacy" onHome={goHome} onMethodology={goMethodology}/></motion.div> : null}
            {tab === "terms" ? <motion.div key="terms-page" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}><PolicyPage kind="terms" onHome={goHome} onMethodology={goMethodology}/></motion.div> : null}
          </AnimatePresence>
          {researchVisited && <motion.div initial={false} animate={tab === "research" ? {opacity:1,y:0} : {opacity:0,y:8}} transition={reduceMotion?{duration:0}:PAGE_TRANSITION} style={{display:tab === "research"?"block":"none",width:"100%",margin:0,padding:0}}><ResearchTab langState={langState} initialRequest={researchRequest} onHome={goHome} onLearn={goLearn} onProfileOpen={onProfileOpen} onResearchRoot={goResearchRoot} onMethodologyOpen={goMethodology}/></motion.div>}

          <footer style={{ maxWidth:960, margin:"56px auto 0", padding:"20px 24px 8px", borderTop:`1px solid ${LINE}`, display:"flex", justifyContent:"center", flexWrap:"wrap", gap:16, fontFamily:MONO, fontSize:10, color:"#667893" }}>
            <a href="/methodology" onClick={(e)=>{e.preventDefault();goMethodology();}} style={{color:"inherit",textDecoration:"none"}}>{langState[0]==="es"?"Metodología":"Methodology"}</a>
            <a href="/privacy" onClick={(e)=>{e.preventDefault();goPrivacy();}} style={{color:"inherit",textDecoration:"none"}}>{langState[0]==="es"?"Privacidad":"Privacy"}</a>
            <a href="/terms" onClick={(e)=>{e.preventDefault();goTerms();}} style={{color:"inherit",textDecoration:"none"}}>{langState[0]==="es"?"Términos":"Terms"}</a>
            <span>{langState[0]==="es"?"Investigación y educación · no consejo médico":"Research & education · not medical advice"}</span>
          </footer>
        </div>

        <div className="mobile-bottom-nav" style={{ position:"fixed",bottom:0,left:0,right:0,zIndex:60,pointerEvents:"none",padding:"0 14px 12px",display:"flex",justifyContent:"center" }}>
          <div style={{pointerEvents:"auto",display:"flex",width:"100%",maxWidth:520,padding:5,gap:4,borderRadius:17,background:"rgba(10,13,20,.88)",backdropFilter:"blur(18px)",WebkitBackdropFilter:"blur(18px)",border:"1px solid rgba(255,255,255,.09)",boxShadow:"0 14px 45px rgba(0,0,0,.42), inset 0 1px 0 rgba(255,255,255,.025)"}}>
            {tabs.map((item)=>{const Ic=item.icon;const on=tab===item.k;return <motion.button key={item.k} whileHover={reduceMotion?undefined:{y:-1}} whileTap={reduceMotion?undefined:{scale:.97}} transition={MOTION_SPRING} aria-current={on ? "page" : undefined} onClick={()=>item.k==="home"?goHome():item.k==="research"?goResearch(null,null):goLearn("basics")} style={{flex:1,position:"relative",display:"flex",alignItems:"center",justifyContent:"center",gap:7,padding:"9px 11px",minHeight:42,border:"none",borderRadius:12,cursor:"pointer",background:"transparent",color:on?TEAL:MUTE,overflow:"hidden"}}>
              {on?<motion.div layoutId="bottom-nav-active-pill" transition={MOTION_SPRING} style={{position:"absolute",inset:0,borderRadius:12,background:"rgba(52,224,190,.095)",border:"1px solid rgba(52,224,190,.22)",boxShadow:"inset 0 0 18px rgba(52,224,190,.03)"}}/>:null}
              <motion.div animate={on&&!reduceMotion?{scale:1.05}:{scale:1}} transition={MOTION_SPRING} style={{display:"grid",position:"relative",zIndex:1}}><Ic size={17} color={on?TEAL:MUTE}/></motion.div><span style={{fontFamily:MONO,fontSize:10,fontWeight:on?700:500,position:"relative",zIndex:1}}>{item.label}</span>
            </motion.button>})}
          </div>
        </div>
      </div>
    </LangContext.Provider>
  );
}
