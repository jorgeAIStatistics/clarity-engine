"""
Stage 2 — Classify each study by evidence weight.

This is deterministic, rule-based classification from PubMed metadata + abstract
text. No LLM needed for the core signal (publication type is the strongest cue).
An LLM can LATER refine population/outcome extraction, but the evidence-hierarchy
logic below is the backbone and is fully transparent + auditable.

Evidence hierarchy (strongest -> weakest):
  systematic_review / meta_analysis  >  rct  >  cohort/observational
  >  case_report  >  animal / in_vitro
"""

import re

# Map PubMed PublicationType strings to our internal design categories.
_DESIGN_BY_PUBTYPE = {
    "meta-analysis": "meta_analysis",
    "systematic review": "systematic_review",
    "randomized controlled trial": "rct",
    "controlled clinical trial": "rct",
    "clinical trial, phase i": "rct",
    "clinical trial, phase ii": "rct",
    "clinical trial, phase iii": "rct",
    "clinical trial, phase iv": "rct",
    "pragmatic clinical trial": "rct",
    "equivalence trial": "rct",
    "adaptive clinical trial": "rct",
    "clinical trial": "trial",
    "clinical trial protocol": "trial",
    "observational study": "observational",
    "cohort studies": "observational",
    "prospective studies": "observational",
    "retrospective studies": "observational",
    "cross-sectional studies": "observational",
    "case-control studies": "observational",
    "longitudinal studies": "observational",
    "follow-up studies": "observational",
    "comparative study": "observational",
    "multicenter study": "observational",
    "twin study": "observational",
    "case reports": "case_report",
    "case report": "case_report",
}

# Fallback: many papers carry ONLY the generic "Journal Article" publication type,
# with the design stated in the abstract text. Without this fallback ~19% of the
# catalog lands as "Unclassified", which weakens the trials table, the critical
# appraisal, and (via design_rank) the grade itself. Ordered strongest-first;
# first match wins.
_DESIGN_BY_TEXT = [
    ("meta_analysis", ("meta-analysis", "meta analysis", "metaanalysis",
                       "pooled analysis of")),
    ("systematic_review", ("systematic review", "scoping review",
                           "prisma", "systematically reviewed")),
    ("rct", ("randomized controlled trial", "randomised controlled trial",
             "randomly assigned", "randomly allocated", "randomized, double-blind",
             "randomised, double-blind", "double-blind, placebo-controlled",
             "double blind placebo controlled", "placebo-controlled trial",
             "randomized crossover", "randomised crossover", "randomized trial",
             "randomised trial", "rct")),
    ("trial", ("open-label trial", "single-arm trial", "pilot trial",
               "clinical trial", "we enrolled", "participants were enrolled",
               "open label study", "intervention study")),
    ("observational", ("cross-sectional", "case-control", "cohort study",
                       "prospective cohort", "retrospective analysis",
                       "observational study", "survey of")),
    ("case_report", ("case report", "we report a case", "a case of")),
]


# Animal-model signals. If any appear, the text fallback must NOT hand back a
# human-trial design — animal studies use identical trial vocabulary ("randomly
# assigned", "double-blind", "placebo-controlled"), and mislabelling them as RCTs
# is how rat data ends up counted as human evidence.
_ANIMAL_TEXT_SIGNALS = (
    # rodents
    "rat", "rats", "mouse", "mice", "murine", "rodent", "hamster", "gerbil",
    "guinea pig", "male wistar", "sprague-dawley", "c57bl", "balb/c",
    # other mammals
    "rabbit", "rabbits", "canine", "dog", "dogs", "porcine", "pig", "pigs",
    "piglet", "bovine", "calf", "cattle", "equine", "horse", "horses", "foal",
    "ovine", "sheep", "lamb", "caprine", "goat", "feline", "cat", "cats",
    "ferret", "primate", "monkey", "monkeys", "macaque", "marmoset", "baboon",
    # birds / fish / invertebrates  (broiler chicken studies were passing as human)
    "chicken", "chickens", "broiler", "poultry", "avian", "hen", "hens",
    "quail", "duck", "turkey", "zebrafish", "fish", "salmon", "trout",
    "drosophila", "c. elegans", "nematode", "xenopus",
    # study framing
    "in vivo animal", "animal model", "animal study", "veterinary",
    "in vitro", "cell culture", "cell line", "cultured cells", "fibroblast",
)


