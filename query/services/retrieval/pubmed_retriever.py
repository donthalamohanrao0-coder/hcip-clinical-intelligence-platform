from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from ingestion.config import get_settings
from query.models.query import RetrievalQuery, RetrievalSource
from query.models.result import RetrievedChunk, RetrievalResult

from .base_retriever import BaseRetriever

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


class PubMedRetriever(BaseRetriever):
    """
    Live retrieval from NCBI PubMed via the free E-utilities REST API.

    Returns abstracts from the top-ranking articles for the query.
    chunk_id = "pubmed:{pmid}" so downstream agents can identify these as
    external references and apply appropriate citation / hallucination checks.

    Rate limits:
        Without PUBMED_API_KEY: 3 requests/second
        With    PUBMED_API_KEY: 10 requests/second
    """

    def __init__(self) -> None:
        cfg               = get_settings()
        self._api_key     = cfg.pubmed_api_key
        self._max_results = cfg.pubmed_max_results

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        if not query.include_pubmed:
            return RetrievalResult(source=RetrievalSource.PUBMED, chunks=[])

        start = time.monotonic()
        try:
            pmids = await self._esearch(query.query_text)
            if not pmids:
                return RetrievalResult(
                    source     = RetrievalSource.PUBMED,
                    chunks     = [],
                    latency_ms = (time.monotonic() - start) * 1000,
                )
            articles = await self._efetch(pmids)
        except Exception as exc:
            return RetrievalResult(
                source     = RetrievalSource.PUBMED,
                latency_ms = (time.monotonic() - start) * 1000,
                error      = str(exc),
            )

        chunks = [
            RetrievedChunk(
                chunk_id    = f"pubmed:{a['pmid']}",
                document_id = f"pubmed:{a['pmid']}",
                content     = a["abstract"] or a["title"],
                score       = 1.0 / (idx + 1),   # rank-decayed score
                rank        = idx,
                source      = RetrievalSource.PUBMED,
                metadata    = {
                    "pmid":        a["pmid"],
                    "title":       a["title"],
                    "authors":     a.get("authors", []),
                    "year":        a.get("year", ""),
                    "journal":     a.get("journal", ""),
                    "doi":         a.get("doi", ""),
                    "is_external": True,
                },
            )
            for idx, a in enumerate(articles)
            if a.get("abstract") or a.get("title")
        ]

        return RetrievalResult(
            source     = RetrievalSource.PUBMED,
            chunks     = chunks,
            latency_ms = (time.monotonic() - start) * 1000,
        )

    @staticmethod
    def _sanitize_query(query_text: str) -> str:
        # PubMed treats - + * as boolean/wildcard operators; strip them
        clean = re.sub(r"[+\-*/\\()\[\]{}|&^~!@#$%:;<>?=]", " ", query_text)
        return " ".join(clean.split())  # collapse whitespace

    async def _esearch(self, query_text: str) -> list[str]:
        params: dict[str, Any] = {
            "db":      "pubmed",
            "term":    self._sanitize_query(query_text),
            "retmax":  str(self._max_results),
            "retmode": "json",
            "sort":    "relevance",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_ESEARCH_URL, params=params)
            resp.raise_for_status()
            return resp.json().get("esearchresult", {}).get("idlist", [])

    async def _efetch(self, pmids: list[str]) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "db":      "pubmed",
            "id":      ",".join(pmids),
            "rettype": "abstract",
            "retmode": "xml",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_EFETCH_URL, params=params)
            resp.raise_for_status()
            return _parse_pubmed_xml(resp.text)

    def health_check(self) -> bool:
        try:
            r = httpx.get(
                _ESEARCH_URL,
                params={"db": "pubmed", "term": "test", "retmax": "1", "retmode": "json"},
                timeout=5.0,
            )
            return r.status_code == 200
        except Exception:
            return False


def _parse_pubmed_xml(xml_text: str) -> list[dict[str, Any]]:
    """Parse PubMed efetch XML into a list of article dicts."""
    articles: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return articles

    for article in root.findall(".//PubmedArticle"):
        medline = article.find("MedlineCitation")
        if medline is None:
            continue

        pmid_el = medline.find("PMID")
        pmid    = pmid_el.text if pmid_el is not None else ""

        art = medline.find("Article")
        if art is None:
            continue

        title_el = art.find("ArticleTitle")
        title    = "".join(title_el.itertext()) if title_el is not None else ""

        abstract_el = art.find("Abstract/AbstractText")
        abstract    = "".join(abstract_el.itertext()) if abstract_el is not None else ""

        authors = [
            f"{a.findtext('LastName', '')} {a.findtext('ForeName', '')}".strip()
            for a in art.findall("AuthorList/Author")
            if a.find("LastName") is not None
        ]

        journal_el = art.find("Journal/Title")
        journal    = journal_el.text if journal_el is not None else ""
        year_el    = art.find("Journal/JournalIssue/PubDate/Year")
        year       = year_el.text if year_el is not None else ""

        doi = ""
        for id_el in article.findall("PubmedData/ArticleIdList/ArticleId"):
            if id_el.get("IdType") == "doi":
                doi = id_el.text or ""
                break

        articles.append({
            "pmid":     pmid,
            "title":    title,
            "abstract": abstract,
            "authors":  authors,
            "journal":  journal,
            "year":     year,
            "doi":      doi,
        })

    return articles
