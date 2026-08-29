"""
Engine regression tests — run after ANY change to grade.py / classify.py.

    python3 test_engine.py

Every case here encodes a real bug that reached the catalog and was caught by
eye. The point is to make that domain knowledge REUSABLE: the engine now has
enough interacting rules (population, design, precision, consistency, layer
caps) that fixing one reliably perturbs another. Five separate times, a correct
local fix produced a wrong global result, and the only detector was a human
noticing an implausible tier scrolling past in a terminal.

If you change a threshold and a test fails, that's the system telling you what
your change costs. Decide deliberately, then update the expectation WITH a note
about why.

No network, no API key, no cost. Runs in under a second.
"""

import sys

import grade
import classify


def mk(design, population, n, count, rank, **extra):
    out = []
    for i in range(count):
        s = {"design": design, "design_rank": rank, "population": population,
             "sample_size": n, "pmid": f"{design}{population}{i}"}
        s.update(extra)
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# GRADING CASES — (name, studies, expected_tier, why_this_matters)
# ---------------------------------------------------------------------------
GRADE_CASES = [
    ("creatine strength: many RCTs, metas, patchy N extraction",
     mk("rct", "human", None, 23, 5) + mk("rct", "human", 39, 5, 5)
     + mk("meta_analysis", "human", 180, 3, 6),
     "Strong",
     "BUG: total_n only summed studies whose abstract stated N, so a large RCT "
     "literature looked tiny and got downgraded for the ENGINE'S parse failure."),

    ("creatine cognition: multiple metas reporting large pooled N",
     mk("rct", "human", None, 17, 5) + mk("meta_analysis", "human", 492, 5, 6),
     "Strong",
     "Genuine top-tier evidence must still reach Strong after tightening."),

    ("NMN-like: ~12 human studies, 2 metas, small/unknown samples",
     mk("rct", "human", None, 10, 5) + mk("rct", "human", 22, 2, 5)
     + mk("meta_analysis", "human", None, 2, 6),
     "Moderate",
     "BUG: `substantial_body` (>=10 human studies) was allowed to satisfy the "
     "precision gate, so nearly every well-searched compound hit Strong."),

    ("resveratrol-like: many small trials summing large",
     mk("rct", "human", 30, 8, 5) + mk("rct", "human", None, 12, 5)
     + mk("meta_analysis", "human", None, 2, 6),
     "Moderate",
     "BUG: extrapolated total N rewarded 20 tiny trials like a few large ones. "
     "Power comes from trial size, not just the sum."),

    ("genuinely large: well-powered trials plus big pooled metas",
     mk("rct", "human", 400, 10, 5) + mk("meta_analysis", "human", 3000, 3, 6),
     "Strong",
     "The bar must remain reachable by evidence that truly deserves it."),

    ("single meta-analysis only",
     mk("rct", "human", None, 12, 5) + mk("meta_analysis", "human", 800, 1, 6),
     "Moderate",
     "BUG: one meta-analysis auto-granted Strong. Nearly every heavily-studied "
     "topic has one, so Strong became cheap. Now needs 2+ independent."),

    ("mood-like: one 18-participant trial",
     mk("rct", "human", 18, 1, 5) + mk("rct", "human", None, 2, 5),
     "Emerging",
     "BUG: ~18 participants graded Moderate, reading as 'good human evidence'."),

    ("animal-only peptide (BPC-157 pattern)",
     mk("animal", "animal", 30, 8, 1),
     "Preliminary",
     "The hard cap: animal data must never reach a human-evidence tier."),

    ("single study only",
     mk("rct", "human", 40, 1, 5),
     "Emerging",
     "One study cannot establish consistency."),

    ("vitamin-E-like: thin primary base, 2 metas present",
     mk("rct", "human", 60, 4, 5) + mk("meta_analysis", "human", 900, 2, 6)
     + mk("animal", "animal", None, 7, 1),
     "Moderate",
     "BUG: Vitamin E reached Strong on 13 retrieved studies. Two review papers in "
     "a thin set cleared the gate with no real primary-human base behind them."),

    ("apple-cider-vinegar-like: mostly animal, few human",
     mk("rct", "human", 40, 3, 5) + mk("meta_analysis", "human", 600, 2, 6)
     + mk("animal", "animal", None, 20, 1),
     "Moderate",
     "BUG: an evidence floor keyed on TOTAL studies let a 20/25-animal set clear "
     "a human-evidence tier. The floor must count human research only."),

    ("no sample sizes extractable anywhere",
     mk("rct", "human", None, 14, 5) + mk("meta_analysis", "human", None, 3, 6),
     "Moderate",
     "Unverifiable precision must cap below the top tier — never assume."),
]


