#!/usr/bin/env python3
"""
LangGraph + vLLM: Perplexity-style assistant
Using proper LangChain tool calling pattern
"""

import json
import contextvars
import re
import time
import os
import copy
import threading
from collections import OrderedDict
from typing import Any, TypedDict, Sequence, Literal, List, Dict, Optional
from typing_extensions import Annotated
import httpx
from html.parser import HTMLParser
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_LLM_PROVIDERS = {"vllm", "openai", "anthropic", "google", "deepseek", "qwen"}

DEFAULT_SEARCH_CONFIG = {
    'num_queries': 5,  # Default number of parallel queries (1-6)
    'memory_enabled': True  # Whether to use conversation history (5 Q&A pairs)
}

CURRENT_LLM_CONFIG: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "liteplex_llm_config",
    default=None
)
CURRENT_SEARCH_CONFIG: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "liteplex_search_config",
    default=DEFAULT_SEARCH_CONFIG
)

# Configuration
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

# Default LLM Provider Configuration from environment
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "vllm").lower()
VLLM_URL = os.getenv("VLLM_URL", "http://localhost:1234/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "./Jan-v1-4B")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")


def read_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


SOURCE_READER_MAX_SOURCES = read_int_env("SOURCE_READER_MAX_SOURCES", 5, 0, 10)
SOURCE_READER_MAX_CHARS = read_int_env("SOURCE_READER_MAX_CHARS", 400000, 50000, 1000000)
SOURCE_READER_TIMEOUT_SECONDS = read_int_env("SOURCE_READER_TIMEOUT_SECONDS", 6, 2, 30)
SOURCE_READER_FALLBACK_SOURCES = read_int_env("SOURCE_READER_FALLBACK_SOURCES", 3, 0, 10)
SEARCH_CACHE_TTL_SECONDS = read_int_env("SEARCH_CACHE_TTL_SECONDS", 300, 0, 86400)
SOURCE_READER_CACHE_TTL_SECONDS = read_int_env("SOURCE_READER_CACHE_TTL_SECONDS", 1800, 0, 604800)

# Warn early but allow the app to start so health/config endpoints still work.
if not SERPER_API_KEY:
    logger.warning("SERPER_API_KEY not found. Web search requests will fail until it is configured.")


TRACKING_QUERY_PARAMS = {
    "fbclid", "gclid", "gbraid", "igshid", "mc_cid", "mc_eid", "msclkid",
    "oly_anon_id", "oly_enc_id", "ref", "s_kwcid", "spm", "vero_id", "yclid"
}


class TTLCache:
    """Small thread-safe TTL cache for repeat research requests."""

    def __init__(self, max_items: int, ttl_seconds: int):
        self.max_items = max_items
        self.ttl_seconds = ttl_seconds
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        if self.ttl_seconds <= 0 or self.max_items <= 0:
            return None

        now = time.monotonic()
        with self._lock:
            cached = self._items.get(key)
            if not cached:
                return None

            expires_at, value = cached
            if expires_at <= now:
                self._items.pop(key, None)
                return None

            self._items.move_to_end(key)
            return copy.deepcopy(value)

    def set(self, key: str, value: Any) -> None:
        if self.ttl_seconds <= 0 or self.max_items <= 0:
            return

        with self._lock:
            self._items[key] = (time.monotonic() + self.ttl_seconds, copy.deepcopy(value))
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)


SEARCH_RESULT_CACHE = TTLCache(max_items=256, ttl_seconds=SEARCH_CACHE_TTL_SECONDS)
SOURCE_PAGE_CACHE = TTLCache(max_items=128, ttl_seconds=SOURCE_READER_CACHE_TTL_SECONDS)


def is_tracking_query_param(name: str) -> bool:
    normalized = name.lower()
    return normalized.startswith("utm_") or normalized in TRACKING_QUERY_PARAMS


def normalize_url(url: str) -> str:
    """Normalize URLs for cache keys and duplicate detection without changing fetched content."""
    if not isinstance(url, str):
        return ""

    url = url.strip()
    if not url:
        return ""

    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc:
        return url

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return ""

    try:
        port = parsed.port
    except ValueError:
        port = None

    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "")
    path = "" if path == "/" else path.rstrip("/")
    query_params = [
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not is_tracking_query_param(name)
    ]
    query = urlencode(sorted(query_params), doseq=True)

    return urlunparse((scheme, netloc, path, parsed.params, query, ""))


def sanitize_llm_config(config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a request-scoped LLM config without accepting browser-supplied secrets."""
    if not config:
        return None

    provider = str(config.get('provider', LLM_PROVIDER)).lower()
    if provider not in ALLOWED_LLM_PROVIDERS:
        raise ValueError(f"Unsupported LLM provider: {provider}")

    sanitized = {
        'provider': provider,
        'model_name': str(config.get('modelName') or MODEL_NAME),
        'vllm_url': str(config.get('vllmUrl') or VLLM_URL)
    }

    return sanitized


def sanitize_search_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize user-tunable search settings for the current request."""
    sanitized = dict(DEFAULT_SEARCH_CONFIG)
    if not config:
        return sanitized

    try:
        num_queries = int(config.get('numQueries', sanitized['num_queries']))
    except (TypeError, ValueError):
        num_queries = sanitized['num_queries']

    sanitized['num_queries'] = min(max(num_queries, 1), 6)
    sanitized['memory_enabled'] = bool(config.get('memoryEnabled', sanitized['memory_enabled']))
    return sanitized


def get_current_search_config() -> Dict[str, Any]:
    return dict(CURRENT_SEARCH_CONFIG.get())


def step_event(step_id: str, label: str, status: str, detail: Optional[str] = None) -> str:
    payload = {"id": step_id, "label": label, "status": status}
    if detail:
        payload["detail"] = detail
    return f"STEP:{json.dumps(payload)}"


def describe_tool_calls(messages: Sequence[BaseMessage]) -> Optional[str]:
    for msg in reversed(messages):
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            continue

        query_count = 0
        previews: List[str] = []
        for tool_call in tool_calls:
            args = tool_call.get("args", {}) if isinstance(tool_call, dict) else {}
            queries = args.get("queries", []) if isinstance(args, dict) else []
            if isinstance(queries, list):
                query_count += len(queries)
                previews.extend(str(query) for query in queries[:3])

        if query_count:
            preview_text = "; ".join(previews[:3])
            return f"{query_count} planned queries: {preview_text}"
        return f"{len(tool_calls)} tool call(s) planned"

    return None


def parse_direct_answer(content: Any) -> Dict[str, Any]:
    if not isinstance(content, str):
        return {"answer": str(content or ""), "sources": []}

    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {"answer": content, "sources": []}

    if isinstance(parsed, dict):
        return {
            "answer": str(parsed.get("answer", "")),
            "sources": parsed.get("sources", []) if isinstance(parsed.get("sources", []), list) else []
        }

    return {"answer": content, "sources": []}

def set_llm_config(config):
    """Set request-local LLM configuration and ignore browser-supplied API keys."""
    sanitized = sanitize_llm_config(config)
    CURRENT_LLM_CONFIG.set(sanitized)
    if sanitized:
        logger.info(f"LLM config set for request: provider={sanitized.get('provider', 'unknown')}")
    return sanitized

def set_search_config(config):
    """Set request-local search configuration."""
    sanitized = sanitize_search_config(config)
    CURRENT_SEARCH_CONFIG.set(sanitized)
    logger.info(f"Search config set for request: queries={sanitized['num_queries']}, "
                f"memory={sanitized['memory_enabled']}")
    return sanitized

def get_llm_provider_config():
    """Get the current request's LLM provider configuration."""
    llm_config = CURRENT_LLM_CONFIG.get()

    if llm_config:
        return {
            'provider': llm_config['provider'],
            'api_key': None,
            'model_name': llm_config['model_name'],
            'vllm_url': llm_config['vllm_url']
        }
    
    # Fall back to environment variables
    return {
        'provider': LLM_PROVIDER,
        'api_key': None,
        'model_name': MODEL_NAME,
        'vllm_url': VLLM_URL
    }


# Helper function to extract domain from URL
def extract_domain(url: str) -> str:
    """Extract domain from URL for deduplication"""
    normalized = normalize_url(url)
    try:
        parsed = urlparse(normalized)
        domain = parsed.netloc.lower()
        return domain[4:] if domain.startswith("www.") else domain
    except (ValueError, AttributeError):
        return normalized.lower()

# Helper function to search single query
def search_single_query(query: str, num_results: int = 10) -> Dict:
    """Execute a single search query"""
    if not SERPER_API_KEY:
        raise RuntimeError("SERPER_API_KEY is not configured")

    cache_key = f"{num_results}:{query.strip().casefold()}"
    cached = SEARCH_RESULT_CACHE.get(cache_key)
    if cached:
        logger.info(f"♻️  [SEARCH CACHE] Reusing Serper results for '{query}'")
        return cached

    response = httpx.post(
        "https://google.serper.dev/search",
        json={"q": query, "num": num_results},
        headers={
            'X-API-KEY': SERPER_API_KEY,
            'Content-Type': 'application/json'
        },
        timeout=httpx.Timeout(5.0, connect=2.0)
    )
    response.raise_for_status()
    result = response.json()

    search_result = {
        'query': query,
        'results': result.get('organic', []),
        'answerBox': result.get('answerBox', None)
    }
    SEARCH_RESULT_CACHE.set(cache_key, search_result)
    return search_result


def deduplicate_results(all_results: List[Dict], max_per_domain: int = 2) -> List[Dict]:
    """Deduplicate exact URLs while preserving limited same-domain coverage for accuracy."""
    seen_urls = set()
    domain_counts: Dict[str, int] = {}
    deduplicated = []

    for result in all_results:
        link = result.get('link', '')
        normalized_url = normalize_url(link)
        parsed_url = urlparse(normalized_url)
        if (
            not normalized_url
            or parsed_url.scheme not in {"http", "https"}
            or normalized_url in seen_urls
        ):
            continue

        domain = extract_domain(normalized_url)
        if domain_counts.get(domain, 0) >= max_per_domain:
            continue

        seen_urls.add(normalized_url)
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        deduplicated.append({**result, 'normalizedLink': normalized_url})

    return deduplicated


class ReadableHTMLParser(HTMLParser):
    """Small dependency-free text extractor for source pages."""

    BLOCK_TAGS = {
        "article", "section", "p", "div", "br", "li", "tr", "td", "th",
        "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"
    }
    SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "iframe"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.skip_depth = 0
        self.canonical_url: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = {
            name.lower(): value
            for name, value in attrs
            if isinstance(name, str) and isinstance(value, str)
        }

        if tag == "link":
            rel = attrs_dict.get("rel", "").lower().split()
            href = attrs_dict.get("href")
            if "canonical" in rel and href:
                self.canonical_url = href

        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth == 0 and data.strip():
            self.parts.append(data.strip())

    def get_text(self) -> str:
        text = " ".join(self.parts)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        return text.strip()


STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "because", "been",
    "being", "can", "could", "did", "does", "for", "from", "had", "has",
    "have", "how", "into", "its", "latest", "more", "news", "not", "now",
    "price", "recent", "should", "than", "that", "the", "their", "then",
    "there", "these", "this", "today", "was", "were", "what", "when",
    "where", "which", "while", "who", "why", "with", "would", "you", "your"
}