# Methodology phrases that do NOT establish the subjects were non-human.
_NON_AUTHORITATIVE_SIGNALS = {
    "in vitro", "cell culture", "cell line", "cultured cells", "fibroblast",
    "animal model", "animal study", "in vivo animal", "veterinary",
}

# Species terms only — these DO establish non-human subjects.
_SPECIES_SIGNALS = [s for s in _ANIMAL_TEXT_SIGNALS
                    if s not in _NON_AUTHORITATIVE_SIGNALS]

_ANIMAL_SIGNAL_RE = re.compile(
    r"\b(" + "|".join(re.escape(sig) for sig in
                      sorted(_SPECIES_SIGNALS, key=len, reverse=True)) + r")\b")

# Kept for design inference, where a broader net is harmless: an unclassified
# study costs a weaker trials table, not a wrong population.
_ANY_ANIMAL_HINT_RE = re.compile(
    r"\b(" + "|".join(re.escape(sig) for sig in
                      sorted(_ANIMAL_TEXT_SIGNALS, key=len, reverse=True)) + r")\b")


def _has_animal_signal(title, abstract):
    """
    Explicit non-human research signal in the title OR abstract.

    Word-boundary matched: plain substring matching made "pigment" match "pig",
    "when" match "hen" and "indicate" match "cat". Tolerable when this was only
    a design hint; not once it decides population.
    """
    blob = f"{title or ''} {abstract or ''}".lower()
    return bool(_ANIMAL_SIGNAL_RE.search(blob))


def _design_from_text(title, abstract):
    """
    Infer design from title+abstract when publication types are uninformative.
    Returns None for anything showing animal/in-vitro hints: better to leave a
    study Unclassified than to promote a rat study to RCT. Uses the BROAD hint
    set — over-caution here only costs a weaker trials table.
    """
    blob = f"{title or ''} {abstract or ''}".lower()
    if _ANY_ANIMAL_HINT_RE.search(blob):
        return None
    blob = f"{title or ''} {abstract or ''}".lower()
    for design, needles in _DESIGN_BY_TEXT:
        for n in needles:
            if n in blob:
                return design
    return None

# Rank used for sorting / picking the strongest evidence in a cluster.
DESIGN_RANK = {
    "meta_analysis": 6,
    "systematic_review": 6,
    "rct": 5,
    "trial": 4,
    "observational": 3,
    "case_report": 2,
    "animal": 1,
    "in_vitro": 1,
    "unknown": 0,
}

_ANIMAL_HINTS = re.compile(r"\b(rat|rats|mice|mouse|rodent|murine|canine|porcine|feline|bovine|equine|in vitro|in-vitro|cell line|cells?|zebrafish|drosophila|xenograft|explant)\b", re.I)
_HUMAN_HINTS = re.compile(r"\b(patients?|participants?|adults?|men|women|subjects?|volunteers?|humans?|children|infants?)\b", re.I)
# High-signal markers that a study was actually conducted IN humans (not just
# mentioning them). These outweigh a stray "human" reference in an animal paper.
_HUMAN_TRIAL_MARKERS = re.compile(r"\b(randomi[sz]ed|double-blind|placebo-controlled|enrolled|recruited|informed consent|clinical trial|healthy volunteers|in patients with)\b", re.I)
# High-signal markers that the SUBJECTS were animals/models, regardless of any
# human words in the discussion section.
_ANIMAL_MODEL_MARKERS = re.compile(r"\b(male|female)?\s?(wistar|sprague-dawley|c57|balb|nude)\b|\b(animal model|induced in (rats|mice)|(rats|mice) were|administered to (rats|mice)|per kg body weight|intraperitoneal|gastric lesion|paw edema)\b", re.I)