# ---------------------------------------------------------------------------
# CLASSIFICATION CASES — (name, study, expected_design, expected_population, why)
# ---------------------------------------------------------------------------
CLASSIFY_CASES = [
    ("rat study using randomization language",
     {"publication_types": ["Journal Article"],
      "title": "BPC 157 accelerates Achilles tendon healing in rats",
      "abstract": "Rats were randomly assigned to four groups in a double-blind design."},
     "animal", "animal",
     "BUG: the abstract-text design fallback read 'randomly assigned' as RCT, so "
     "rat studies counted as human evidence — reviving the phantom-human bug."),

    ("mouse study, placebo-controlled phrasing",
     {"publication_types": ["Journal Article"],
      "title": "Effects of TB-500 in a murine model",
      "abstract": "Mice were randomly allocated in a placebo-controlled trial design."},
     "animal", "animal",
     "Same class: animal studies use identical trial vocabulary."),

    ("species named only in the abstract is still animal",
     {"publication_types": ["Journal Article"],
      "title": "Pentadecapeptide BPC 157 cream improves burn-wound healing",
      "abstract": "BPC 157 was administered topically or systemically in burned mice."},
     "animal", "animal",
     "BUG: the species word appeared in the abstract, not the title, so a PubMed "
     "pubtype of 'observational' carried the decision and BPC-157 reached "
     "Moderate ('good human evidence') on mouse burn studies."),

    ("animal words inside longer words are not signals",
     {"publication_types": ["Randomized Controlled Trial"],
      "title": "Pigment epithelium changes when supplementation indicates benefit",
      "abstract": "Adults were randomized to treatment or placebo."},
     "rct", "human",
     "BUG: substring matching made 'pigment' match 'pig', 'when' match 'hen' and "
     "'indicate' match 'cat'. Harmless as a design hint, catastrophic once the "
     "detector governs population."),

    ("human trial citing in-vitro work stays human",
     {"publication_types": ["Randomized Controlled Trial"],
      "title": "Efficacy of berberine in patients with type 2 diabetes mellitus",
      "abstract": "In vitro studies suggest AMPK activation. We randomized 116 patients."},
     "rct", "human",
     "BUG: 'in vitro' and 'cell culture' were treated as authoritative animal "
     "signals, but human trials routinely cite them in their background. This "
     "flagged 87 of 128 profiles and would have demoted real human evidence."),

    ("genuine human RCT tagged in metadata",
     {"publication_types": ["Randomized Controlled Trial"],
      "title": "Creatine supplementation in older adults",
      "abstract": "120 community-dwelling adults were randomized to creatine or placebo."},
     "rct", "human",
     "Metadata-tagged human RCTs must still classify correctly."),

    ("human RCT stated only in abstract text",
     {"publication_types": ["Journal Article"],
      "title": "Creatine and strength in trained men",
      "abstract": "In this randomized, double-blind, placebo-controlled trial, 40 healthy men participated."},
     "rct", "human",
     "BUG: ~19% of the catalog was 'Unclassified' because design lived in the "
     "abstract, not the publication types. The fallback must still rescue these."),

    ("narrative review excluded",
     {"publication_types": ["Review", "Journal Article"],
      "title": "Creatine: a narrative review",
      "abstract": "We discuss the literature on creatine."},
     None, None,
     "Reviews/editorials must not be counted as primary studies."),
]