def extract_terms(queries: List[str]) -> List[str]:
    terms = []
    for query in queries:
        for term in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9._-]+", query.lower()):
            if len(term) > 2 and term not in STOP_WORDS:
                terms.append(term)
    return sorted(set(terms))


def extract_readable_document(html: str, base_url: str) -> tuple[str, Optional[str]]:
    parser = ReadableHTMLParser()
    parser.feed(html)
    canonical_url = None
    if parser.canonical_url:
        canonical_url = normalize_url(urljoin(base_url, parser.canonical_url))
    return parser.get_text(), canonical_url


def extract_readable_text(html: str) -> str:
    text, _ = extract_readable_document(html, "")
    return text


def chunk_text(text: str, max_chars: int = 900) -> List[str]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}|(?<=[.!?])\s+(?=[A-Z0-9])", text) if p.strip()]
    chunks: List[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            for start in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[start:start + max_chars].strip())
            continue

        if len(current) + len(paragraph) + 1 > max_chars:
            if current:
                chunks.append(current.strip())
            current = paragraph
        else:
            current = f"{current} {paragraph}".strip()

    if current:
        chunks.append(current.strip())

    return chunks


def score_passage(passage: str, terms: List[str]) -> int:
    passage_lower = passage.lower()
    score = 0
    for term in terms:
        occurrences = passage_lower.count(term)
        if occurrences:
            score += occurrences * (3 if len(term) > 4 else 1)
    return score


def fetch_source_page(url: str) -> Optional[Dict[str, Any]]:
    """Fetch and cache readable source-page text."""
    normalized_url = normalize_url(url)
    if not normalized_url:
        return None

    parsed_url = urlparse(normalized_url)
    if parsed_url.scheme not in {"http", "https"}:
        return None

    cached = SOURCE_PAGE_CACHE.get(normalized_url)
    if cached:
        logger.info(f"♻️  [SOURCE CACHE] Reusing source page {normalized_url}")
        return cached

    try:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=httpx.Timeout(SOURCE_READER_TIMEOUT_SECONDS, connect=2.0),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; LitePlexBot/1.0; "
                    "+https://github.com/xiaoyu-work/LitePlex)"
                )
            }
        )
        response.raise_for_status()
    except Exception as exc:
        logger.info(f"Source fetch skipped for {url}: {exc}")
        return None

    final_url = normalize_url(str(response.url)) or normalized_url
    content_type = response.headers.get("content-type", "").lower()
    if content_type and not any(kind in content_type for kind in ("text/html", "text/plain", "application/xhtml")):
        logger.info(f"Source fetch skipped for {url}: unsupported content type {content_type}")
        return None

    raw_text = response.text[:SOURCE_READER_MAX_CHARS]
    readable_text, canonical_url = extract_readable_document(raw_text, str(response.url))
    if len(readable_text) < 200:
        return None

    page = {
        "url": canonical_url or final_url,
        "readable_text": readable_text
    }
    SOURCE_PAGE_CACHE.set(normalized_url, page)
    if final_url != normalized_url:
        SOURCE_PAGE_CACHE.set(final_url, page)
    if canonical_url and canonical_url not in {normalized_url, final_url}:
        SOURCE_PAGE_CACHE.set(canonical_url, page)

    return page


def fetch_source_evidence(source: Dict, queries: List[str]) -> Optional[Dict]:
    """Return the most relevant evidence excerpts from one source page."""
    url = source.get('url')
    if not url:
        return None

    page = fetch_source_page(url)
    if not page:
        return None

    terms = extract_terms(queries)
    passages = chunk_text(page["readable_text"])
    ranked = sorted(
        ((score_passage(passage, terms), index, passage) for index, passage in enumerate(passages)),
        key=lambda item: (-item[0], item[1])
    )

    excerpt_items = [
        {"text": passage, "score": score}
        for score, _, passage in ranked
        if score > 0
    ][:2]
    if not excerpt_items:
        excerpt_items = [
            {"text": passage, "score": score}
            for score, _, passage in ranked[:1]
        ]

    if not excerpt_items:
        return None

    return {
        "index": source["index"],
        "title": source["title"],
        "url": page["url"],
        "excerpts": [item["text"] for item in excerpt_items],
        "evidence": excerpt_items,
        "bestScore": ranked[0][0] if ranked else 0
    }


def select_source_candidates(sources: List[Dict], max_sources: int) -> List[Dict]:
    """Select unique source URLs, keeping fallbacks for failed or low-signal pages."""
    candidate_limit = min(len(sources), max_sources + SOURCE_READER_FALLBACK_SOURCES)
    candidates: List[Dict] = []
    seen_urls = set()

    for source in sources:
        normalized_url = normalize_url(source.get('url', ''))
        parsed_url = urlparse(normalized_url)
        if parsed_url.scheme not in {"http", "https"} or normalized_url in seen_urls:
            continue

        seen_urls.add(normalized_url)
        candidates.append({**source, "normalizedUrl": normalized_url})
        if len(candidates) >= candidate_limit:
            break

    return candidates