def classify(study):
    """Add design, population, sample_size, and is_review fields to a study dict."""
    types_lower = [t.lower() for t in study.get("publication_types", [])]

    # ---- Non-study / non-evidence detection ---------------------------------
    # PubMed "Review" that is NOT systematic/meta is a narrative review: a POINTER
    # to evidence, not evidence. Editorials, comments, letters, news, biographies,
    # etc. are likewise NOT primary studies. All are tagged is_review so the
    # pipeline drops them from primary grading. Systematic reviews / meta-analyses
    # are KEPT (top evidence tier) even though they also carry "review" in PubMed.
    is_high_tier_review = ("meta-analysis" in types_lower
                           or "systematic review" in types_lower)
    _NON_STUDY_TYPES = {
        "review", "editorial", "comment", "letter", "news", "newspaper article",
        "biography", "historical article", "interview", "published erratum",
        "retraction of publication", "expression of concern", "address",
        "congress", "consensus development conference", "guideline",
        "practice guideline", "patient education handout", "personal narrative",
    }
    has_non_study = any(t in _NON_STUDY_TYPES for t in types_lower)
    is_narrative_review = has_non_study and not is_high_tier_review

    design = "unknown"
    for t in types_lower:
        if t in _DESIGN_BY_PUBTYPE:
            cand = _DESIGN_BY_PUBTYPE[t]
            if DESIGN_RANK[cand] > DESIGN_RANK[design]:
                design = cand

    # Fallback to abstract text when publication types were uninformative
    # (very common: papers tagged only "Journal Article"). Never DOWNgrades a
    # design already established from metadata — only fills genuine gaps.
    if design == "unknown" and not is_narrative_review:
        inferred = _design_from_text(study.get("title", ""), study.get("abstract", ""))
        if inferred:
            design = inferred
            study["design_source"] = "abstract_text"

    text = f"{study.get('title','')} {study.get('abstract','')}"
    title_only = study.get("title", "")

    # ---- Population: decide by WEIGHT of signal, not all-or-nothing ----------
    # The old logic marked animal only if NO human word appeared anywhere — but
    # animal abstracts routinely say "adults", "men", or "implications for humans",
    # so almost every animal study was mis-tagged human. Instead, score both sides.
    animal_generic = len(_ANIMAL_HINTS.findall(text))
    human_generic = len(_HUMAN_HINTS.findall(text))
    has_human_trial = bool(_HUMAN_TRIAL_MARKERS.search(text))
    has_animal_model = bool(_ANIMAL_MODEL_MARKERS.search(text))

    # TITLE OVERRIDE: a species/model term in the TITLE is near-decisive for
    # animal. Papers performed in humans are not titled "...in rats" / "...in a
    # murine model". This beats human BACKGROUND prose in the abstract body
    # (e.g. a rat study whose intro says "safe in healthy volunteers"), which was
    # the residual mis-tagging after reviews/editorials were excluded.
    _TITLE_ANIMAL = re.compile(
        r"\b(rat|rats|mouse|mice|murine|rodent|rabbit|rabbits|dog|dogs|canine|"
        r"porcine|swine|zebrafish|in vitro|in-vitro|cell line|cells)\b", re.I)
    title_is_animal = bool(_TITLE_ANIMAL.search(title_only))

    # Publication type is a strong human signal: RCTs/meta-analyses are human
    # unless the abstract is explicitly an animal model.
    # CRITICAL: only designs from PubMed METADATA count. A design inferred from
    # abstract text must NOT imply human population — animal studies also say
    # "randomly assigned" and "double-blind". Treating inferred designs as human
    # evidence reintroduces the phantom-human bug (rat studies grading as RCTs).
    design_from_metadata = study.get("design_source") != "abstract_text"
    pubtype_is_human = design_from_metadata and design in (
        "rct", "trial", "observational", "meta_analysis", "systematic_review")

    # AUTHORITATIVE ANIMAL OVERRIDE.
    # A study whose abstract says "burned mice" is an animal study, whatever
    # PubMed's publication type says. BPC-157 reached Moderate ("good human
    # evidence") on mouse burn-wound papers because the species word appeared in
    # the abstract rather than the title, so a metadata pubtype of
    # "observational" carried the decision. One detector now governs both design
    # and population instead of two systems disagreeing.
    if _has_animal_signal(study.get("title", ""), study.get("abstract", "")) \
            and not has_human_trial:
        population = "animal"
    elif title_is_animal and not pubtype_is_human:
        # Species in the title, not an explicitly human study design -> animal.
        population = "animal"
    elif has_animal_model and not has_human_trial:
        # Explicit animal-model language with no human-trial structure -> animal.
        population = "animal"
    elif has_human_trial and not title_is_animal:
        # Human-trial structure AND no animal species in the title -> human.
        population = "human"
    elif pubtype_is_human and not has_animal_model:
        population = "human"
    elif animal_generic > human_generic and not has_human_trial:
        # More animal than human signal, no trial structure -> animal.
        population = "animal"
    elif human_generic > 0:
        population = "human"
    else:
        population = "unknown"

    # If we concluded animal, an otherwise-generic design should reflect that.
    if population == "animal":
        # An animal study is never an "RCT" in our taxonomy, however the abstract
        # is worded. Preserve genuine animal meta-analyses/systematic reviews;
        # everything else collapses to animal/in vitro.
        if design in ("unknown", "trial", "rct", "observational", "case_report"):
            design = "animal"

    # Confidence flag: mark cases the keyword logic is genuinely unsure about, so
    # an optional LLM pass can resolve ONLY these (keeping cost/latency minimal).
    # Low-confidence when: population is unknown, OR the two sides conflict
    # (animal-model language AND human-trial language both present), OR there's
    # human generic wording but no strong human OR animal structural signal.
    conflict = has_animal_model and has_human_trial
    weak_human = (population == "human" and not has_human_trial
                  and not pubtype_is_human and not title_is_animal)
    low_confidence = (population == "unknown") or conflict or weak_human

    study["design"] = design
    study["population"] = population
    study["sample_size"] = _extract_sample_size(text)
    study["design_rank"] = DESIGN_RANK.get(design, 0)
    study["is_review"] = is_narrative_review
    study["population_confidence"] = "low" if low_confidence else "high"
    return study