# ---------------------------------------------------------------------------
# RELEVANCE / STUDY-TYPE CASES — (name, study, topic, expect_kept, why)
# ---------------------------------------------------------------------------
FILTER_CASES = [
    ("off-topic paper matching only a token",
     {"title": "Logistic regression analysis of environmental and other variables",
      "abstract": "We modelled environmental exposures."}, "tb-500", False,
     "BUG: TB-500 was graded Moderate partly on papers that never mention it — "
     "PubMed matched 'TB' and generic peptide terms."),

    ("pharmacological name accepted",
     {"title": "Thymosin beta-4 promotes corneal wound healing",
      "abstract": "Thymosin beta-4 was administered topically."}, "tb-500", True,
     "Relevance must accept the drug's real name, not just the street name."),

    ("biomarker study excluded from intervention evidence",
     {"title": "Circulating levels of MOTS-c in patients with breast cancer",
      "abstract": "Serum levels were measured in patients and controls."}, "mots-c", False,
     "BUG: MOTS-c graded Moderate on observational studies MEASURING endogenous "
     "levels. Nobody received the compound; correlation is not intervention evidence."),

    ("broiler chicken study is not human evidence",
     {"title": "Comparative effects of dietary sodium butyrate on broiler chickens",
      "abstract": "Birds were fed supplemented diets."}, "tb-500", False,
     "BUG: the species list lacked poultry/horses/sheep/primates, so a chicken "
     "study classified as human and lifted TB-500 to Moderate."),

    ("assay methodology paper is not efficacy evidence",
     {"title": "Doping control analysis of TB-500 in equine urine by mass spectrometry",
      "abstract": "A validated LC-MS method was developed."}, "tb-500", False,
     "BUG: detection/quantification papers name the compound so they passed "
     "relevance, but they contain no evidence about whether it works."),

    ("intervention language must name THIS compound",
     {"title": "Circulating levels of MOTS-c in patients treated with metformin",
      "abstract": "Serum levels were measured in patients treated with metformin."},
     "mots-c", False,
     "BUG: 'treated with' fired on metformin, not MOTS-c, so a biomarker study "
     "counted as intervention evidence."),

    ("salt/form suffix stripped from compound name",
     {"title": "Effects of creatine supplementation on muscle strength",
      "abstract": "Participants received creatine or placebo for 12 weeks."},
     "creatine monohydrate", True,
     "BUG: topic 'creatine monohydrate' looked for 'creatine monohydrate "
     "supplementation', but papers write 'creatine supplementation'. Creatine "
     "lost two-thirds of its studies and fell from Strong to Moderate."),

    ("supplement-paper phrasing recognised",
     {"title": "Creatine loading enhances high-intensity performance",
      "abstract": "Subjects underwent creatine loading before testing."},
     "creatine monohydrate", True,
     "Intervention patterns must cover how supplement literature actually "
     "phrases administration (loading, ingestion, intake), not just clinical verbs."),

    ("Greek-letter compound name matched",
     {"title": "\u03b2-Alanine ingestion increases muscle carnosine content",
      "abstract": "Participants received \u03b2-alanine supplementation for 4 weeks."},
     "beta-alanine", True,
     "BUG: papers write '\u03b2-Alanine' but the filter looked for 'beta-alanine', "
     "rejecting 40% of the retrieval as off-topic. Beta-alanine fell to 12 studies "
     "and Moderate. Affects every Greek-lettered compound (t\u03b24, \u03b1-GPC, \u03c9-3)."),

    ("genuine intervention study kept",
     {"title": "Effect of MOTS-c supplementation on insulin sensitivity",
      "abstract": "Participants received MOTS-c or placebo in a double-blind trial."},
     "mots-c", True,
     "Real administration studies must survive both filters."),
]


# ---------------------------------------------------------------------------
# OUTCOME DISCOVERY — (name, studies, expected_outcome, must_not_include, why)
# ---------------------------------------------------------------------------
DISCOVERY_CASES = [
    ("beta-alanine discovers exercise performance",
     [{"title": "Effect of beta-alanine supplementation on high-intensity exercise performance", "abstract": ""},
      {"title": "beta-alanine efficacy for sports performance improvement", "abstract": ""},
      {"title": "Additive Benefits of beta-Alanine Supplementation and Sprint-Interval Training", "abstract": ""},
      {"title": "Carnosine and Beta-Alanine Supplementation", "abstract": "reduces oxidative stress markers"},
      {"title": "Insulin does not stimulate beta-alanine transport", "abstract": "glucose insulin uptake"}],
     "exercise performance", ["stress / anxiety"],
     "BUG: no category existed for high-intensity performance, so beta-alanine "
     "was graded on gut, blood sugar and inflammation instead. Also 'oxidative "
     "stress' matched the psychological stress pattern on every antioxidant paper."),

    ("collagen discovers skin and joints",
     [{"title": "Oral collagen peptide supplementation improves skin elasticity", "abstract": "wrinkle depth reduced"},
      {"title": "Collagen peptides and joint pain in athletes", "abstract": "knee pain and WOMAC improved"},
      {"title": "Effect of hydrolyzed collagen on skin wrinkles", "abstract": "dermal density increased"},
      {"title": "Collagen supplementation for osteoarthritis", "abstract": "cartilage and joint stiffness"}],
     "skin / appearance", ["gut / digestion", "mood / depression"],
     "BUG: no skin or joint categories existed, so collagen graded on muscle "
     "strength, mood and gut instead of its actual literature. Same gap affected "
     "glucosamine, biotin, milk thistle, lutein, tongkat ali."),

    ("creatine discovers strength and cognition",
     [{"title": "Creatine supplementation increases muscle strength", "abstract": ""},
      {"title": "Creatine and cognition in aging: a systematic review", "abstract": ""},
      {"title": "Effects of creatine on 1-RM strength and power output", "abstract": ""},
      {"title": "Creatine monohydrate and cognitive function in adults", "abstract": ""}],
     "muscle strength", [],
     "Discovery must still find the right outcomes for well-behaved compounds."),
]