def collect_source_evidence(sources: List[Dict], queries: List[str]) -> List[Dict]:
    """Read top search results in parallel and extract relevant evidence passages."""
    max_sources = min(SOURCE_READER_MAX_SOURCES, len(sources))
    if max_sources <= 0:
        return []

    evidence: List[Dict] = []
    candidates = select_source_candidates(sources, max_sources)
    if not candidates:
        return []

    start = time.time()

    with ThreadPoolExecutor(max_workers=min(6, len(candidates))) as executor:
        future_to_source = {
            executor.submit(fetch_source_evidence, source, queries): source
            for source in candidates
        }
        for future in as_completed(future_to_source):
            try:
                item = future.result(timeout=8)
                if item:
                    evidence.append(item)
            except Exception as exc:
                source = future_to_source[future]
                logger.info(f"Evidence extraction failed for {source.get('url')}: {exc}")

    evidence.sort(key=lambda item: (-item.get("bestScore", 0), item["index"]))
    selected_evidence = evidence[:max_sources]
    logger.info(
        f"📖 [SOURCE READER] Extracted evidence from {len(selected_evidence)}/"
        f"{max_sources} sources using {len(candidates)} candidate pages in {time.time() - start:.2f}s"
    )
    return selected_evidence


SUPERSCRIPT_TO_DIGIT = str.maketrans({
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
    "⁻": "-"
})


def parse_citation_numbers(value: str) -> List[int]:
    normalized = value.translate(SUPERSCRIPT_TO_DIGIT)
    numbers: List[int] = []

    for part in re.split(r"[,;\s]+", normalized):
        if not part:
            continue

        if "-" in part:
            try:
                start, end = [int(item) for item in part.split("-", 1)]
            except ValueError:
                continue
            if 0 < start <= end <= 100:
                numbers.extend(range(start, end + 1))
            continue

        if part.isdigit():
            numbers.append(int(part))

    return list(dict.fromkeys(numbers))


def clean_claim_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -:;")


def claim_before_citation(answer: str, citation_start: int) -> str:
    prefix = answer[max(0, citation_start - 700):citation_start]
    sentence_start = max(prefix.rfind(". "), prefix.rfind("? "), prefix.rfind("! "), prefix.rfind("\n"))
    claim = prefix[sentence_start + 1:] if sentence_start >= 0 else prefix
    return clean_claim_text(claim)[-400:]


def extract_cited_claims(answer: str) -> Dict[int, List[str]]:
    cited_claims: Dict[int, List[str]] = {}
    patterns = [
        re.compile(r"<sup>\s*([\d,\s;\-]+)\s*</sup>", re.IGNORECASE),
        re.compile(r"([⁰¹²³⁴⁵⁶⁷⁸⁹][⁰¹²³⁴⁵⁶⁷⁸⁹⁻,\s]*)")
    ]

    for pattern in patterns:
        for match in pattern.finditer(answer):
            raw_citation = match.group(1)
            numbers = parse_citation_numbers(raw_citation)
            if not numbers:
                continue

            claim = claim_before_citation(answer, match.start())
            if not claim:
                continue

            for number in numbers:
                cited_claims.setdefault(number, []).append(claim)

    return cited_claims


