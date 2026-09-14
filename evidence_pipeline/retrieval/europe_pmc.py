"""Europe PMC core search with immutable windows and durable page commits."""

import hashlib
import re
import time
from datetime import date
from html.parser import HTMLParser
from typing import Annotated
import httpx
from pydantic import Field
from ..common import digest, now, PipelineError
from ..schemas.pico import StrictModel, Text, SourceDocument

BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


class Target(StrictModel):
    id: Annotated[str, Field(min_length=1, max_length=160)]
    terms: Annotated[list[Text], Field(min_length=1, max_length=30)]


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "br", "div", "sec", "title"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("p", "div", "sec", "title"):
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(value or "")
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def phrase(term):
    if any(ord(c) < 32 for c in term):
        raise ValueError("Control character in query term")
    return '"' + term.replace("\\", "\\\\").replace('"', '\\"') + '"'


def query_for(target, since, until):
    if since > until:
        raise ValueError("Reversed search window")
    terms = " OR ".join("TITLE_ABS:" + phrase(t) for t in target.terms)
    return f'({terms}) AND (PUB_TYPE:"randomized controlled trial" OR PUB_TYPE:"meta-analysis") AND FIRST_IDATE:[{since.isoformat()} TO {until.isoformat()}]'


def document_from(record):
    pmid = str(
        record.get("pmid")
        or (record.get("id") if record.get("source") == "MED" else "")
        or ""
    )
    pmid = pmid if pmid.isdigit() else None
    pmcid = record.get("pmcid")
    pmcid = pmcid if pmcid and re.fullmatch(r"PMC\d+", pmcid) else None
    doi = (record.get("doi") or "").strip().removeprefix("https://doi.org/").lower()
    doi = doi if re.fullmatch(r"10\.\d{4,9}/\S+", doi) else None
    identifier = (
        "pmid:" + pmid
        if pmid
        else "doi:" + doi
        if doi
        else "epmc:" + str(record.get("source")) + ":" + str(record.get("id"))
    )
    abstract = plain(record.get("abstractText"))
    text = plain(record.get("title")) + "\n\n" + abstract
    if not abstract:
        return identifier, None, "abstract_unavailable"
    if (
        "retract" in " ".join(record.get("pubTypeList", {}).get("pubType", [])).lower()
        or record.get("isRetracted") == "Y"
    ):
        return identifier, None, "source_retraction_notice"
    doc = SourceDocument(
        id=identifier,
        kind="abstract",
        pmid=pmid,
        pmcid=pmcid,
        doi=doi,
        source_url=f"https://europepmc.org/article/{record['source']}/{record['id']}",
        version="europe-pmc-core/plain-v1",
        retrieved_at=now(),
        text=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
    )
    return identifier, doc, None


class EuropePMC:
    def __init__(self, client=None, page_size=100, max_pages=100, sleep=time.sleep):
        if not 1 <= page_size <= 1000 or max_pages < 1:
            raise ValueError("Invalid retrieval bounds")
        self.client = client or httpx.Client(timeout=30, follow_redirects=False)
        self.owned = client is None
        self.page_size = page_size
        self.max_pages = max_pages
        self.sleep = sleep

    def close(self):
        if self.owned:
            self.client.close()

    def page(self, query, cursor):
        for attempt in range(3):
            try:
                response = self.client.get(
                    BASE_URL,
                    params={
                        "query": query,
                        "format": "json",
                        "resultType": "core",
                        "pageSize": self.page_size,
                        "cursorMark": cursor,
                    },
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 2:
                        raise PipelineError("retrieval_retry_exhausted")
                    try:
                        delay = min(
                            max(float(response.headers.get("Retry-After", "0")), 0), 15
                        )
                    except ValueError:
                        delay = 0
                    self.sleep(max(delay, 2**attempt))
                    continue
                response.raise_for_status()
                body = response.json()
                if type(body.get("hitCount")) is not int or not isinstance(
                    body.get("resultList", {}).get("result"), list
                ):
                    raise PipelineError("malformed_retrieval_response")
                return body
            except httpx.TransportError:
                if attempt == 2:
                    raise PipelineError("retrieval_transport_failure") from None
                self.sleep(2**attempt)
            except (httpx.HTTPStatusError, ValueError):
                raise PipelineError("retrieval_response_failure") from None
        raise PipelineError("retrieval_retry_exhausted")

    def retrieve(self, target, since: date, until: date, state, heartbeat=lambda: None):
        query = query_for(target, since, until)
        key = digest(
            {"query": query, "target": target.model_dump(), "normalizer": "plain-v1"}
        )
        window = state.get("window", key) or {
            "id": key,
            "target_id": target.id,
            "target_scope": digest(target.model_dump()),
            "query": query,
            "since": since.isoformat(),
            "until": until.isoformat(),
            "cursor": "*",
            "seen": [],
            "pages": 0,
            "complete": False,
            "started_at": now().isoformat(),
        }
        if window["complete"]:
            return window
        for _ in range(self.max_pages):
            heartbeat()
            body = self.page(query, window["cursor"])
            records = body["resultList"]["result"]
            seen = set(window["seen"])
            candidates = []
            for record in records:
                if not record.get("id") or not record.get("source"):
                    raise PipelineError("source_identifier_missing")
                identity = str(record["source"]) + ":" + str(record["id"])
                identifier, doc, reason = document_from(record)
                candidates.append(
                    {
                        "id": digest([identifier, doc.sha256 if doc else record]),
                        "study_id": identifier,
                        "target_ids": [target.id],
                        "document": doc.model_dump(mode="json") if doc else None,
                        "reason": reason,
                        "metadata": record,
                    }
                )
                seen.add(identity)
            next_cursor = body.get("nextCursorMark")
            complete = len(seen) >= body["hitCount"]
            if not complete and (
                not records or not next_cursor or next_cursor == window["cursor"]
            ):
                raise PipelineError("incomplete_pagination")
            window = {
                **window,
                "seen": sorted(seen),
                "hit_count": body["hitCount"],
                "pages": window["pages"] + 1,
                "cursor": next_cursor or window["cursor"],
                "complete": complete,
                "updated_at": now().isoformat(),
            }
            # Source records and cursor advance together. Extraction failures do not
            # require searching an already durable window again.
            with state.transaction():
                for candidate in candidates:
                    old = state.get("candidate", candidate["id"])
                    if old:
                        candidate["target_ids"] = sorted(
                            set(old["target_ids"] + candidate["target_ids"])
                        )
                    state.put("candidate", candidate["id"], candidate)
                state.put("window", key, window)
            if complete:
                return window
        raise PipelineError("retrieval_page_budget_reached_resume_next_run")