def _extract_sample_size(text):
    """
    Best-effort participant count from an abstract.

    PubMed abstracts report N inconsistently, so this is deliberately layered:
      1. Prefer high-signal enrollment phrasings (N=, randomized/assigned to,
         enrolled, a total of N) — these almost always denote the study sample.
      2. Fall back to 'N <noun>' but only for HUMAN nouns, and take the LARGEST
         plausible match, not the first (the first is often a subgroup, a number
         of trials, a dose, or a duration).
      3. Return None when nothing trustworthy is found — None means 'unknown',
         which the grader treats as unverified precision, NOT as 'small'.

    This will still miss many abstracts (they simply don't state N parseably).
    That honest gap is why 'reviewed_by' exists and why an LLM extraction pass is
    a legitimate later upgrade — extraction from the real text, not fabrication.
    """
    # 1) High-signal enrollment patterns. Collect all, take the max plausible.
    strong = re.findall(
        r"(?:n\s*=\s*|randomi[sz]ed\s+(?:to\s+)?|assigned\s+to\s+|enroll(?:ed|ing)?\s+"
        r"|recruited\s+|a\s+total\s+of\s+|sample\s+of\s+)(\d{2,6})",
        text, re.I,
    )
    candidates = [int(x) for x in strong]

    # 2) Weaker 'N <human-noun>' fallback (humans only — avoid rats/mice inflating n).
    weak = re.findall(
        r"\b(\d{2,6})\s+(?:participants|subjects|patients|adults|men|women|"
        r"volunteers|individuals|healthy\s+(?:adults|volunteers|men|women))\b",
        text, re.I,
    )
    candidates += [int(x) for x in weak]

    # 3) Filter to a plausible human-study range; drop years, doses, p-values, etc.
    candidates = [n for n in candidates if 5 <= n <= 500000]
    if not candidates:
        return None
    # Largest plausible enrollment is the best single estimate of study size.
    return max(candidates)


