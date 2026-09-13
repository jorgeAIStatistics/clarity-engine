"""
Curated pharmacokinetics (PK) data — REAL, CITED published values only.

WHY THIS IS A HAND-CURATED FILE AND NOT AUTO-EXTRACTED:
PK parameters (half-life, Tmax, Cmax, bioavailability) are NOT in PubChem
(that's molecular data) and are only inconsistently in PubMed abstracts. They
come from clinical pharmacology studies and vary by dose/route/population. So
the honest way to surface them is a small curated dataset where every value
carries a citation — never an LLM guess. A compound appears in the PK section
ONLY if it has an entry here. Everything else shows no PK section (honest: we
don't have verified PK for it).

Each entry's values are published means/typical values for oral administration
in healthy adults, with the source. `curve` is a small set of (hour, relative%)
points describing the plasma concentration-time shape — used to DRAW the curve.
These describe the SHAPE (rise to Tmax, decay by half-life); they are relative
(peak = 100%), not absolute concentrations, and labelled as such in the UI.

To add a compound: add a cited entry. Do NOT add values you can't cite.
"""

# Relative concentration-time curves: list of [hour, percent-of-peak].
# Built to match each compound's real Tmax and half-life (documented per entry).

PK_DATA = {
    "caffeine": {
        "display_route": "oral",
        "tmax_min": 45,           # mean ~0.5-1 h; "well absorbed within 45 min"
        "tmax_label": "30–60 min",
        "half_life_h": 5.0,       # adult mean ~5 h (range 2–8)
        "half_life_label": "~5 h (range 2–8)",
        "bioavailability_pct": 99,
        "bioavailability_label": "~99% (near-complete)",
        "cmax_label": "1–2 mg/L per 1 mg/kg",
        "vd_label": "0.5–0.6 L/kg",
        "metabolism": "Hepatic, primarily CYP1A2 (→ paraxanthine).",
        "notes": "Half-life varies widely: shortened by smoking, roughly doubled "
                 "in pregnancy and with oral contraceptives.",
        "sources": [
            {"label": "StatPearls (NIH Bookshelf), Caffeine",
             "url": "https://www.ncbi.nlm.nih.gov/books/NBK519490/"},
            {"label": "Blanchard & Sawers 1983, Eur J Clin Pharmacol (absolute bioavailability)",
             "url": "https://link.springer.com/article/10.1007/BF00613933"},
        ],
        # peak at ~0.75 h, t½ 5 h decay
        "curve": [[0, 0], [0.25, 55], [0.5, 88], [0.75, 100], [1, 98], [1.5, 92],
                  [2, 85], [3, 74], [4, 64], [6, 48], [8, 36], [10, 27],
                  [12, 20], [16, 11], [24, 4]],
    },
    "creatine monohydrate": {
        "display_route": "oral",
        "tmax_min": 114,          # 1.9 h (Persky 2003, single 71 mg/kg dose)
        "tmax_label": "~1.9 h",
        "half_life_h": 3.0,       # plasma t½ ~3 h (short; then muscle uptake/excretion)
        "half_life_label": "~3 h (plasma)",
        "bioavailability_pct": None,
        "bioavailability_label": "high, not precisely established",
        "cmax_label": "~102 mg·h/L (single 71 mg/kg dose)",
        "vd_label": "not established",
        "metabolism": "Not hepatically metabolised; taken up by muscle or excreted "
                      "renally as creatinine.",
        "notes": "Plasma is a transit compartment — the point of dosing is muscle "
                 "saturation over days, not the single-dose plasma curve. Steady "
                 "state after ~1 week of 3–5 g/day.",
        "sources": [
            {"label": "Persky et al. 2003, J Clin Pharmacol (single- & multiple-dose PK)",
             "url": "https://accp1.onlinelibrary.wiley.com/doi/10.1177/0091270002239703"},
            {"label": "Persky, Brazeau & Hochhaus 2003, Clin Pharmacokinet (review)",
             "url": "https://paulogentil.com/pdf/Pharmacokinetics%20of%20the%20dietary%20supplement%20creatine.pdf"},
        ],
        # peak ~1.9 h, plasma t½ ~3 h
        "curve": [[0, 0], [0.5, 35], [1, 72], [1.5, 92], [1.9, 100], [2.5, 94],
                  [3, 85], [4, 68], [5, 54], [6, 43], [8, 27], [10, 17], [12, 11]],
    },
}


def get(name):
    """Return the PK record for a compound name (case-insensitive), or None."""
    if not name:
        return None
    key = name.lower().strip()
    if key in PK_DATA:
        return PK_DATA[key]
    # tolerate "creatine" -> "creatine monohydrate"
    for k in PK_DATA:
        if k.startswith(key) or key.startswith(k.split()[0]):
            if key in k or k.split()[0] == key:
                return PK_DATA[k]
    return None


if __name__ == "__main__":
    for n in ("caffeine", "creatine monohydrate", "creatine", "ashwagandha"):
        r = get(n)
        print(f"{n:24} -> {'PK: t½ ' + r['half_life_label'] if r else 'no PK data'}")
