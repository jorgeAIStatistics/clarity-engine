"""
Stage 1 of multi-source retrieval — Europe PMC.

WHY: PubMed (via NCBI eutils) indexes MEDLINE-ish biomedical journals and misses
a lot — preprints, more European journals, and much of PMC full text. Europe PMC
is a broader, still-curated index that INCLUDES PubMed/MEDLINE plus bioRxiv/
medRxiv/ChemRxiv preprints and extra journal coverage. It's a free REST API, no
key, JSON. Adding it widens coverage without dropping to unfiltered sources like
raw Google Scholar (which has no quality gate).

DESIGN: this returns study dicts in the SAME shape pubmed.py produces
  {pmid, title, abstract, year, journal, publication_types}
plus two extra fields the merge/dedup + quality layers use:
  {doi, is_preprint, cited_by}
so it drops straight into the existing pipeline. Merge + dedup across sources is
handled by the caller (sources.py), keyed on DOI then normalized title.

HONESTY NOTES:
  - Preprints are FLAGGED (is_preprint) and tagged in publication_types as
    "Preprint" so grading/classification can treat non-peer-reviewed work
    accordingly — never silently mixed in as if peer-reviewed.
  - cited_by (Europe PMC's citedByCount) is a quality signal for the weighting
    layer; an uncited methods/doping paper shouldn't count like a cited trial.
  - Degrades safely: network error -> returns [] and the pipeline falls back to
    PubMed alone.
"""

import os
import time
import threading
import requests

try:
    import indications
except Exception:
    indications = None

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
CONTACT = os.environ.get("CLARITY_CONTACT_EMAIL", "you@example.com")

_MIN_INTERVAL = 0.2          # be polite; Europe PMC is generous
_last_call = [0.0]
_lock = threading.Lock()


def _throttle():
    with _lock:
        dt = time.time() - _last_call[0]
        if dt < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - dt)
        _last_call[0] = time.time()


def _get(params, tries=3, timeout=25):
    delay = 1.0
    for _ in range(tries):
        _throttle()
        try:
            r = requests.get(BASE, params=params, timeout=timeout,
                             headers={"User-Agent": f"clarity-engine ({CONTACT})"})
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(delay); delay = min(delay * 2, 8.0); continue
            r.raise_for_status()
            return r.json()
        except (requests.Timeout, requests.ConnectionError):
            time.sleep(delay); delay = min(delay * 2, 8.0)
        except Exception:
            return None
    return None


_PREPRINT_HINTS = ("preprint", "biorxiv", "medrxiv", "chemrxiv", "research square")


def _parse_result(rec):
    """Map one Europe PMC result record to our study-dict shape."""
    pub_types = []
    ptl = (rec.get("pubTypeList") or {}).get("pubType") or []
    if isinstance(ptl, str):
        ptl = [ptl]
    pub_types = [str(p) for p in ptl if p]

    source = (rec.get("source") or "").lower()
    title_l = (rec.get("title") or "").lower()
    is_preprint = (source == "ppr"
                   or any(h in " ".join(pub_types).lower() for h in _PREPRINT_HINTS)
                   or "preprint" in title_l)
    if is_preprint and "Preprint" not in pub_types:
        pub_types.append("Preprint")

    cited = rec.get("citedByCount")
    try:
        cited = int(cited)
    except (TypeError, ValueError):
        cited = None

    journal = ((rec.get("journalInfo") or {}).get("journal") or {}).get("title") or ""
    if not journal and rec.get("bookOrReportDetails"):
        journal = (rec["bookOrReportDetails"].get("publisher") or "")

    return {
        # pmid may be absent for preprints — fall back to the Europe PMC id so
        # the record still has a stable key.
        "pmid": rec.get("pmid") or "",
        "epmc_id": f"{rec.get('source','')}:{rec.get('id','')}",
        "title": (rec.get("title") or "").strip(),
        "abstract": (rec.get("abstractText") or "").strip(),
        "year": (str(rec.get("pubYear")) if rec.get("pubYear") else "")[:4],
        "journal": journal,
        "publication_types": pub_types,
        "doi": (rec.get("doi") or "").lower().strip() or None,
        "is_preprint": is_preprint,
        "cited_by": cited,
        "retrieved_from": "europe_pmc",
    }


