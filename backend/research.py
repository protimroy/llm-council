"""Retrieval helpers for second-round council prompts.

The council can run without retrieval, so every provider is best-effort:
network/search failures return an unavailable briefing instead of raising.
"""

from __future__ import annotations

import logging
import os
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Protocol
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx

from .models import CritiqueReport, FinalDecision
from .observability import apply_context_to_current_span, get_tracer, mark_span_ok, set_span_attributes

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)

BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
DUCKDUCKGO_SEARCH_ENDPOINT = "https://duckduckgo.com/html/"
MAX_QUERY_CHARS = 240
MAX_EXCERPT_CHARS = 900
DEFAULT_PROVIDER = "auto"


class SearchProvider(Protocol):
    """Common contract for search providers used by second-round retrieval."""

    name: str

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        max_results: int,
    ) -> List[Dict[str, str]]:
        """Return normalized search results with title, url, and snippet keys."""


class _DuckDuckGoHTMLParser(HTMLParser):
    """Extract result links and snippets from DuckDuckGo's HTML endpoint."""

    def __init__(self) -> None:
        super().__init__()
        self.results: List[Dict[str, str]] = []
        self._capturing_title = False
        self._capturing_snippet = False
        self._current_url = ""
        self._text_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        attr_map = {name: value or "" for name, value in attrs}
        class_name = attr_map.get("class", "")

        if tag == "a" and "result__a" in class_name:
            self._capturing_title = True
            self._current_url = _normalize_duckduckgo_url(attr_map.get("href", ""))
            self._text_parts = []
        elif "result__snippet" in class_name:
            self._capturing_snippet = True
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._capturing_title or self._capturing_snippet:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capturing_title:
            title = _clean_text(" ".join(self._text_parts))
            if title and self._current_url:
                self.results.append({
                    "title": title,
                    "url": self._current_url,
                    "snippet": "",
                    "provider": DuckDuckGoSearchProvider.name,
                })
            self._capturing_title = False
            self._current_url = ""
            self._text_parts = []
        elif self._capturing_snippet and tag in {"a", "div", "span"}:
            snippet = _clean_text(" ".join(self._text_parts))
            if snippet and self.results and not self.results[-1].get("snippet"):
                self.results[-1]["snippet"] = snippet
            self._capturing_snippet = False
            self._text_parts = []


class _ReadableHTMLParser(HTMLParser):
    """Extract readable text from a fetched HTML page."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "form", "nav"}

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, _attrs: List[tuple[str, Optional[str]]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            cleaned = _clean_text(data)
            if len(cleaned) > 30:
                self.text_parts.append(cleaned)

    def readable_text(self) -> str:
        return _clean_text(" ".join(self.text_parts))


class DuckDuckGoSearchProvider:
    """No-key fallback search provider using DuckDuckGo's HTML endpoint."""

    name = "duckduckgo"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        max_results: int,
    ) -> List[Dict[str, str]]:
        response = await client.get(
            f"{DUCKDUCKGO_SEARCH_ENDPOINT}?q={quote_plus(query)}",
            headers={"User-Agent": "LLM-Council/0.1 (+local research briefing)"},
        )
        response.raise_for_status()

        parser = _DuckDuckGoHTMLParser()
        parser.feed(response.text)
        return parser.results[:max_results]