def source_evidence_items(evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = evidence.get("evidence")
    if isinstance(items, list) and items:
        return [
            {"text": str(item.get("text", "")), "score": int(item.get("score", 0))}
            for item in items
            if isinstance(item, dict) and item.get("text")
        ]

    return [
        {"text": str(excerpt), "score": int(evidence.get("bestScore", 0))}
        for excerpt in evidence.get("excerpts", [])
        if excerpt
    ]


def apply_evidence_to_sources(sources: List[Dict], evidence_data: List[Dict]) -> List[Dict]:
    sources_by_index = {source["index"]: source for source in sources}

    for evidence in evidence_data:
        source = sources_by_index.get(evidence.get("index"))
        if not source:
            continue

        source["url"] = evidence.get("url") or source["url"]
        source["evidence"] = source_evidence_items(evidence)
        source["evidenceScore"] = int(evidence.get("bestScore", 0))

    return sources


def score_claim_against_excerpts(claim: str, excerpts: List[str]) -> Dict[str, Any]:
    terms = extract_terms([claim])
    if not terms:
        return {"ratio": 0.0, "overlapTerms": [], "matchedExcerpt": ""}

    unique_terms = sorted(set(terms))
    best = {"ratio": 0.0, "overlapTerms": [], "matchedExcerpt": ""}

    for excerpt in excerpts:
        excerpt_lower = excerpt.lower()
        overlap_terms = [term for term in unique_terms if term in excerpt_lower]
        ratio = len(overlap_terms) / len(unique_terms)

        if ratio > best["ratio"] or (
            ratio == best["ratio"] and len(overlap_terms) > len(best["overlapTerms"])
        ):
            best = {
                "ratio": ratio,
                "overlapTerms": overlap_terms,
                "matchedExcerpt": excerpt
            }

    return best


def verify_source_citations(answer: str, sources: List[Dict]) -> List[Dict]:
    """Lightweight citation check using already extracted evidence only."""
    cited_claims = extract_cited_claims(answer)
    verified_sources = copy.deepcopy(sources)

    for source in verified_sources:
        source_index = source.get("index")
        claims = cited_claims.get(source_index, [])
        evidence_items = source.get("evidence", [])
        excerpts = [
            str(item.get("text", ""))
            for item in evidence_items
            if isinstance(item, dict) and item.get("text")
        ]

        if not claims:
            source["citationCheck"] = {
                "cited": False,
                "confidence": "uncited",
                "reason": "This source was returned for context but was not cited in the final answer."
            }
            continue

        if not excerpts:
            source["citationCheck"] = {
                "cited": True,
                "confidence": "low",
                "reason": "The answer cites this source, but no readable evidence excerpt was extracted.",
                "claims": claims[:3]
            }
            continue

        best_claim = ""
        best_match: Dict[str, Any] = {"ratio": 0.0, "overlapTerms": [], "matchedExcerpt": ""}
        for claim in claims:
            match = score_claim_against_excerpts(claim, excerpts)
            if match["ratio"] > best_match["ratio"]:
                best_match = match
                best_claim = claim

        overlap_count = len(best_match["overlapTerms"])
        if best_match["ratio"] >= 0.35 or overlap_count >= 4:
            confidence = "supported"
            reason = "The cited sentence overlaps with extracted source evidence."
        elif overlap_count > 0:
            confidence = "partial"
            reason = "The cited sentence has partial overlap with extracted source evidence."
        else:
            confidence = "low"
            reason = "The cited sentence did not have clear overlap with extracted evidence."

        source["citationCheck"] = {
            "cited": True,
            "confidence": confidence,
            "reason": reason,
            "claims": claims[:3],
            "matchedExcerpt": best_match["matchedExcerpt"],
            "overlapTerms": best_match["overlapTerms"][:8],
            "checkedClaim": best_claim
        }

    return verified_sources

# Import for tool schema
from pydantic import BaseModel, Field, field_validator

class GoogleSearchInput(BaseModel):
    """Input schema for google_search tool"""
    queries: List[str] = Field(
        description="List of search queries for comprehensive coverage; the tool also reads top source pages for evidence"
    )
    
    @field_validator('queries')
    @classmethod
    def validate_queries_count(cls, v: List[str]) -> List[str]:
        # Adjust to configured number of queries
        target_count = get_current_search_config().get('num_queries', 5)
        queries = [query.strip() for query in v if isinstance(query, str) and query.strip()]
        if not queries:
            raise ValueError("At least one non-empty search query is required")

        if len(queries) < target_count:
            # Pad with variations of existing queries
            while len(queries) < target_count:
                queries.append(queries[0])
        elif len(queries) > target_count:
            queries = queries[:target_count]
        return queries

# Main search tool - now accepts multiple queries
@tool(args_schema=GoogleSearchInput)
def google_search(queries: List[str]) -> str:
    """
    Search Google with multiple queries, read top source pages, and extract evidence passages.
    Number of queries is configurable (1-6) for optimal balance of speed and coverage.
    
    Args:
        queries: List of search queries (will be adjusted to configured count)
    """
    start_time = time.time()
    
    # Validate input
    if not isinstance(queries, list):
        queries = [queries] if isinstance(queries, str) else []
    queries = [query.strip() for query in queries if isinstance(query, str) and query.strip()]
    if not queries:
        return json.dumps({'text': "Search failed: no valid search queries were provided.", 'sources': []})
    
    # Adjust to configured number of queries
    target_count = get_current_search_config().get('num_queries', 5)
    if len(queries) < target_count:
        logger.info(f"📝 Expanding to {target_count} queries (received {len(queries)})")
        while len(queries) < target_count:
            queries.append(queries[0] if queries else "")
    elif len(queries) > target_count:
        logger.info(f"📝 Limiting to {target_count} queries (received {len(queries)})")
        queries = queries[:target_count]
    
    logger.info(f"🔍 [MULTI-SEARCH START] Executing {len(queries)} queries in parallel")
    for i, q in enumerate(queries, 1):
        logger.info(f"  Query {i}: {q}")
    
    try:
        # Parallel execution for maximum speed
        all_results = []
        all_answer_boxes = []
        results_by_query: Dict[int, List[Dict]] = {}
        answer_boxes_by_query: Dict[int, Any] = {}
        errors = []
        
        with ThreadPoolExecutor(max_workers=6) as executor:
            # Submit all queries at once
            future_to_query = {
                executor.submit(search_single_query, query, 10): (index, query)
                for index, query in enumerate(queries)
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_query):
                query_index, query = future_to_query[future]
                try:
                    result = future.result(timeout=3)  # 3 second timeout per query
                    results_by_query[query_index] = result['results']
                    if result['answerBox']:
                        answer_boxes_by_query[query_index] = result['answerBox']
                    logger.info(f"✅ Query completed: '{query}' - {len(result['results'])} results")
                except Exception as e:
                    logger.error(f"❌ Query failed: '{query}' - {e}")
                    errors.append(str(e))

        for query_index in range(len(queries)):
            all_results.extend(results_by_query.get(query_index, []))
            answer_box = answer_boxes_by_query.get(query_index)
            if answer_box:
                all_answer_boxes.append(answer_box)
        
        parallel_time = time.time() - start_time
        logger.info(f"⏱️  [PARALLEL SEARCH] All queries completed in: {parallel_time:.2f}s")

        if not all_results and not all_answer_boxes and errors:
            return json.dumps({'text': f"Search failed: {errors[0]}", 'sources': []})
        
        # Deduplicate exact URLs and limit per-domain repeats while preserving coverage.
        dedup_start = time.time()
        unique_results = deduplicate_results(all_results)
        dedup_time = time.time() - dedup_start
        logger.info(f"⏱️  [DEDUPLICATION] {len(all_results)} → {len(unique_results)} results in {dedup_time:.2f}s")
        
        # Format results
        format_start = time.time()
        formatted = f"Search results for {len(queries)} queries:\n\n"
        
        # Add answer boxes if available
        if all_answer_boxes:
            formatted += "Quick Answers:\n"
            for i, answer in enumerate(all_answer_boxes[:3], 1):  # Limit to 3 answer boxes
                if isinstance(answer, dict):
                    formatted += f"{i}. {answer.get('answer', answer.get('snippet', ''))}\n"
            formatted += "\n"
        
        # Format unique results
        sources_data = []
        formatted += "Search Results:\n"
        
        for i, item in enumerate(unique_results[:40], 1):  # Limit to 40 unique results
            title = item.get('title', '')
            snippet = item.get('snippet', '')
            link = item.get('link', '')
            
            formatted += f"\n[{i}] {title}\n"
            formatted += f"    {snippet}\n"
            formatted += f"    URL: {link}\n"
            
            sources_data.append({
                'index': i,
                'title': title,
                'url': link,
                'normalizedUrl': item.get('normalizedLink') or normalize_url(link)
            })

        evidence_data = collect_source_evidence(sources_data, queries)
        sources_data = apply_evidence_to_sources(sources_data, evidence_data)

        if evidence_data:
            formatted += "\n\nEvidence Extracted from Source Pages (ordered by relevance):\n"
            for evidence in evidence_data:
                formatted += f"\n[{evidence['index']}] {evidence['title']}\n"
                for excerpt_index, excerpt in enumerate(evidence["evidence"], 1):
                    formatted += f"    Evidence {excerpt_index}: {excerpt['text']}\n"
                formatted += f"    URL: {evidence['url']}\n"
        else:
            formatted += "\n\nEvidence Extracted from Source Pages:\n"
            formatted += "    Source reader could not extract page text; use search snippets cautiously.\n"
        
        format_time = time.time() - format_start
        logger.info(f"⏱️  [FORMAT] Formatting took: {format_time:.2f}s")
        
        total_time = time.time() - start_time
        logger.info(f"🎯 [SEARCH COMPLETE] Total time: {total_time:.2f}s | Unique results: {len(unique_results)}")
        
        return json.dumps({
            'text': formatted,
            'sources': sources_data,
            'evidence': evidence_data
        })
        
    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"❌ [SEARCH ERROR] Failed after {total_time:.2f}s: {e}")
        return json.dumps({'text': f"Search failed: {str(e)}", 'sources': []})


# Define the graph state
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_question: str  # Store the original user question for summarization