def classify_all(studies):
    return [classify(s) for s in studies]


if __name__ == "__main__":
    import pubmed
    studies = pubmed._parse_articles(open("tests/sample_pubmed.xml").read())
    for s in classify_all(studies):
        print(f"PMID {s['pmid']}: design={s['design']:18} pop={s['population']:8} n={s['sample_size']}")

# ---------------------------------------------------------------------------
# RELEVANCE + STUDY-TYPE FILTERS
# Two failures found in the catalog that grading logic cannot fix, because they
# are about WHICH studies get graded:
#   1. TB-500's "evidence" included papers never mentioning TB-500 (PubMed
#      matched "TB" as tuberculosis, generic peptide methods papers, etc).
#   2. MOTS-c's "human evidence" was observational studies MEASURING endogenous
#      MOTS-c as a biomarker. Nobody was administered anything. Sick people
#      having lower levels says nothing about whether supplementing helps.
# Both inflate grades with material that isn't intervention evidence.
# ---------------------------------------------------------------------------

# Compound name variants, so relevance checking doesn't reject legitimate papers
# that use the pharmacological name rather than the street name.
_NAME_VARIANTS = {
    "tb-500": ["tb-500", "tb500", "thymosin beta-4", "thymosin beta 4", "tβ4", "tb4"],
    "bpc-157": ["bpc-157", "bpc 157", "bpc157", "pentadecapeptide"],
    "ghk-cu": ["ghk-cu", "ghk cu", "ghk", "copper tripeptide", "copper peptide"],
    "cjc-1295": ["cjc-1295", "cjc 1295", "drug affinity complex", "grf 1-29"],
    "mots-c": ["mots-c", "mots c", "mitochondrial-derived peptide", "mitochondrial derived peptide"],
    "melanotan ii": ["melanotan", "melanotan-ii", "melanotan ii", "mt-ii", "afamelanotide"],
    "melanotan-1": ["melanotan", "afamelanotide", "melanotan-i"],
    "pt-141": ["pt-141", "pt 141", "bremelanotide"],
    "aod-9604": ["aod-9604", "aod 9604", "aod9604"],
    "thymosin alpha-1": ["thymosin alpha", "thymalfasin", "tα1"],
    "ipamorelin": ["ipamorelin"],
    "sermorelin": ["sermorelin", "grf 1-29"],
    "epithalon": ["epithalon", "epitalon", "ala-glu-asp-gly"],
    "ll-37": ["ll-37", "ll 37", "cathelicidin"],
    "igf-1 lr3": ["igf-1 lr3", "igf-i lr3", "long r3 igf"],
    "5-amino-1mq": ["5-amino-1mq", "5-amino 1mq", "nnmt inhibitor"],
    "nicotinamide adenine dinucleotide": ["nad+", "nad ", "nicotinamide adenine dinucleotide",
                                          "nicotinamide riboside", "nicotinamide mononucleotide"],
    "delta sleep-inducing peptide": ["delta sleep-inducing peptide", "dsip"],
    "vasoactive intestinal peptide": ["vasoactive intestinal peptide", "vip"],
    "cibinetide": ["cibinetide", "ara-290", "ara 290"],
}