def search(query, retmax=60, include_preprints=True):
    """
    Search Europe PMC with a raw query string and return study dicts.
    `query` should already be a composed Europe PMC query (the caller builds it,
    mirroring pubmed's scoping). pageSize caps at 100 per call.
    """
    if not query:
        return []
    page_size = min(int(retmax), 100)
    params = {
        "query": query,
        "resultType": "core",     # includes abstractText + full metadata
        "pageSize": page_size,
        "format": "json",
        # NOTE: no `sort` param — Europe PMC's default IS relevance, and passing
        # sort=relevance is invalid and silently returns nothing (hitCount=None).
    }
    data = _get(params)
    if not data:
        return []
    results = (data.get("resultList") or {}).get("result") or []
    out = []
    for rec in results:
        s = _parse_result(rec)
        if not s["title"]:
            continue
        if s["is_preprint"] and not include_preprints:
            continue
        out.append(s)
    return out


# Europe PMC query scoping. Its pub-type vocabulary and field names differ from
# PubMed's — the earlier PUB_TYPE:"Randomized Controlled Trial" style matched
# nothing. This scope uses fields that exist in Europe PMC and errs toward
# RETURNING results (the quality filter downstream removes noise; the retrieval
# layer's job is coverage). We require the topic in title/abstract to cut the
# "tb"+"500" broad-keyword noise, and prefer human/clinical work.
def _scoped_query(topic, outcome):
    # Require a recognized compound name in title/abstract. Vitamins often use
    # chemical names (e.g. cholecalciferol, cobalamin) rather than the catalog label.
    key = str(topic or "").lower().strip()
    ambiguous = {
        # Do not search bare "VIP": it matches unrelated care programs/regimens.
        "vip": ["vasoactive intestinal peptide", "vasoactive intestinal polypeptide"],
    }
    aliases = list(ambiguous.get(key, []))
    if not aliases and indications is not None:
        try:
            aliases = indications.search_aliases(topic)
        except Exception:
            aliases = []
    if not aliases:
        aliases = [str(topic)]
    topic_parts = []
    for raw in aliases[:6]:
        term = f'"{raw}"'
        topic_parts.append(f'TITLE:{term}')
        topic_parts.append(f'ABSTRACT:{term}')
    q = '(' + ' OR '.join(topic_parts) + ')'
    if outcome:
        parts = [p.strip() for p in str(outcome).split("/") if p.strip()]
        expanded = " OR ".join(f'"{p}"' if " " in p else p for p in parts)
        q += f' AND ({expanded})'
    return q


def search_topic(topic, outcome=None, retmax=60, include_preprints=True):
    """
    Convenience wrapper mirroring pubmed.search_topic's signature, so the caller
    can treat both sources uniformly. Scoped to title/abstract mentions of the
    compound (the quality filter handles study-type relevance downstream).
    """
    scoped = _scoped_query(topic, outcome)
    hits = search(scoped, retmax=retmax, include_preprints=include_preprints)
    # Fallback 1: drop the outcome clause (some outcomes are phrased oddly).
    if len(hits) < 5 and outcome:
        hits = search(_scoped_query(topic, None), retmax=retmax,
                      include_preprints=include_preprints)
    # Fallback 2: bare term anywhere, last resort for obscure compounds.
    if len(hits) < 3:
        bare = f'"{topic}"' if " " in topic else topic
        hits = search(bare, retmax=retmax, include_preprints=include_preprints)
    return hits


if __name__ == "__main__":
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else "tb-500"
    outcome = sys.argv[2] if len(sys.argv) > 2 else None
    res = search_topic(topic, outcome, retmax=15)
    print(f"Europe PMC: {len(res)} results for '{topic}'"
          + (f" / '{outcome}'" if outcome else ""))
    for s in res[:12]:
        tag = " [PREPRINT]" if s["is_preprint"] else ""
        cb = f" · cited {s['cited_by']}" if s["cited_by"] is not None else ""
        print(f"  [{s['year']}] {s['title'][:70]}{tag}{cb}")
