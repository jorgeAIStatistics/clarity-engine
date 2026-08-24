"""
Stage 1 — Retrieve the literature from PubMed.

PubMed's E-utilities API is free. 35M+ papers.
- Without an API key: 3 requests/second
- With a free key (env var NCBI_API_KEY): 10 requests/second

Get a free key at https://www.ncbi.nlm.nih.gov/account/ (optional but recommended).
This module needs NO paid service.
"""

import os
import time
import threading
import requests
import xml.etree.ElementTree as ET

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
API_KEY = os.environ.get("NCBI_API_KEY")  # optional; raises rate limit if present
CONTACT = os.environ.get("CLARITY_CONTACT_EMAIL", "you@example.com")  # courtesy to NCBI

# Be a good citizen: throttle so we never exceed NCBI limits.
_MIN_INTERVAL = 0.34 if not API_KEY else 0.11  # ~3/s or ~10/s
_last_call = [0.0]
# Lock is REQUIRED once outcomes are processed in parallel: without it workers
# race past NCBI's rate limit, which is what produced the multi-hour stalls.
_throttle_lock = threading.Lock()


def _throttle():
    with _throttle_lock:
        dt = time.time() - _last_call[0]
        if dt < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - dt)
        _last_call[0] = time.time()


def _params(extra):
    p = {"tool": "clarity", "email": CONTACT}
    if API_KEY:
        p["api_key"] = API_KEY
    p.update(extra)
    return p


def _get_with_retry(url, params, timeout, tries=4):
    """
    GET with backoff. NCBI throttles heavy use (HTTP 429) and connections can
    stall — without this, a single stall hangs the whole pre-warm for hours.
    Retries on 429/5xx and network errors with exponential backoff, and caps
    total wait so a bad compound fails fast instead of freezing the run.
    """
    delay = 1.0
    last_err = None
    for attempt in range(tries):
        _throttle()
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                # Throttled or server error — back off and retry.
                last_err = f"HTTP {r.status_code}"
                time.sleep(delay)
                delay = min(delay * 2, 8.0)
                continue
            r.raise_for_status()
            return r
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = type(e).__name__
            time.sleep(delay)
            delay = min(delay * 2, 8.0)
    raise RuntimeError(f"NCBI request failed after {tries} tries ({last_err})")


def esearch(term, retmax=40):
    """Return a list of PubMed IDs (PMIDs) matching a query term."""
    r = _get_with_retry(f"{BASE}/esearch.fcgi", _params({
        "db": "pubmed",
        "term": term,
        "retmax": retmax,
        "retmode": "json",
        "sort": "relevance",
    }), timeout=20)
    return r.json().get("esearchresult", {}).get("idlist", [])


_EFETCH_BATCH = 40


def efetch(pmids):
    """
    Fetch abstracts + metadata for a list of PMIDs, in batches.

    A single request for 150 abstracts returns a multi-megabyte XML document,
    which exceeded the timeout and then burned four retries — over a minute
    with nothing produced. NCBI's own guidance is to batch; 40 per request is
    comfortably inside their limits and each batch returns quickly.

    Batches run concurrently (the throttle is lock-guarded, so NCBI's rate
    limit is still respected) and partial failures degrade to fewer studies
    rather than losing the whole compound.
    """
    if not pmids:
        return []
    pmids = list(pmids)
    batches = [pmids[i:i + _EFETCH_BATCH]
               for i in range(0, len(pmids), _EFETCH_BATCH)]

    def _one(batch):
        try:
            r = _get_with_retry(f"{BASE}/efetch.fcgi", _params({
                "db": "pubmed",
                "id": ",".join(batch),
                "retmode": "xml",
            }), timeout=30)
            return _parse_articles(r.text)
        except Exception as e:
            print(f"  [pubmed] efetch batch of {len(batch)} failed: "
                  f"{type(e).__name__}; continuing with the rest")
            return []

    if len(batches) == 1:
        return _one(batches[0])

    from concurrent.futures import ThreadPoolExecutor
    out = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for part in pool.map(_one, batches):
            out.extend(part)
    return out


def _parse_articles(xml_text):
    out = []
    root = ET.fromstring(xml_text)
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID", default="")
        title = art.findtext(".//ArticleTitle", default="") or ""
        # Abstract may be split into multiple labeled sections
        abstract_parts = [ (a.text or "") for a in art.findall(".//AbstractText") ]
        abstract = " ".join(p for p in abstract_parts if p).strip()
        year = art.findtext(".//PubDate/Year", default="") or art.findtext(".//PubDate/MedlineDate", default="")
        journal = art.findtext(".//Journal/Title", default="")
        pub_types = [ (pt.text or "") for pt in art.findall(".//PublicationType") ]
        out.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "year": year[:4] if year else "",
            "journal": journal,
            "publication_types": pub_types,
        })
    return out