# Greek letters appear constantly in biomedical titles: "β-Alanine", "tβ4",
# "α-GPC", "ω-3". Without normalisation the relevance filter rejected 40% of
# beta-alanine's retrieval — core intervention trials thrown out on a character
# encoding difference. Normalise BOTH the paper text and the compound name so
# "β-alanine" and "beta-alanine" are the same string.
_GREEK_MAP = {
    "\u03b1": "alpha", "\u0391": "alpha", "\u03b2": "beta", "\u0392": "beta",
    "\u03b3": "gamma", "\u0393": "gamma", "\u03b4": "delta", "\u0394": "delta",
    "\u03b5": "epsilon", "\u03ba": "kappa", "\u03bb": "lambda",
    "\u03bc": "mu", "\u00b5": "mu", "\u03c9": "omega", "\u03a9": "omega",
    "\u03c3": "sigma", "\u03a3": "sigma", "\u03c4": "tau", "\u03b8": "theta",
    "\u03c6": "phi", "\u03c1": "rho", "\u03b7": "eta", "\u03b9": "iota",
    "\u03bd": "nu", "\u03be": "xi", "\u03c0": "pi", "\u03c5": "upsilon",
    "\u03c7": "chi", "\u03c8": "psi", "\u03b6": "zeta",
}


def _greek_fold(text):
    """Replace Greek letters with their spelled-out names, lowercase."""
    t = (text or "").lower()
    for g, name in _GREEK_MAP.items():
        if g in t:
            t = t.replace(g, name)
    return t


_FORM_SUFFIXES = (
    "monohydrate", "hydrochloride", "hcl", "citrate", "malate", "sulfate",
    "sulphate", "gluconate", "picolinate", "bisglycinate", "glycinate",
    "oxide", "chloride", "acetate", "tartrate", "aspartate", "orotate",
    "extract", "powder", "capsules", "root", "supplement", "supplements",
)


def _name_forms(topic):
    """All names a paper might use for this compound."""
    key = (topic or "").lower().strip()
    forms = set(_NAME_VARIANTS.get(key, []))
    forms.add(key)
    forms.add(key.replace("-", " "))
    forms.add(key.replace(" ", "-"))
    # strip trailing form/salt words: "creatine monohydrate" -> "creatine"
    parts = key.split()
    while len(parts) > 1 and parts[-1] in _FORM_SUFFIXES:
        parts = parts[:-1]
        forms.add(" ".join(parts))
    return {f for f in forms if f and len(f) > 2}


def is_relevant(study, topic):
    """
    Does this paper actually concern the compound? PubMed relevance search will
    happily return papers that merely share a token with the query. A study that
    never names the compound cannot be evidence about it.
    """
    if not topic:
        return True
    blob = _greek_fold(f"{study.get('title','')} {study.get('abstract','')}")
    # Use the same name forms as intervention detection, so "creatine
    # monohydrate" also matches papers that simply say "creatine". Greek-folded
    # on both sides so "beta-alanine" matches papers written "beta-Alanine".
    variants = {_greek_fold(v) for v in _name_forms(topic)}
    variants |= {_greek_fold(topic).replace("-", ""),
                 _greek_fold(topic).replace("-", " ")}
    return any(v and v in blob for v in variants)


# Language indicating the compound was ADMINISTERED (intervention evidence).
_INTERVENTION_SIGNALS = (
    "supplementation", "supplemented", "administered", "administration of",
    "treated with", "treatment with", "received", "injection of", "injected",
    "ingestion of", "ingested", "were given", "was given", "dosed",
    "randomized to", "randomised to", "assigned to receive", "placebo-controlled",
    "double-blind", "oral intake", "intravenous", "subcutaneous", "supplement",
    "therapy with", "infusion of", "topical application",
)

# Language indicating the study MEASURED endogenous levels (correlational).
_BIOMARKER_SIGNALS = (
    "circulating levels", "serum levels", "plasma levels", "serum concentration",
    "plasma concentration", "circulating concentrations", "biomarker",
    "were measured in patients", "levels were assessed", "associated with levels",
    "correlates with", "correlation between serum", "diagnostic value",
    "prognostic value", "expression levels in patients", "reduced serum",
    "elevated serum", "levels in patients with", "positively associate",
    "negatively associate", "association between serum", "associate with",
    "expression patterns of", "as a biomarker", "diagnostic-prognostic",
    "cross-sectional study", "serum humanin",
)


