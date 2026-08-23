"""
PubChem enrichment — hard factual chemistry data per compound.

WHY: the "what it is" section is currently 100% LLM-generated prose, which is
the highest hallucination-risk content in the product. PubChem gives us FACTS
(formula, weight, IUPAC name, synonyms, CID) that are citable and verifiable.
These anchor the section instead of relying on generation for basic identity.

Free, no API key, no rate-limit problems at our volume. Cached by compound name.
Degrades silently: no network / no match -> returns None, UI omits the block.

Data source: PubChem PUG-REST (pubchem.ncbi.nlm.nih.gov). Same NCBI family as
PubMed, so attribution is consistent with the rest of the engine.
"""

import os
import json
import time
import urllib.parse

import requests

_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "pubchem.json")
_MIN_INTERVAL = 0.25          # PubChem asks for <=5 req/sec; stay well under
_last_call = [0.0]

# Compounds where the catalog name won't resolve cleanly — map to a searchable
# term. Peptides especially are often absent or oddly named in PubChem.
_ALIASES = {
    "omega-3": "eicosapentaenoic acid",
    "fish oil": "eicosapentaenoic acid",
    "vitamin d3": "cholecalciferol",
    "vitamin d": "cholecalciferol",
    "vitamin b12": "cyanocobalamin",
    "vitamin k2": "menaquinone",
    "vitamin c": "ascorbic acid",
    "vitamin e": "alpha-tocopherol",
    "vitamin a": "retinol",
    "folate": "folic acid",
    "nac": "acetylcysteine",
    "nmn": "nicotinamide mononucleotide",
    "nr": "nicotinamide riboside",
    "ca-akg": "alpha-ketoglutaric acid",
    "whey protein": None,        # not a single molecule — skip honestly
    "collagen": None,
    "probiotics": None,
    "prebiotics": None,
    "electrolytes": None,
    "digestive enzymes": None,
    "krill oil": None,
    "mct oil": None,
    "fish oil ": None,
}


def _throttle():
    dt = time.time() - _last_call[0]
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    _last_call[0] = time.time()


def _load_cache():
    try:
        with open(_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(c):
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, "w") as f:
            json.dump(c, f, indent=2)
    except Exception:
        pass


def _get(url, timeout=15):
    _throttle()
    r = requests.get(url, timeout=timeout,
                     headers={"User-Agent": "clarity-engine (research/education)"})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r


def fetch(name):
    """
    Look up one compound. Returns a dict of verified facts, or None.
    Cached by lowercase name (including negative results, so we don't re-query
    things PubChem genuinely doesn't have).
    """
    key = (name or "").lower().strip()
    if not key:
        return None

    cache = _load_cache()
    if key in cache:
        return cache[key]          # may be None (cached miss) — that's intended

    # Mixtures / non-single-molecule entries: honestly no chemistry record.
    if key in _ALIASES and _ALIASES[key] is None:
        cache[key] = None
        _save_cache(cache)
        return None
    query = _ALIASES.get(key, name)

    result = None
    try:
        q = urllib.parse.quote(query)
        props = ("MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,"
                 "InChIKey,XLogP")
        r = _get(f"{_BASE}/compound/name/{q}/property/{props}/JSON")
        if r:
            rows = r.json().get("PropertyTable", {}).get("Properties", [])
            if rows:
                p = rows[0]
                cid = p.get("CID")
                result = {
                    "cid": cid,
                    "formula": p.get("MolecularFormula"),
                    "weight": p.get("MolecularWeight"),
                    "iupac_name": p.get("IUPACName"),
                    "smiles": p.get("CanonicalSMILES"),
                    "inchikey": p.get("InChIKey"),
                    "xlogp": p.get("XLogP"),
                    "image_url": (f"https://pubchem.ncbi.nlm.nih.gov/image/imgsrv.fcgi"
                                  f"?cid={cid}&t=l") if cid else None,
                    "pubchem_url": (f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
                                    if cid else None),
                    "matched_query": query,
                    "source": "PubChem",
                }
                # a couple of common synonyms, for the "also known as" line
                try:
                    rs = _get(f"{_BASE}/compound/cid/{cid}/synonyms/JSON")
                    if rs:
                        syns = (rs.json().get("InformationList", {})
                                .get("Information", [{}])[0].get("Synonym", []))
                        clean = [s for s in syns[:40]
                                 if len(s) < 40 and not s.isdigit()
                                 and s.lower() != key][:6]
                        result["synonyms"] = clean
                except Exception:
                    result["synonyms"] = []
    except Exception:
        result = None

    cache[key] = result
    _save_cache(cache)
    return result


if __name__ == "__main__":
    import sys
    for n in (sys.argv[1:] or ["creatine monohydrate", "ashwagandha", "bpc-157",
                               "vitamin d3", "whey protein"]):
        d = fetch(n)
        if d:
            print(f"{n:24} -> {d['formula']:14} MW {d['weight']:>8}  CID {d['cid']}")
            print(f"{'':24}    {(d.get('iupac_name') or '')[:80]}")
            if d.get("synonyms"):
                print(f"{'':24}    aka: {', '.join(d['synonyms'][:4])}")
        else:
            print(f"{n:24} -> no single-molecule record (mixture or not found)")
