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
import requests
import xml.etree.ElementTree as ET

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
API_KEY = os.environ.get("NCBI_API_KEY")  # optional; raises rate limit if present
CONTACT = os.environ.get("CLARITY_CONTACT_EMAIL", "you@example.com")  # courtesy to NCBI

# Be a good citizen: throttle so we never exceed NCBI limits.
_MIN_INTERVAL = 0.34 if not API_KEY else 0.11  # ~3/s or ~10/s
_last_call = [0.0]


def _throttle():
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


def esearch(term, retmax=40):
    """Return a list of PubMed IDs (PMIDs) matching a query term."""
    _throttle()
    r = requests.get(f"{BASE}/esearch.fcgi", params=_params({
        "db": "pubmed",
        "term": term,
        "retmax": retmax,
        "retmode": "json",
        "sort": "relevance",
    }), timeout=30)
    r.raise_for_status()
    return r.json().get("esearchresult", {}).get("idlist", [])


def efetch(pmids):
    """Fetch abstracts + metadata for a list of PMIDs. Returns list of dicts."""
    if not pmids:
        return []
    _throttle()
    r = requests.get(f"{BASE}/efetch.fcgi", params=_params({
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }), timeout=60)
    r.raise_for_status()
    return _parse_articles(r.text)


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


def search_topic(topic, outcome=None, retmax=40):
    """Convenience: build a query for a topic (optionally an outcome) and fetch studies."""
    # Bias toward human clinical evidence where possible.
    query = f'({topic})'
    if outcome:
        query += f' AND ({outcome})'
    ids = esearch(query, retmax=retmax)
    return efetch(ids)


if __name__ == "__main__":
    # Quick manual test
    studies = search_topic("creatine monohydrate", "muscle strength", retmax=5)
    print(f"Fetched {len(studies)} studies")
    for s in studies:
        print(f"- [{s['year']}] {s['title'][:70]}  ({', '.join(s['publication_types'][:2])})")