class BraveSearchProvider:
    """Brave Search API provider, enabled with BRAVE_SEARCH_API_KEY."""

    name = "brave"

    def __init__(self, api_key: str, endpoint: str = BRAVE_SEARCH_ENDPOINT) -> None:
        self.api_key = api_key
        self.endpoint = endpoint

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        max_results: int,
    ) -> List[Dict[str, str]]:
        response = await client.get(
            self.endpoint,
            params={"q": query, "count": max_results},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            },
        )
        response.raise_for_status()
        data = response.json()
        raw_results = (data.get("web") or {}).get("results") or []
        results = []
        for item in raw_results[:max_results]:
            url = item.get("url") or ""
            title = _clean_text(item.get("title") or "")
            if not url or not title:
                continue
            results.append({
                "title": title,
                "url": url,
                "snippet": _clean_text(item.get("description") or ""),
                "provider": self.name,
            })
        return results


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def _normalize_duckduckgo_url(url: str) -> str:
    if not url:
        return ""
    absolute_url = urljoin("https://duckduckgo.com", url)
    parsed = urlparse(absolute_url)
    query = parse_qs(parsed.query)
    redirected = query.get("uddg", [None])[0]
    return unquote(redirected) if redirected else absolute_url


def _select_provider() -> Optional[SearchProvider]:
    provider_name = os.getenv("RESEARCH_SEARCH_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    brave_api_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()

    if provider_name in {"off", "none", "disabled"}:
        return None
    if provider_name == "brave":
        if not brave_api_key:
            raise RuntimeError("RESEARCH_SEARCH_PROVIDER=brave requires BRAVE_SEARCH_API_KEY")
        return BraveSearchProvider(brave_api_key, os.getenv("BRAVE_SEARCH_ENDPOINT", BRAVE_SEARCH_ENDPOINT))
    if provider_name == "duckduckgo":
        return DuckDuckGoSearchProvider()
    if provider_name != "auto":
        raise RuntimeError(f"Unsupported RESEARCH_SEARCH_PROVIDER '{provider_name}'")
    if brave_api_key:
        return BraveSearchProvider(brave_api_key, os.getenv("BRAVE_SEARCH_ENDPOINT", BRAVE_SEARCH_ENDPOINT))
    return DuckDuckGoSearchProvider()


def _build_research_query(
    user_query: str,
    final_decision: FinalDecision,
    critique_report: Optional[CritiqueReport],
) -> str:
    seeds = [user_query]

    if critique_report:
        unresolved = set(final_decision.unresolved_claims + final_decision.rejected_claims)
        for disagreement in critique_report.disagreements:
            if not unresolved or unresolved.intersection(disagreement.claim_ids):
                seeds.append(disagreement.description)
        for hypothesis in critique_report.top_hypotheses[:3]:
            if not unresolved or hypothesis.claim_id in unresolved:
                seeds.append(hypothesis.hypothesis)

    if final_decision.rationale:
        seeds.append(final_decision.rationale)

    query = _clean_text(" ".join(part for part in seeds if part))
    return query[:MAX_QUERY_CHARS]


async def _fetch_source_excerpt(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "skipped", ""

    try:
        response = await client.get(
            url,
            headers={"User-Agent": "LLM-Council/0.1 (+source excerpt)"},
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" in content_type.lower():
            parser = _ReadableHTMLParser()
            parser.feed(response.text)
            text = parser.readable_text()
        else:
            text = _clean_text(response.text)
        return "fetched" if text else "empty", _truncate(text, MAX_EXCERPT_CHARS)
    except Exception as exc:
        logger.debug("Failed to fetch source excerpt for %s: %s", url, exc)
        return "unavailable", ""


async def _add_source_excerpts(
    client: httpx.AsyncClient,
    results: List[Dict[str, str]],
    max_source_fetches: int,
) -> List[Dict[str, str]]:
    enriched = []
    for index, result in enumerate(results):
        enriched_result = dict(result)
        if index < max_source_fetches:
            status, excerpt = await _fetch_source_excerpt(client, result.get("url", ""))
            enriched_result["fetch_status"] = status
            if excerpt:
                enriched_result["content_excerpt"] = excerpt
        else:
            enriched_result["fetch_status"] = "not_fetched"
        enriched.append(enriched_result)
    return enriched


async def build_research_briefing(
    user_query: str,
    final_decision: FinalDecision,
    critique_report: Optional[CritiqueReport] = None,
    max_results: int = 5,
    max_source_fetches: int = 3,
) -> Dict[str, Any]:
    """Return a best-effort search briefing for unresolved second-round issues."""
    query = _build_research_query(user_query, final_decision, critique_report)

    with tracer.start_as_current_span("research.build_research_briefing", openinference_span_kind="retriever") as span:
        span.set_input({
            "query_characters": len(query),
            "max_results": max_results,
            "max_source_fetches": max_source_fetches,
            "unresolved_claim_count": len(final_decision.unresolved_claims),
            "rejected_claim_count": len(final_decision.rejected_claims),
        })
        set_span_attributes(
            span,
            research_query_characters=len(query),
            research_max_results=max_results,
            research_max_source_fetches=max_source_fetches,
        )
        apply_context_to_current_span()

        if not query:
            briefing = {
                "status": "skipped",
                "provider": "none",
                "query": "",
                "results": [],
                "summary": "No focused research query could be built.",
            }
            span.set_output({"status": briefing["status"], "provider": briefing["provider"], "result_count": 0})
            mark_span_ok(span)
            return briefing

        try:
            provider = _select_provider()
            if provider is None:
                briefing = {
                    "status": "skipped",
                    "provider": "disabled",
                    "query": query,
                    "results": [],
                    "summary": "Research retrieval is disabled.",
                }
                span.set_output({"status": briefing["status"], "provider": briefing["provider"], "result_count": 0})
                mark_span_ok(span)
                return briefing

            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                results = await provider.search(client, query, max_results)
                results = await _add_source_excerpts(client, results, max_source_fetches)

            excerpt_count = sum(1 for result in results if result.get("content_excerpt"))
            briefing = {
                "status": "ok" if results else "empty",
                "provider": provider.name,
                "query": query,
                "results": results,
                "source_excerpt_count": excerpt_count,
                "summary": (
                    f"Found {len(results)} search result(s) via {provider.name}; "
                    f"fetched {excerpt_count} source excerpt(s)."
                ),
            }
            span.set_output({
                "status": briefing["status"],
                "provider": provider.name,
                "result_count": len(results),
                "source_excerpt_count": excerpt_count,
            })
            mark_span_ok(span)
            return briefing
        except Exception as exc:
            logger.warning("Second-round research briefing failed: %s", exc)
            briefing = {
                "status": "unavailable",
                "provider": os.getenv("RESEARCH_SEARCH_PROVIDER", DEFAULT_PROVIDER).strip().lower(),
                "query": query,
                "results": [],
                "summary": "Search retrieval was unavailable; second round will proceed from council context only.",
                "error": str(exc),
            }
            span.set_output({"status": briefing["status"], "provider": briefing["provider"], "result_count": 0})
            mark_span_ok(span)
            return briefing


def format_research_briefing_for_prompt(briefing: Optional[Dict[str, Any]]) -> str:
    """Render a research briefing as prompt text."""
    if not briefing:
        return ""

    parts = [
        "TARGETED RESEARCH BRIEFING:",
        f"Status: {briefing.get('status', 'unknown')}",
        f"Provider: {briefing.get('provider', 'unknown')}",
    ]
    if briefing.get("query"):
        parts.append(f"Search query: {briefing['query']}")
    if briefing.get("summary"):
        parts.append(f"Summary: {briefing['summary']}")

    results = briefing.get("results") or []
    if results:
        parts.append("Search results and source excerpts to consider critically:")
        for index, result in enumerate(results, start=1):
            parts.append(f"  {index}. {result.get('title', 'Untitled')}")
            if result.get("url"):
                parts.append(f"     URL: {result['url']}")
            if result.get("snippet"):
                parts.append(f"     Snippet: {result['snippet']}")
            if result.get("content_excerpt"):
                parts.append(f"     Source excerpt: {result['content_excerpt']}")
        parts.append("Treat these as leads, not proof. Reconcile them against the original reasoning.")

    return "\n".join(parts)