# Analytical / assay / detection papers. These legitimately name the compound
# (so they pass relevance) but contain no evidence about whether it works —
# they are about how to MEASURE it. TB-500's "human evidence" was largely
# doping-control and mass-spectrometry methodology.
_ANALYTICAL_SIGNALS = (
    "doping control", "doping-control", "mass spectrometry", "chromatography",
    "solid-phase extraction", "solid phase extraction", "quantification of",
    "simultaneous determination", "analytical method", "assay development",
    "screening for peptides", "detection method", "adsorption effects",
    "sample preparation", "validated method", "lc-ms", "uhplc", "hplc",
    "in vitro model systems of the metabolism", "metabolite profiling",
)


def is_analytical_paper(study):
    """True for detection/assay methodology papers — not efficacy evidence."""
    blob = _greek_fold(f"{study.get('title','')} {study.get('abstract','')}")
    return any(sig in blob for sig in _ANALYTICAL_SIGNALS)


# Salt/form suffixes to strip: papers say "creatine supplementation", not
# "creatine monohydrate supplementation". Failing to strip these caused creatine
# to lose two-thirds of its studies and drop from Strong to Moderate.
def _compound_intervention_phrases(topic):
    """
    Phrases indicating THIS compound was administered. Generic intervention
    words are not enough — MOTS-c kept a study of patients "treated with
    metformin" because the phrase fired on a different drug. But the patterns
    must also match how supplement papers actually write ("creatine loading",
    "participants ingested creatine", "supplementation with creatine").
    """
    phrases = []
    for n in {_greek_fold(x) for x in _name_forms(topic)}:
        phrases += [
            # compound-first
            f"{n} supplementation", f"{n} supplement", f"{n} administration",
            f"{n} treatment", f"{n} ingestion", f"{n} intake", f"{n} loading",
            f"{n} was administered", f"{n} were administered",
            f"{n} was given", f"{n} were given", f"{n} injection",
            f"{n} or placebo", f"{n} versus placebo", f"{n} vs placebo",
            f"{n} group", f"{n} arm", f"{n} dose", f"{n} dosing",
            f"{n} improves", f"{n} attenuates", f"{n} reduces", f"{n} increases",
            f"{n} alleviates", f"{n} enhances", f"{n} improved", f"{n} increased",
            f"{n} decreased", f"{n} reduced",
            # compound-second
            f"administration of {n}", f"administered {n}", f"treated with {n}",
            f"supplemented with {n}", f"supplementation with {n}",
            f"received {n}", f"receiving {n}", f"injected with {n}",
            f"ingested {n}", f"ingestion of {n}", f"intake of {n}",
            f"placebo or {n}", f"exogenous {n}", f"effects of {n}",
            f"effect of {n}", f"supplementing with {n}", f"given {n}",
            f"randomized to {n}", f"randomised to {n}", f"assigned to {n}",
        ]
    return phrases


def is_intervention_study(study, topic=None):
    """
    True if the compound appears to have been GIVEN to subjects; False if the
    study merely measured naturally-occurring levels.

    This matters enormously for endogenous compounds (MOTS-c, DHEA, oxytocin,
    glutathione, CoQ10, vitamin D): much of their literature is observational
    measurement, which is NOT evidence that supplementing them does anything.
    Returns True when ambiguous — we only exclude on a clear biomarker signal
    with no intervention language present.
    """
    blob = _greek_fold(f"{study.get('title','')} {study.get('abstract','')}")
    has_biomarker = any(sig in blob for sig in _BIOMARKER_SIGNALS)

    if topic:
        # STRICT RULE: when we know which compound we're grading, require
        # language showing THAT compound was administered. Absent that, the
        # paper is measuring it, comparing it, or mentioning it — none of which
        # is evidence that taking it does anything. This deliberately
        # under-counts rather than inflates: a missed human study costs a
        # slightly conservative grade; a biomarker study counted as intervention
        # evidence tells someone a compound works when nobody ever took it.
        return any(p in blob for p in _compound_intervention_phrases(topic))

    has_intervention = any(sig in blob for sig in _INTERVENTION_SIGNALS)
    if has_biomarker and not has_intervention:
        return False
    return True