# Initialize LLM with tools properly bound
def create_llm_with_tools():
    """Create LLM with tools properly bound using LangChain pattern"""
    
    # Get current configuration
    config = get_llm_provider_config()
    provider = config['provider']
    model_name = config['model_name']
    
    logger.info(f"🔧 Creating LLM with provider: {provider}")
    logger.info(f"📝 Model: {model_name}")
    if provider == "vllm":
        logger.info(f"🌐 vLLM URL: {config.get('vllm_url')}")
    
    # Create LLM instance based on provider
    if provider == "vllm":
        llm = ChatOpenAI(
            base_url=config['vllm_url'],
            model=model_name,
            api_key="not-needed",  # vLLM doesn't need API key
            temperature=0.7,
            max_tokens=16384,  # Use larger context window
            streaming=True  # Enable streaming for token-by-token output
        )
    elif provider == "openai":
        llm = ChatOpenAI(
            api_key=config['api_key'] or OPENAI_API_KEY,
            model=model_name,
            temperature=0.7,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "anthropic":
        llm = ChatAnthropic(
            api_key=config['api_key'] or ANTHROPIC_API_KEY,
            model=model_name,
            temperature=0.7,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "google":
        api_key = config['api_key'] or GOOGLE_API_KEY
        if not api_key:
            logger.error("❌ Google API key not configured!")
            raise ValueError("Google API key not configured. Please set GOOGLE_API_KEY in the backend environment.")
        logger.info(f"🌟 Using Google Gemini")
        logger.info(f"  - Model: {model_name}")
        try:
            llm = ChatGoogleGenerativeAI(
                google_api_key=api_key,
                model=model_name,
                temperature=0.7,
                streaming=True
            )
            logger.info("✅ Google Gemini LLM initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Google Gemini: {e}")
            raise
    elif provider == "deepseek":
        llm = ChatOpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=config['api_key'] or DEEPSEEK_API_KEY,
            model=model_name,
            temperature=0.7,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "qwen":
        llm = ChatOpenAI(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=config['api_key'] or DASHSCOPE_API_KEY,
            model=model_name,
            temperature=0.7,
            max_tokens=4096,
            streaming=True
        )
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")
    
    # Bind tools to LLM (this is the proper LangChain way)
    tools = [google_search]
    llm_with_tools = llm.bind_tools(tools)
    
    return llm_with_tools, tools


# Agent node - calls LLM with tools
def agent_node(state: AgentState) -> dict:
    """
    Agent node: LLM with tools bound decides what to do
    """
    node_start = time.time()
    logger.info("🤖 [AGENT NODE START]")
    
    messages = state["messages"]
    
    # Extract user question from the last human message
    user_question = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_question = msg.content
            break
    
    # Get LLM with tools
    setup_start = time.time()
    llm_with_tools, _ = create_llm_with_tools()
    setup_time = time.time() - setup_start
    logger.info(f"⏱️  [AGENT SETUP] LLM setup took: {setup_time:.2f}s")
    
    # Simple system message - just decide whether to use tools
    system_message = SystemMessage(content="""You are a helpful research assistant with access to web search and source reading.

DECISION FLOW:
1. For greetings, simple chat, or meta questions → Respond directly with JSON (no tools)
2. For stock/company/current-information queries → Use google_search tool
3. For factual questions or information requests → Use google_search tool
4. When unsure → Use google_search tool

STOCK QUERIES:
For ANY mention of stocks/companies (Tesla, TSLA, Apple, etc.):
- ALWAYS use google_search to get current info
- Include "stock price" and "stock news" in searches
- The summarizer will add [STOCK_CHART:TICKER] automatically

Example: "show me tsla and tell me recent news"
→ google_search(["TSLA stock price", "Tesla stock news today", "TSLA recent announcements", "Tesla latest developments", "TSLA stock analysis"])

OUTPUT FORMAT (when NOT using tools):
{
  "answer": "Your response in markdown format or [STOCK_CHART:SYMBOL] for stocks",
  "sources": []
}

WHEN TO USE TOOLS:
Use google_search for:
   - How-to questions (how to make, how to do, how to...)
   - Recipe or cooking questions
   - Factual questions, current events, or real-world information
   - Questions needing specific data or up-to-date information
   - General stock market questions (not specific tickers)

WHEN NOT TO USE TOOLS (respond directly with JSON):
   - Greetings (hi, hello, hey, good morning, etc.)
   - Thank you messages
   - Simple acknowledgments
   - Clarification requests about the conversation
   - Meta questions about yourself or this system

IMPORTANT:
The google_search tool requires a LIST of queries, not a single string.
It searches the web, reads top source pages, and returns extracted evidence passages for grounded citations.

MULTI-QUERY SEARCH REQUIREMENTS:
Provide queries as a list to google_search tool (system will adjust to configured count).
Generate diverse queries that cover different aspects of the user's question.

QUERY GENERATION STRATEGY:
- Query 1: User's exact question
- Query 2-3: Add context, related terms, or specific aspects
- Query 4-5: Alternative phrasings or different angles
- Query 6: Focus on authoritative sources or specific details

EXAMPLES:
User: "Trump Putin meeting"
Call: google_search(["Trump Putin meeting", "Trump Putin summit Alaska", "Trump Putin meeting outcomes", "Trump Putin Ukraine negotiations", "Trump Putin latest talks"])

User: "how to make milk tea"
Call: google_search(["how to make milk tea", "milk tea recipe ingredients", "bubble tea preparation steps", "homemade milk tea tutorial", "traditional milk tea method"])

User: "AAPL stock and why is it dropping?"
Call: google_search(["AAPL stock price today", "Apple stock dropping reasons", "AAPL news today", "Apple stock analysis", "Why is Apple stock down"])

User: "TSLA and recent news"
Call: google_search(["TSLA stock price", "Tesla stock news today", "Tesla latest announcements", "TSLA stock analysis", "Tesla Elon Musk news"])

IMPORTANT:
- DO NOT add years/dates unless user mentions them
- Each query should be distinct but related
- Always pass queries as a list: google_search([...])""")
    
    # Combine system message with conversation
    full_messages = [system_message] + list(messages)
    
    logger.info("🤖 [AGENT DECISION] LLM is deciding whether to use tools...")
    
    # Invoke LLM with tools - it will decide whether to use them
    llm_start = time.time()
    response = llm_with_tools.invoke(full_messages)
    llm_time = time.time() - llm_start
    logger.info(f"⏱️  [AGENT LLM] LLM decision took: {llm_time:.2f}s")
    
    # Log what LLM decided
    if response.tool_calls:
        logger.info(f"🔧 [AGENT TOOLS] LLM decided to use tools: {[tc['name'] for tc in response.tool_calls]}")
    else:
        logger.info("💬 [AGENT DIRECT] LLM responded directly without tools")
    
    total_time = time.time() - node_start
    logger.info(f"✅ [AGENT NODE COMPLETE] Total time: {total_time:.2f}s")
    
    return {"messages": [response], "user_question": user_question}


# Summarize node - takes tool results and summarizes them
def summarize_node(state: AgentState) -> dict:
    """
    Summarize node: Takes search results and user's question to create a focused answer
    """
    node_start = time.time()
    logger.info("📝 [SUMMARIZE NODE START]")
    
    messages = state["messages"]
    user_question = state.get("user_question", "")
    
    # Get the last tool result message (search results)
    parse_start = time.time()
    tool_result = None
    sources_data = []
    for msg in reversed(messages):
        if hasattr(msg, 'content') and msg.content:
            try:
                # Try to parse as JSON (new format)
                data = json.loads(msg.content)
                if 'text' in data and 'Search results for' in data['text']:
                    tool_result = data['text']
                    sources_data = data.get('sources', [])
                    break
            except (json.JSONDecodeError, ValueError, TypeError):
                # Fallback to old format
                if 'Search results for' in str(msg.content):
                    tool_result = msg.content
                    break

    parse_time = time.time() - parse_start
    logger.info(f"⏱️  [SUMMARIZE PARSE] Message parsing took: {parse_time:.2f}s")
    
    if not tool_result:
        # If no tool results, just pass through
        logger.info("⚠️  [SUMMARIZE SKIP] No tool results to summarize")
        return {"messages": []}
    
    # Get conversation history (last 5 exchanges)
    conversation_history = []
    for msg in messages[-10:]:  # Last 10 messages (5 exchanges)
        if isinstance(msg, HumanMessage):
            conversation_history.append(f"User: {msg.content}")
        elif isinstance(msg, AIMessage) and not hasattr(msg, 'tool_calls'):
            # Only include AI responses, not tool calls
            conversation_history.append(f"Assistant: {msg.content[:200]}...")  # Truncate long responses
    
    # Get current configuration for summarization
    config = get_llm_provider_config()
    provider = config['provider']
    model_name = config['model_name']
    
    # Create a simple LLM without tools for streaming based on provider
    if provider == "vllm":
        llm = ChatOpenAI(
            base_url=config['vllm_url'],
            model=model_name,
            api_key="not-needed",
            temperature=0.3,  # Lower temperature for accurate, fact-based summaries
            max_tokens=28000,  # Use most of the 32k context for output
            streaming=True  # Enable streaming for token-by-token output
        )
    elif provider == "openai":
        llm = ChatOpenAI(
            api_key=config['api_key'] or OPENAI_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "anthropic":
        llm = ChatAnthropic(
            api_key=config['api_key'] or ANTHROPIC_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "google":
        llm = ChatGoogleGenerativeAI(
            google_api_key=config['api_key'] or GOOGLE_API_KEY,
            model=model_name,
            temperature=0.1,  # Lower temperature for faster generation
            top_p=0.8,  # Reduce diversity for speed
            streaming=True
        )
    elif provider == "deepseek":
        llm = ChatOpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=config['api_key'] or DEEPSEEK_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "qwen":
        llm = ChatOpenAI(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=config['api_key'] or DASHSCOPE_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")
    
    # Create a focused prompt that answers the user's specific question
    summarize_prompt = SystemMessage(content="""You are a helpful assistant providing comprehensive, detailed answers like Perplexity.

MANDATORY RULE FOR STOCK QUERIES:
If the user asks about ANY company/stock (Tesla, TSLA, Apple, etc.) AND you see stock prices/tickers in search results:
→ Line 1 of your "answer" field MUST be: [STOCK_CHART:TICKER]
→ Line 2: Empty line (\\n\\n)
→ Line 3+: Your markdown content

CORRECT EXAMPLE for "show me tsla and tell me recent news":
{
  "answer": "[STOCK_CHART:TSLA]\\n\\n## Tesla Stock Overview\\n\\nTesla is currently trading at...",
  "sources": [{"index": 1, "title": "...", "url": "..."}]
}

WRONG EXAMPLE (missing stock chart):
{
  "answer": "## Tesla Stock Overview\\n\\nTesla is currently trading at...",
  "sources": [...]
}

OUTPUT FORMAT:
You MUST ALWAYS respond with a valid JSON object in this exact format:
{
  "answer": "Your complete markdown-formatted answer with citations using <sup>1,2,3</sup> tags",
  "sources": [
    {"index": 1, "title": "Source Title", "url": "https://example.com"},
    {"index": 2, "title": "Another Source", "url": "https://example2.com"}
  ]
}

Note: If you don't have sources (e.g., for greetings or direct answers), use empty array: "sources": []

IMPORTANT:
- The "answer" field should contain your full response in Markdown format
- Use sequential citation numbers starting from 1 (e.g., <sup>1</sup>, <sup>2</sup>, <sup>3</sup>)
- The "sources" array must be renumbered sequentially starting from 1
- Sources should be listed in the order they are first cited in your answer
- Each source must have index, title, and url
- DO NOT include the sources list in the answer field
- DO NOT skip numbers - if you cite sources from search results #1, #14, #19, renumber them as 1, 2, 3


ANSWER STYLE:
- Provide COMPREHENSIVE answers like Perplexity - extract and organize EVERY relevant detail
- Use PROPER MARKDOWN formatting:
  * Use ## for section headers
  * Use numbered lists: 1. 2. 3. for steps
  * Use bullet points: - or * for unordered lists
  * Add blank lines between sections for proper spacing
- Structure your answer based on the question type:

FOR EVENTS/NEWS (meetings, incidents, announcements):
  ## Background
  • Context and setup
  
  ## Key Developments
  • Timeline of events
  • Important moments
  
  ## Outcomes & Impact
  • Results and consequences
  • Different perspectives
  
  ## Future Implications
  • What's next

FOR HOW-TO/TUTORIALS (recipes, guides, instructions):
  Use this exact structure with proper markdown:
  
  ## Overview
  [Brief description paragraph]
  
  ## Requirements  
  - First requirement
  - Second requirement
  - Third requirement
  
  ## Step-by-Step Instructions
  1. First step with citation <sup>1</sup>
  2. Second step with citation <sup>2</sup>  
  3. Third step with citation <sup>3</sup>
  4. Continue numbering...
  
  ## Tips & Variations
  - First tip
  - Second tip
  - Alternative approaches
  
  ## Common Mistakes to Avoid
  - First mistake to avoid
  - Second mistake to avoid

FOR TECHNICAL/ERROR QUESTIONS:
  ## Problem Description
  What the error/issue is
  
  ## Root Cause
  Why this happens
  
  ## Solutions
  ### Method 1: [Name]
  • Steps to resolve
  • Code example if needed
  
  ### Method 2: [Name]
  • Alternative approach
  
  ## Best Practices
  • How to prevent this

FOR GENERAL INFORMATION:
  ## Overview
  Definition and introduction
  
  ## Key Information
  • Important facts
  • Core details
  
  ## Categories/Types
  • Different variations
  • Classifications
  
  ## Examples
  • Real-world applications
  • Use cases

ALWAYS:
- Include ALL specific details: dates, names, numbers, quotes, locations
- Use multiple paragraphs with smooth transitions  
- Aim for 300-600 words for completeness
- Present conflicting information if it exists
- End with a summary or key takeaways when appropriate

CRITICAL CITATION RULES:
⚠️ CITATIONS ARE MANDATORY - Every factual claim MUST have a citation
⚠️ Place citations IMMEDIATELY after the sentence containing the information
⚠️ NEVER group citations at the end of paragraphs
⚠️ Each distinct fact needs its own citation
⚠️ DO NOT include source URLs or links in the main answer text - only use <sup> numbers
⚠️ Prefer "Evidence Extracted from Source Pages" over search snippets
⚠️ Only cite sources whose evidence or snippet directly supports the sentence

FORMATTING RULES:
⚠️ Output valid GitHub-Flavored Markdown in the "answer" field
⚠️ Use ## for main headers, ### for subheaders
⚠️ Use - for bullet points (NOT • or *)
⚠️ Use 1. 2. 3. for numbered lists with proper spacing
⚠️ Add blank lines between sections (use \\n\\n in JSON)
⚠️ Format lists properly:
   - For bullet points: "- Item one\\n- Item two\\n- Item three"  
   - For numbered: "1. Step one\\n2. Step two\\n3. Step three"
⚠️ DO NOT use <br> tags - use \\n for line breaks in JSON

FORBIDDEN PHRASES (NEVER USE):
- "According to my search..."
- "Based on the information I found..."
- "The search results show..."
- "From what I gathered..."
Just state the facts directly with citations.

DECISION PROCESS:
1. Check if search results are relevant to the user's question
2. If relevant: Use them comprehensively with citations
3. If not relevant: Answer from knowledge without citations

IMPORTANT:
- Be comprehensive but stay focused on the question
- Use formatting (bullet points, sections) to improve readability
- Include practical examples and step-by-step solutions when applicable

CITATION RENUMBERING RULES:
When citing search results, you MUST renumber them sequentially:
- If you cite search results #8, #1, #4, #16, #17, #18, #25, #24, #2, #12, #11
- Renumber them as 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 in your answer
- In the JSON "sources" array, list them with these new sequential numbers

EXAMPLE:
Search result #8 becomes citation <sup>1</sup> and source index 1
Search result #16 becomes citation <sup>2</sup> and source index 2
And so on...

The key is: Citations must be numbered 1, 2, 3, 4... regardless of original search result numbers

WHEN ANSWERING DIRECTLY (search results not relevant or simple greeting):
- Still use JSON format: {"answer": "Your response", "sources": []}
- Write your answer WITHOUT citations
- Keep sources array empty

VERY IMPORTANT:
- ALWAYS output valid JSON format
- If you have citations, include sources in the array
- If no citations, sources array must be empty []
- Always renumber citations sequentially starting from 1
- The numbers in your <sup> tags should be 1,2,3,4... based on order of use
""")
    
    # Build the context with conversation history
    context = ""
    if conversation_history:
        context += "Recent conversation:\n" + "\n".join(conversation_history[-4:]) + "\n\n"  # Last 2 exchanges
    
    context += f"User's current question: {user_question}\n\n"
    context += f"Information to use for answering:\n{tool_result}\n\n"
    
    # Add sources information for proper citation
    if sources_data:
        context += "Format these sources in your response:\n"
        for source in sources_data:
            context += f"{source['index']}. [{source['title']}]({source['url']})\n"
    
    # Ask to answer the specific question with strong emphasis on stock chart detection
    summary_request = HumanMessage(content=f"""INSTRUCTION: If the search results contain stock prices or the user asks about a company/stock, 
you MUST start your answer with [STOCK_CHART:TICKER] where TICKER is extracted from the search results.

Question: {user_question}

Search results show stock tickers? If yes, your answer MUST start with [STOCK_CHART:TICKER]

Context:
{context}""")
    
    logger.info("📝 [SUMMARIZE GENERATE] Generating focused answer...")
    
    # Get answer with timeout handling
    llm_start = time.time()
    try:
        summary = llm.invoke([summarize_prompt, summary_request])
        llm_time = time.time() - llm_start
        logger.info(f"⏱️  [SUMMARIZE LLM] LLM summarization took: {llm_time:.2f}s")
    except Exception as e:
        logger.error(f"❌ [SUMMARIZE ERROR] LLM invocation failed: {e}")
        # Fallback to a simple response
        fallback_content = json.dumps({
            "answer": "I'm having trouble generating a response. Please try again or check your LLM configuration.",
            "sources": []
        })
        summary = AIMessage(content=fallback_content)
        llm_time = time.time() - llm_start
        logger.info(f"⏱️  [SUMMARIZE FALLBACK] Used fallback after: {llm_time:.2f}s")
    
    total_time = time.time() - node_start
    logger.info(f"✅ [SUMMARIZE NODE COMPLETE] Total time: {total_time:.2f}s")
    
    return {"messages": [summary]}


# Router to decide next step after agent
def should_continue(state: AgentState) -> Literal["tools", "end"]:
    """
    Determine whether to continue to tools or end
    """
    messages = state["messages"]
    last_message = messages[-1]
    
    # Check if the last message has tool calls
    if last_message.tool_calls:
        logger.info("➡️ Routing to tools node")
        return "tools"
    else:
        logger.info("➡️ Routing to end")
        return "end"


# Router after tools - go to end to allow streaming summarization
def after_tools(state: AgentState) -> Literal["end", "agent"]:
    """
    After tools, route to end so we can do streaming summarization outside the graph
    """
    messages = state["messages"]

    # Check if we have search results in the recent messages
    for msg in reversed(messages[-3:]):  # Check last 3 messages
        if hasattr(msg, 'content') and 'Search results for' in str(msg.content):
            logger.info("➡️ Routing to END (will do streaming summarization)")
            return "end"

    # Otherwise go back to agent
    logger.info("➡️ Routing back to agent")
    return "agent"


# Streaming summarization generator (for real streaming)
def stream_summarize(messages, user_question, stop_event=None):
    """
    Generator that streams summarization tokens.
    Yields: (token_type, content) tuples
    - ("token", "text") for streaming tokens
    - ("sources", [...]) for sources at the end
    - ("done", full_content) when complete
    """
    logger.info("📝 [STREAM SUMMARIZE START]")

    # Extract search results from messages
    tool_result = None
    sources_data = []
    for msg in reversed(messages):
        if hasattr(msg, 'content') and msg.content:
            try:
                data = json.loads(msg.content)
                if 'text' in data and 'Search results for' in data['text']:
                    tool_result = data['text']
                    sources_data = data.get('sources', [])
                    break
            except (json.JSONDecodeError, ValueError, TypeError):
                if 'Search results for' in str(msg.content):
                    tool_result = msg.content
                    break

    if not tool_result:
        logger.info("⚠️ [STREAM SUMMARIZE] No tool results to summarize")
        yield ("done", "")
        return

    # Get LLM config
    config = get_llm_provider_config()
    provider = config['provider']
    model_name = config['model_name']

    # Create LLM based on provider
    if provider == "vllm":
        llm = ChatOpenAI(
            base_url=config['vllm_url'],
            model=model_name,
            api_key="not-needed",
            temperature=0.3,
            max_tokens=28000,
            streaming=True
        )
    elif provider == "openai":
        llm = ChatOpenAI(
            api_key=config['api_key'] or OPENAI_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "anthropic":
        llm = ChatAnthropic(
            api_key=config['api_key'] or ANTHROPIC_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "google":
        llm = ChatGoogleGenerativeAI(
            google_api_key=config['api_key'] or GOOGLE_API_KEY,
            model=model_name,
            temperature=0.1,
            top_p=0.8,
            streaming=True
        )
    elif provider == "deepseek":
        llm = ChatOpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=config['api_key'] or DEEPSEEK_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    elif provider == "qwen":
        llm = ChatOpenAI(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=config['api_key'] or DASHSCOPE_API_KEY,
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            streaming=True
        )
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")

    # Streaming prompt - outputs markdown directly (no JSON wrapper)
    system_prompt = SystemMessage(content="""You are a helpful assistant providing comprehensive, detailed answers like Perplexity.

OUTPUT FORMAT: Write your answer directly in Markdown format. DO NOT wrap in JSON.

STOCK QUERIES: If the user asks about a stock/company and you see stock data, start with:
[STOCK_CHART:TICKER]

Then write your markdown answer.

CITATION RULES:
- Use <sup>1</sup>, <sup>2</sup>, etc. to cite sources
- Number citations sequentially starting from 1
- Place citations immediately after the relevant information
- Prefer "Evidence Extracted from Source Pages" over search snippets.
- Only cite a source when the provided evidence or snippet directly supports the sentence.
- If evidence is missing or conflicting, say so instead of overstating certainty.

ANSWER STYLE:
- Use ## for section headers
- Use bullet points and numbered lists
- Be comprehensive but focused
- Include specific details: dates, names, numbers

FORBIDDEN: Do not say "According to search results" or similar phrases. Just state the facts.""")

    # Build context
    context = f"User's question: {user_question}\n\nInformation to answer with:\n{tool_result}"

    if sources_data:
        context += "\n\nAvailable sources (cite by number):\n"
        for source in sources_data:
            context += f"{source['index']}. [{source['title']}]({source['url']})\n"

    user_msg = HumanMessage(content=context)

    logger.info("📝 [STREAM SUMMARIZE] Starting LLM stream...")

    # Stream the response
    full_content = ""
    try:
        for chunk in llm.stream([system_prompt, user_msg]):
            if stop_event and stop_event.is_set():
                logger.info("Request cancelled during streaming")
                return

            if hasattr(chunk, 'content') and chunk.content:
                full_content += chunk.content
                yield ("token", chunk.content)

        logger.info(f"📝 [STREAM SUMMARIZE] Complete, {len(full_content)} chars")

        # Send sources
        yield ("sources", verify_source_citations(full_content, sources_data))

        # Send completion
        yield ("done", full_content)

    except Exception as e:
        logger.error(f"❌ [STREAM SUMMARIZE ERROR] {e}")
        yield ("error", str(e))


# Create the graph
def create_perplexity_graph():
    """
    Create the LangGraph workflow with proper tool calling and summarization
    Workflow: user -> agent -> tools -> summarize -> end
    """
    # Initialize workflow
    workflow = StateGraph(AgentState)
    
    # Create ToolNode with our tools
    tool_node = ToolNode([google_search])
    
    # Add nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)  # Using ToolNode from LangGraph
    workflow.add_node("summarize", summarize_node)  # New summarize node
    
    # Set entry point
    workflow.set_entry_point("agent")
    
    # Add conditional routing from agent
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "end": END
        }
    )
    
    # After tools, route to end (for streaming summarization) or back to agent
    workflow.add_conditional_edges(
        "tools",
        after_tools,
        {
            "end": END,
            "agent": "agent"
        }
    )
    
    # Compile the graph
    app = workflow.compile()
    
    logger.info("📊 Graph compiled with workflow: agent -> tools -> summarize -> end")
    
    return app


# Main assistant class
class PerplexityAssistant:
    """
    Main assistant using LangGraph with proper tool calling
    """
    
    def __init__(self):
        self.graph = create_perplexity_graph()
        self.message_history = []  # Maintain full message history
        self.conversation_history = []  # Keep simplified history for reference
        logger.info("✅ Perplexity Assistant initialized with LangGraph")
    
    def chat(self, user_input: str) -> str:
        """
        Process user input through the graph with conversation history
        """
        # Add user message to history
        user_msg = HumanMessage(content=user_input)
        self.message_history.append(user_msg)
        
        # Create initial state with conversation history based on config
        if get_current_search_config().get('memory_enabled', True):
            # Keep last 5 questions (10 messages: 5 user + 5 assistant)
            messages_to_include = self.message_history[-10:]
        else:
            # No history, just current message
            messages_to_include = [user_msg]
        
        initial_state = {
            "messages": messages_to_include,
            "user_question": user_input  # Pass the current question
        }
        
        logger.info(f"\n{'='*60}")
        logger.info(f"👤 USER: {user_input}")
        logger.info(f"{'='*60}")
        
        # Run the graph
        result = self.graph.invoke(initial_state)
        
        # Get the final message
        final_message = result["messages"][-1]
        
        # Add assistant response to history
        self.message_history.append(final_message)
        
        # Track if tools were used
        used_tools = any(msg.tool_calls for msg in result["messages"] if hasattr(msg, 'tool_calls'))
        
        # Store in simplified history
        self.conversation_history.append({
            "user": user_input,
            "assistant": final_message.content,
            "used_tools": used_tools
        })
        
        # Format response
        response = final_message.content
        
        return response

    @staticmethod
    def _messages_from_request(request_messages, fallback_user_input: str) -> List[BaseMessage]:
        """Convert frontend chat history into LangChain messages without storing it globally."""
        converted: List[BaseMessage] = []

        if isinstance(request_messages, list):
            for item in request_messages:
                if not isinstance(item, dict):
                    continue

                role = item.get('role')
                content = item.get('content')
                if not isinstance(content, str) or not content.strip():
                    continue

                if role == 'user':
                    converted.append(HumanMessage(content=content))
                elif role == 'assistant':
                    converted.append(AIMessage(content=content))

        if not converted:
            return [HumanMessage(content=fallback_user_input)]

        return converted

    def stream_chat(
        self,
        user_input: str,
        stop_event=None,
        llm_config: Optional[Dict[str, Any]] = None,
        search_config: Optional[Dict[str, Any]] = None,
        request_messages=None
    ):
        """Stream chat with request-local configuration that is reset when streaming ends."""
        llm_token = CURRENT_LLM_CONFIG.set(sanitize_llm_config(llm_config))
        search_token = CURRENT_SEARCH_CONFIG.set(sanitize_search_config(search_config))

        try:
            yield from self._stream_chat_impl(user_input, stop_event, request_messages)
        finally:
            CURRENT_LLM_CONFIG.reset(llm_token)
            CURRENT_SEARCH_CONFIG.reset(search_token)

    def _stream_chat_impl(self, user_input: str, stop_event=None, request_messages=None):
        """
        Stream the chat response with cancellation support - with real streaming
        """
        overall_start = time.time()

        use_request_history = request_messages is not None
        user_msg = HumanMessage(content=user_input)

        if use_request_history:
            history_messages = self._messages_from_request(request_messages, user_input)
        else:
            # CLI mode keeps local history; web requests pass history explicitly.
            self.message_history.append(user_msg)
            history_messages = self.message_history

        # Create initial state with conversation history based on config
        if get_current_search_config().get('memory_enabled', True):
            # Keep last 5 questions (10 messages: 5 user + 5 assistant)
            messages_to_include = history_messages[-10:]
        else:
            # No history, just current message
            messages_to_include = [history_messages[-1] if history_messages else user_msg]
        
        initial_state = {
            "messages": messages_to_include,
            "user_question": user_input  # Pass the current question
        }
        
        logger.info(f"\n{'='*60}")
        logger.info(f"👤 USER: {user_input}")
        logger.info(f"⏱️  [STREAM START] Starting request processing")
        logger.info(f"{'='*60}")

        yield "STATUS:PLANNING"
        yield step_event(
            "planning",
            "Planning research",
            "active",
            "Deciding whether to search and which angles to cover."
        )

        # Use streaming directly from the graph
        try:
            full_content = ""
            used_tools = False
            all_messages = list(messages_to_include)  # Track all messages
            sources_data = []
            direct_content = ""
            direct_sources = []
            planning_finalized = False

            # Stream through the graph
            graph_start = time.time()
            logger.info(f"⏱️  [GRAPH START] Beginning graph execution")

            for event in self.graph.stream(initial_state):
                if stop_event and stop_event.is_set():
                    logger.info("Request cancelled during streaming")
                    return

                for node_name, node_data in event.items():
                    logger.info(f"🔄 [NODE] {node_name}")

                    if node_name == "tools":
                        used_tools = True
                        yield step_event("searching", "Searching the web", "done")
                        yield step_event("reading", "Reading source pages", "done")
                        yield step_event("summarizing", "Composing grounded answer", "active")
                        yield "STATUS:SUMMARIZING"
                        # Collect messages from tools
                        if "messages" in node_data:
                            all_messages.extend(node_data["messages"])

                    elif node_name == "agent":
                        if "messages" in node_data:
                            agent_messages = node_data["messages"]
                            all_messages.extend(agent_messages)
                            tool_plan = describe_tool_calls(agent_messages)
                            if tool_plan:
                                planning_finalized = True
                                yield step_event("planning", "Planning research", "done", tool_plan)
                                yield step_event("searching", "Searching the web", "active", tool_plan)
                                yield step_event("reading", "Reading source pages", "active", "Fetching top results and extracting evidence.")
                                yield "STATUS:READING"
                            else:
                                for message in agent_messages:
                                    if isinstance(message, AIMessage):
                                        parsed_direct = parse_direct_answer(message.content)
                                        direct_content = parsed_direct["answer"]
                                        direct_sources = parsed_direct["sources"]
                                if not planning_finalized:
                                    planning_finalized = True
                                    yield step_event("planning", "Planning research", "done", "No web search needed.")

            graph_time = time.time() - graph_start
            logger.info(f"⏱️  [GRAPH COMPLETE] Graph took: {graph_time:.2f}s")

            # If tools were used, do streaming summarization
            if used_tools:
                logger.info("📝 [STREAMING SUMMARIZE] Starting...")

                for result in stream_summarize(all_messages, user_input, stop_event):
                    if stop_event and stop_event.is_set():
                        return

                    result_type, content = result

                    if result_type == "token":
                        # Stream each token to frontend
                        yield f"STREAM:{content}"
                        full_content += content

                    elif result_type == "sources":
                        sources_data = content
                        # Send sources as JSON
                        yield f"SOURCES:{json.dumps(content)}"

                    elif result_type == "done":
                        logger.info(f"📝 [STREAMING SUMMARIZE] Done, {len(content)} chars")
                        yield step_event("summarizing", "Composing grounded answer", "done")

                    elif result_type == "error":
                        logger.error(f"❌ [STREAMING SUMMARIZE] Error: {content}")
                        yield step_event("summarizing", "Composing grounded answer", "error", str(content))
                        yield f"Error: {content}"

            elif direct_content:
                yield "STATUS:SUMMARIZING"
                yield step_event("summarizing", "Composing response", "active")
                yield f"STREAM:{direct_content}"
                full_content = direct_content
                if direct_sources:
                    sources_data = direct_sources
                    yield f"SOURCES:{json.dumps(direct_sources)}"
                yield step_event("summarizing", "Composing response", "done")

            # Store in history
            if full_content and not use_request_history:
                final_msg = AIMessage(content=full_content)
                self.message_history.append(final_msg)
                self.conversation_history.append({
                    "user": user_input,
                    "assistant": full_content,
                    "used_tools": used_tools
                })

            total_time = time.time() - overall_start
            logger.info(f"⏱️  [REQUEST COMPLETE] Total: {total_time:.2f}s")
            logger.info(f"{'='*60}\n")
                
        except Exception as e:
            total_time = time.time() - overall_start
            logger.error(f"❌ [ERROR] Request failed after {total_time:.2f}s: {e}")
            yield f"Error: {str(e)}"
            return
    


# Interactive CLI
def main():
    """
    Interactive chat interface
    """
    print("""
╔═══════════════════════════════════════════════════════╗
║     LangChain + LangGraph + vLLM Assistant           ║
╚═══════════════════════════════════════════════════════╝

🔄 Workflow:
┌────────┐     ┌─────────────┐     ┌────────────┐     ┌──────────┐
│  User  │ --> │ Agent (LLM) │ --> │  ToolNode  │ --> │ Summarize│
└────────┘     └─────────────┘     └────────────┘     └──────────┘
                    ↓                (google_search)         ↓
               [Decides to use                           [Clean summary
                tools or not]                             without bias]

✨ LLM autonomously decides when to search
📚 Using proper LangChain tool calling pattern

Type 'exit' to quit
""")
    # Initialize assistant
    assistant = PerplexityAssistant()
    
    while True:
        try:
            # Get user input
            user_input = input("\n👤 You: ")
            
            if user_input.lower() == 'exit':
                print("👋 Goodbye!")
                break
            
            # Stream and display response
            print("\n🤖 Assistant: ", end="", flush=True)
            
            # Stream the response
            full_response = ""
            for chunk in assistant.stream_chat(user_input):
                print(chunk, end="", flush=True)
                full_response += chunk
            
            print()  # New line after response
            
            # Store in history
            assistant.conversation_history.append({
                "user": user_input,
                "assistant": full_response,
            })
            
        except KeyboardInterrupt:
            print("\n\nUse 'exit' to quit")
        except Exception as e:
            print(f"\n❌ Error: {e}")
            logger.error(f"Error in chat: {e}", exc_info=True)


if __name__ == "__main__":
    main()