# ---------------------------------------------------------------------------
# QUERY STRUCTURE — every compound name must yield ONE safely-parenthesised
# group. "(a) OR (b) AND scope" parses as "(a) OR ((b) AND scope)" in PubMed,
# leaving the first branch unfiltered — which silently defeated the clinical
# scoping for every multi-word compound.
# ---------------------------------------------------------------------------
def check_query_structure():
    import pubmed
    names = list(pubmed.SEARCH_TERMS.keys()) + [
        "creatine monohydrate", "bpc-157", "beta-alanine", "ghk-cu", "tb-500"]
    bad = []
    for t in names:
        q = pubmed._query_for(t)
        if q.count("(") != q.count(")"):
            bad.append((t, "unbalanced parens", q))
            continue
        depth = 0
        for i, ch in enumerate(q):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(q) - 1:
                    bad.append((t, "multiple top-level groups", q))
                    break
    return names, bad


def run():
    passed = failed = 0
    failures = []

    print("GRADING")
    for name, studies, expected, why in GRADE_CASES:
        g = grade.grade_outcome(studies)
        got = g["tier"]
        ok = got == expected
        print(f"  {'PASS' if ok else 'FAIL'}  {name:52} {got:12} (want {expected})")
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((name, expected, got, why))

    print("\nCLASSIFICATION")
    for name, study, exp_design, exp_pop, why in CLASSIFY_CASES:
        r = classify.classify(dict(study, pmid="1"))
        if exp_design is None:
            ok = r is None or r.get("is_non_study") or r.get("design") in (None, "unknown")
            got = "excluded" if ok else f"{r.get('design')}/{r.get('population')}"
            want = "excluded"
        else:
            got = f"{r.get('design')}/{r.get('population')}"
            want = f"{exp_design}/{exp_pop}"
            ok = got == want
        print(f"  {'PASS' if ok else 'FAIL'}  {name:52} {got:20} (want {want})")
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((name, want, got, why))

    print("\nRELEVANCE / STUDY TYPE")
    for name, study, topic, expect_kept, why in FILTER_CASES:
        kept = (classify.is_relevant(study, topic)
                and classify.is_intervention_study(study, topic)
                and not classify.is_analytical_paper(study))
        ok = kept == expect_kept
        print(f"  {'PASS' if ok else 'FAIL'}  {name:52} kept={kept} (want {expect_kept})")
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((name, f"kept={expect_kept}", f"kept={kept}", why))

    print("\nOUTCOME DISCOVERY")
    import discover
    for name, studies, expected, forbidden, why in DISCOVERY_CASES:
        outs = discover.discover(studies, name.split()[0])
        ok = expected in outs and not any(f in outs for f in forbidden)
        print(f"  {'PASS' if ok else 'FAIL'}  {name:52} {outs}")
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((name, f"{expected} present, {forbidden} absent",
                             str(outs), why))

    print("\nQUERY STRUCTURE")
    names, bad = check_query_structure()
    if bad:
        failed += 1
        print(f"  FAIL  {len(bad)} of {len(names)} compound queries malformed")
        for t, why, q in bad[:5]:
            print(f"        {t}: {why}")
        failures.append(("query structure", "all queries one safe group",
                         f"{len(bad)} malformed",
                         "BUG: 'AND' binds tighter than 'OR' in PubMed, so an "
                         "unwrapped 'OR' left half the query unscoped."))
    else:
        passed += 1
        print(f"  PASS  all {len(names)} compound queries safely parenthesised")

    print(f"\n{passed} passed, {failed} failed")
    if failures:
        print("\nWHAT BROKE AND WHY IT MATTERED:")
        for name, want, got, why in failures:
            print(f"\n  {name}\n    wanted {want}, got {got}\n    {why}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
