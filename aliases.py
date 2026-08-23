"""
Search aliases: vendor/street names -> the real compound the research is under.

WHY THIS MATTERS: people search for what's printed on the vial, not the name in
PubMed. "GLP-3" is a vendor coinage (there is no GLP-3 receptor) for retatrutide,
a triple GIP/GLP-1/glucagon agonist. Someone searching "GLP-3" should land on
retatrutide's real evidence, not a dead end — and should be TOLD they're the
same thing, since the marketing name implies a drug class that doesn't exist.

Used by the API/search layer to resolve a query before hitting the engine.
"""

# alias (lowercase) -> (canonical name, category, note shown to the user)
ALIASES = {
    "glp-3": ("retatrutide", "peptide",
              "“GLP-3” is a vendor name for retatrutide, a triple GIP/GLP-1/glucagon "
              "receptor agonist. There is no GLP-3 receptor — showing the evidence "
              "for retatrutide."),
    "glp3": ("retatrutide", "peptide",
             "“GLP-3” is a vendor name for retatrutide. Showing retatrutide's evidence."),
    "wolverine blend": ("bpc-157", "peptide",
                        "A blend of BPC-157 and TB-500. Blends aren't graded as one "
                        "compound — showing BPC-157; search TB-500 separately."),
    "n-acetyl semax amidate": ("semax", "peptide",
                               "Research is published on the parent peptide, Semax."),
    "n-acetyl selank amidate": ("selank", "peptide",
                                "Research is published on the parent peptide, Selank."),
    "n-acetyl epithalon": ("epithalon", "peptide",
                           "Research is published on the parent peptide, Epithalon."),
    "thymosin beta-4": ("tb-500", "peptide", "TB-500 is synthetic thymosin beta-4."),
    "mt-2": ("melanotan-2", "peptide", ""),
    "mt-1": ("melanotan-1", "peptide", ""),
    "cibinetide": ("ara-290", "peptide", "ARA-290 is also known as cibinetide."),
    "modified grf 1-29": ("cjc-1295", "peptide", ""),
    "ta1": ("thymosin alpha-1", "peptide", ""),
    "nad+": ("nicotinamide adenine dinucleotide", "longevity", ""),
    "nad": ("nicotinamide adenine dinucleotide", "longevity", ""),
    "copper peptide": ("ghk-cu", "peptide", ""),
    "ozempic": ("semaglutide", "peptide", "Ozempic is a brand of semaglutide."),
    "wegovy": ("semaglutide", "peptide", "Wegovy is a brand of semaglutide."),
    "mounjaro": ("tirzepatide", "peptide", "Mounjaro is a brand of tirzepatide."),
    "zepbound": ("tirzepatide", "peptide", "Zepbound is a brand of tirzepatide."),
}


def resolve(query):
    """
    Returns (canonical_name, category, note) if the query is a known alias,
    else (query, None, None) unchanged.
    """
    k = (query or "").lower().strip()
    if k in ALIASES:
        return ALIASES[k]
    return (query, None, None)


if __name__ == "__main__":
    for q in ["GLP-3", "Ozempic", "n-acetyl semax amidate", "creatine"]:
        name, cat, note = resolve(q)
        print(f"{q:26} -> {name:34} {cat or '-':10} {(note or "")[:60]}")