# Compounds whose bare name means something else in PubMed. "Collagen" returns
# structural biology and biomaterials, not supplement trials — all 40 retrieved
# papers were rejected by the intervention filter, correctly, leaving 0 studies.
# The fix is to search the term the trials actually use.
SEARCH_TERMS = {
    "collagen": "collagen peptides OR hydrolyzed collagen OR collagen supplementation",
    "glutamine": "glutamine supplementation",
    "glycine": "glycine supplementation",
    "taurine": "taurine supplementation",
    "copper": "copper supplementation",
    "iron": "iron supplementation",
    "calcium": "calcium supplementation",
    "potassium": "potassium supplementation",
    "magnesium": "magnesium supplementation",
    "zinc": "zinc supplementation",
    "selenium": "selenium supplementation",
    "iodine": "iodine supplementation",
    "chromium": "chromium picolinate OR chromium supplementation",
    "manganese": "manganese supplementation",
    "boron": "boron supplementation",
    "thyroid": "thyroid hormone supplementation",
    "testosterone": "testosterone therapy OR testosterone supplementation",
    "progesterone": "progesterone therapy",
    "oxytocin": "intranasal oxytocin",
    "melatonin": "melatonin supplementation",
    "biotin": "biotin supplementation",
    "niacin": "niacin supplementation OR nicotinic acid supplementation",
    "thiamine": "thiamine supplementation",
    "folate": "folic acid supplementation",
    "zma": "zinc magnesium aspartate OR ZMA supplementation",
    "prebiotics": "prebiotic supplementation",
    "glutathione": "glutathione supplementation",
    "spermidine": "spermidine supplementation",
    "quercetin": "quercetin supplementation",
    "resveratrol": "resveratrol supplementation",
    "fisetin": "fisetin supplementation",
    "sulforaphane": "sulforaphane supplementation",
    "astaxanthin": "astaxanthin supplementation",
    "betaine": "betaine anhydrous OR trimethylglycine supplementation",
    "l-carnitine": "l-carnitine supplementation",
    "creatine": "creatine supplementation",
}


def _query_for(topic):
    """Map a catalog name to the term clinical trials actually use."""
    key = (topic or "").lower().strip()
    if key in SEARCH_TERMS:
        return f"({SEARCH_TERMS[key]})"
    # Multi-word names like "creatine monohydrate" also try their base form.
    base = key.split()[0] if " " in key else None
    if base and base in SEARCH_TERMS:
        # Outer parens are REQUIRED: PubMed binds AND tighter than OR, so
        # "(a) OR (b) AND scope" would leave the first branch unscoped.
        return f"(({topic}) OR ({SEARCH_TERMS[base]}))"
    return f"({topic})"


# ROOT FIX: scope every query to INTERVENTION research using PubMed's own
# publication-type and MeSH filters, instead of hand-mapping compound names.
#
# The bare name returns a compound's entire literature: "collagen" gives
# structural biology, "melatonin" gives oncology and antioxidant work,
# "glutamine" gives cancer metabolism. Supplement trials are a minority of the
# top 40, so the engine graded whatever noise ranked highest. Hand-written
# SEARCH_TERMS only fixed the compounds we happened to notice — there was always
# another one. This scoping applies to all of them at once.
_CLINICAL_SCOPE = (
    '("randomized controlled trial"[pt] OR "clinical trial"[pt] '
    'OR "meta-analysis"[pt] OR "systematic review"[pt] '
    'OR "controlled clinical trial"[pt] OR "observational study"[pt] '
    'OR dietary supplements[mh] OR "drug therapy"[sh])'
)

# Preclinical scope — kept separate so peptides still show their animal evidence
# rather than returning nothing. Retrieved as a supplement, never as the primary.
_PRECLINICAL_SCOPE = '(animals[mh] NOT humans[mh])'


def search_topic(topic, outcome=None, retmax=40, include_preclinical=True):
    """
    Fetch studies for a topic, scoped to intervention research.

    Two-pass: clinical-scoped first (the evidence that matters for grading),
    then a preclinical pass to fill remaining slots so animal-only compounds
    still produce a profile. Falls back to an unscoped query only if the scoped
    one returns almost nothing, so obscure compounds aren't left empty.
    """
    base = _query_for(topic)
    # Outcome names use " / " to join synonyms ("gut / digestion", "mood /
    # depression"). A bare slash is MeSH subheading syntax in PubMed
    # (term/subheading), so passing it through produced malformed queries for a
    # third of the vocabulary. Expand to an explicit OR instead.
    outcome_clause = ''
    if outcome:
        parts = [p.strip() for p in str(outcome).split("/") if p.strip()]
        expanded = " OR ".join(f'"{p}"' if " " in p else p for p in parts)
        outcome_clause = f' AND ({expanded})'


    clinical_q = f'{base}{outcome_clause} AND {_CLINICAL_SCOPE}'
    ids = esearch(clinical_q, retmax=retmax)

    if include_preclinical and len(ids) < int(retmax * 0.6):
        pre_q = f'{base}{outcome_clause} AND {_PRECLINICAL_SCOPE}'
        for pid in esearch(pre_q, retmax=retmax - len(ids)):
            if pid not in ids:
                ids.append(pid)

    # Fallback: if scoping starved the query, retrieve unscoped rather than
    # returning an empty profile for a genuinely obscure compound.
    if len(ids) < 5:
        ids = esearch(f'{base}{outcome_clause}', retmax=retmax)

    return efetch(ids)


if __name__ == "__main__":
    # Quick manual test
    studies = search_topic("creatine monohydrate", "muscle strength", retmax=5)
    print(f"Fetched {len(studies)} studies")
    for s in studies:
        print(f"- [{s['year']}] {s['title'][:70]}  ({', '.join(s['publication_types'][:2])})")
