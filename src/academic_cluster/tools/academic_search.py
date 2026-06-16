"""
学术搜索工具

实现对多个学术数据源的搜索（对齐 Rust 版 5 个源）：
- Semantic Scholar (200 results)
- PubMed (200 results)
- arXiv (200 results)
- OpenAlex (100 results)
- Crossref (200 results)

各 API 速率限制（已在 _RATE_LIMITS 中配置）：
- arXiv:            1 请求 / 3 秒（无认证，最严格）
- Semantic Scholar:  1 请求 / 秒（无 key），100 请求 / 秒（有 key）
- PubMed:           3 请求 / 秒（无 key），10 请求 / 秒（有 key）
- OpenAlex:         ~10 请求 / 秒（无 mailto），~100 请求 / 秒（polite pool）
- Crossref:         ~5 请求 / 秒（polite pool）
"""

import asyncio
import time
from typing import Optional

import httpx
import structlog

from ..services.source_config import (
    get_effective_source_value,
    get_semantic_scholar_api_keys,
)
from .doi import normalize_doi, is_valid_doi, extract_doi

logger = structlog.get_logger()


# =============================================================================
# 速率限制器
# =============================================================================

# 各源最小请求间隔（秒），根据配置动态计算
_RATE_LIMITS: dict[str, float] | None = None


async def _get_rate_limits() -> dict[str, float]:
    """根据实际配置动态生成各源的最小请求间隔"""
    global _RATE_LIMITS
    if _RATE_LIMITS is not None:
        return _RATE_LIMITS

    pubmed_api_key = await get_effective_source_value("pubmed_api_key")
    _RATE_LIMITS = {
        "arxiv": 3.0,                                           # 1 req / 3s（无认证）
        "semantic_scholar": 1.0,                                 # 1 req / s / key
        "pubmed": 0.1 if pubmed_api_key else 0.34,               # 有 key: 10 rps, 无 key: 3 rps
        "openalex": 0.1,                                         # polite pool
        "crossref": 0.2,                                         # 5 req / s（polite pool）
    }
    return _RATE_LIMITS

# 上次请求时间戳（按源）
_last_request_time: dict[str, float] = {}
_rate_locks: dict[str, asyncio.Lock] = {}


def _get_rate_lock(source: str) -> asyncio.Lock:
    """获取指定源的速率锁（惰性创建）"""
    if source not in _rate_locks:
        _rate_locks[source] = asyncio.Lock()
    return _rate_locks[source]


async def _enforce_rate_limit(source: str) -> None:
    """确保两次请求之间满足最小间隔（单 key 场景）"""
    lock = _get_rate_lock(source)
    async with lock:
        now = time.monotonic()
        min_interval = (await _get_rate_limits()).get(source, 1.0)
        last = _last_request_time.get(source, 0.0)
        wait = min_interval - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time[source] = time.monotonic()


# =============================================================================
# Semantic Scholar 多 Key 池
# =============================================================================

class _KeySlot:
    """单个 API key 的限流状态"""
    __slots__ = ("key", "lock", "last_used")

    def __init__(self, key: str):
        self.key = key
        self.lock = asyncio.Lock()
        self.last_used: float = 0.0


class SemanticScholarKeyPool:
    """
    Semantic Scholar 多 key 池。

    每个 key 独立限流（1 rps），轮询选择最久未使用的 key，
    N 个 key = N rps 总吞吐。
    """

    def __init__(self, keys: list[str], min_interval: float = 1.0):
        self._slots = [_KeySlot(k) for k in keys]
        self._min_interval = min_interval
        self._rr_index = 0

    @property
    def key_count(self) -> int:
        return len(self._slots)

    async def acquire(self) -> str:
        """
        获取一个可用的 key，等待其速率限制满足后返回。
        使用最久未使用（LRU）策略选择 key。
        """
        if not self._slots:
            return ""

        # 按 last_used 排序，选最久没用的
        self._slots.sort(key=lambda s: s.last_used)
        slot = self._slots[0]

        async with slot.lock:
            now = time.monotonic()
            wait = self._min_interval - (now - slot.last_used)
            if wait > 0:
                await asyncio.sleep(wait)
            slot.last_used = time.monotonic()
            return slot.key


# 惰性初始化的 key pool 单例
_s2_key_pool: SemanticScholarKeyPool | None = None


def reset_source_config_runtime_cache() -> None:
    """Reset source-derived runtime caches after admin source updates."""
    global _RATE_LIMITS, _s2_key_pool
    _RATE_LIMITS = None
    _s2_key_pool = None


async def _get_s2_key_pool() -> SemanticScholarKeyPool | None:
    """获取或创建 Semantic Scholar key pool"""
    global _s2_key_pool
    if _s2_key_pool is not None:
        return _s2_key_pool

    keys = await get_semantic_scholar_api_keys()
    if not keys:
        return None

    _s2_key_pool = SemanticScholarKeyPool(keys, min_interval=1.0)
    logger.info(
        "Semantic Scholar key pool initialized",
        key_count=len(keys),
        capacity_rps=len(keys),
    )
    return _s2_key_pool


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    source: str,
    max_retries: int = 3,
    _skip_rate_limit: bool = False,
    **kwargs,
) -> httpx.Response:
    """
    带速率限制和 429 退避的 HTTP 请求。

    每次请求前强制执行 per-source 速率限制，
    遇到 429 时按指数退避重试。

    _skip_rate_limit: 为 True 时跳过全局限流（调用方已自行限流，如 key pool）
    """
    for attempt in range(max_retries):
        if not _skip_rate_limit:
            await _enforce_rate_limit(source)
        response = await client.request(method, url, **kwargs)

        if response.status_code == 429:
            # 解析 Retry-After 头，否则指数退避
            # 限制最大等待时间为 60 秒，避免被恶意/异常的 Retry-After 值阻塞数小时
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait = min(float(retry_after), 60)
            else:
                wait = min(2 ** (attempt + 1), 30)
            logger.warning(
                "Rate limited (429), retrying",
                source=source,
                attempt=attempt + 1,
                max_retries=max_retries,
                wait_seconds=wait,
                url=url,
            )
            await asyncio.sleep(wait)
            continue

        return response

    # 所有重试用尽，raise 让调用方捕获异常
    logger.error(
        "All retries exhausted for HTTP request",
        source=source,
        url=url,
        status_code=response.status_code,
        max_retries=max_retries,
    )
    response.raise_for_status()
    return response


# =============================================================================
# Semantic Scholar
# =============================================================================

async def search_semantic_scholar(
    query: str,
    limit: int = 100,
    year_range: Optional[tuple[int, int]] = None,
    fields_of_study: Optional[list[str]] = None,
) -> list[dict]:
    """
    搜索 Semantic Scholar

    API 文档: https://api.semanticscholar.org/api-docs/
    支持多 key 池化：每个 key 独立 1 rps 限流，N key = N rps。
    """
    pool = await _get_s2_key_pool()

    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query,
        "limit": min(limit, 100),
        "fields": "paperId,title,abstract,authors,year,citationCount,referenceCount,fieldsOfStudy,externalIds,venue,publicationDate",
    }

    if year_range:
        params["year"] = f"{year_range[0]}-{year_range[1]}"

    if fields_of_study:
        params["fieldsOfStudy"] = ",".join(fields_of_study)

    async with httpx.AsyncClient() as client:
        try:
            if pool:
                # 多 key 模式：key pool 自身负责 per-key 限流
                api_key = await pool.acquire()
                headers = {"x-api-key": api_key}
                response = await _request_with_retry(
                    client, "GET", url, "semantic_scholar",
                    params=params, headers=headers, timeout=30,
                    _skip_rate_limit=True,  # key pool 已限流，跳过全局限流
                )
            else:
                # 无 key 模式：使用全局单 key 限流
                headers = {}
                semantic_scholar_api_key = await get_effective_source_value("semantic_scholar_api_key")
                if semantic_scholar_api_key:
                    headers["x-api-key"] = semantic_scholar_api_key
                response = await _request_with_retry(
                    client, "GET", url, "semantic_scholar",
                    params=params, headers=headers, timeout=30,
                )

            response.raise_for_status()
            data = response.json()

            papers = []
            for item in data.get("data", []):
                # 提取并标准化 DOI
                raw_doi = item.get("externalIds", {}).get("DOI")
                doi = normalize_doi(raw_doi) if raw_doi else None

                # 优先使用 DOI 作为 external_id
                external_id = doi if doi and is_valid_doi(doi) else item.get("paperId")

                papers.append({
                    "external_id": external_id,
                    "source": "semantic_scholar",
                    "title": item.get("title"),
                    "abstract": item.get("abstract"),
                    "authors": [
                        {"name": a.get("name"), "id": a.get("authorId")}
                        for a in item.get("authors", [])
                    ],
                    "publication_date": item.get("publicationDate"),
                    "year": item.get("year"),
                    "journal": item.get("venue"),
                    "citation_count": item.get("citationCount", 0),
                    "reference_count": item.get("referenceCount", 0),
                    "fields_of_study": item.get("fieldsOfStudy", []),
                    "doi": doi,
                    "url": f"https://www.semanticscholar.org/paper/{item.get('paperId')}",
                })

            logger.info(
                "Semantic Scholar search completed",
                query=query,
                results=len(papers),
            )

            return papers

        except httpx.HTTPError as e:
            logger.error(
                "Semantic Scholar search failed",
                query=query,
                limit=limit,
                year_range=year_range,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []
        except Exception as e:
            logger.error(
                "Semantic Scholar search failed with unexpected error",
                query=query,
                limit=limit,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []


# =============================================================================
# PubMed
# =============================================================================

async def search_pubmed(
    query: str,
    limit: int = 100,
    min_date: Optional[str] = None,
    max_date: Optional[str] = None,
) -> list[dict]:
    """
    搜索 PubMed

    使用 NCBI E-utilities API
    """
    email = await get_effective_source_value("pubmed_email") or "user@example.com"
    tool = "academic-cluster"
    api_key = await get_effective_source_value("pubmed_api_key")

    # Step 1: 搜索获取 ID 列表
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    search_params = {
        "db": "pubmed",
        "term": query,
        "retmax": min(limit, 200),
        "retmode": "json",
        "email": email,
        "tool": tool,
    }

    if api_key:
        search_params["api_key"] = api_key

    if min_date:
        search_params["mindate"] = min_date
    if max_date:
        search_params["maxdate"] = max_date

    async with httpx.AsyncClient() as client:
        try:
            search_response = await _request_with_retry(
                client, "GET", search_url, "pubmed",
                params=search_params, timeout=30,
            )
            search_response.raise_for_status()
            search_data = search_response.json()

            id_list = search_data.get("esearchresult", {}).get("idlist", [])

            if not id_list:
                return []

            # Step 2: 获取详细信息
            fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
            fetch_params = {
                "db": "pubmed",
                "id": ",".join(id_list),
                "retmode": "json",
                "email": email,
                "tool": tool,
            }

            if api_key:
                fetch_params["api_key"] = api_key

            fetch_response = await _request_with_retry(
                client, "GET", fetch_url, "pubmed",
                params=fetch_params, timeout=30,
            )
            fetch_response.raise_for_status()
            fetch_data = fetch_response.json()

            papers = []
            for pmid in id_list:
                article = fetch_data.get("result", {}).get(pmid, {})
                if not article:
                    continue

                # 提取作者
                authors = [
                    {"name": a.get("name", "")}
                    for a in article.get("authors", [])
                ]

                # 提取并标准化 DOI
                raw_doi = article.get("elocationid", "").replace("doi: ", "")
                doi = normalize_doi(raw_doi) if raw_doi else None

                # 优先使用 DOI 作为 external_id
                external_id = doi if doi and is_valid_doi(doi) else f"PMID:{pmid}"

                papers.append({
                    "external_id": external_id,
                    "source": "pubmed",
                    "title": article.get("title", ""),
                    "abstract": "",  # esummary 不返回摘要，需要额外调用 efetch
                    "authors": authors,
                    "publication_date": article.get("pubdate"),
                    "year": article.get("pubdate", "")[:4],
                    "journal": article.get("fulljournalname", article.get("source", "")),
                    "doi": doi,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "citation_count": 0,  # PubMed 不提供引用数
                })

            logger.info(
                "PubMed search completed",
                query=query,
                results=len(papers),
            )

            return papers

        except httpx.HTTPError as e:
            logger.error(
                "PubMed search failed",
                query=query,
                limit=limit,
                min_date=min_date,
                max_date=max_date,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []
        except Exception as e:
            logger.error(
                "PubMed search failed with unexpected error",
                query=query,
                limit=limit,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []


# =============================================================================
# arXiv
# =============================================================================

async def search_arxiv(
    query: str,
    limit: int = 100,
    categories: Optional[list[str]] = None,
    sort_by: str = "relevance",
) -> list[dict]:
    """
    搜索 arXiv

    使用 arXiv API
    """
    url = "https://export.arxiv.org/api/query"

    search_query = query
    if categories:
        cat_filter = " OR ".join([f"cat:{cat}" for cat in categories])
        search_query = f"({query}) AND ({cat_filter})"

    params = {
        "search_query": f"all:{search_query}",
        "start": 0,
        "max_results": min(limit, 200),
        "sortBy": sort_by,
        "sortOrder": "descending",
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await _request_with_retry(
                client, "GET", url, "arxiv",
                params=params, timeout=30,
            )
            response.raise_for_status()

            # arXiv 返回 XML，需要解析
            import xml.etree.ElementTree as ET

            root = ET.fromstring(response.text)
            ns = {
                "atom": "http://www.w3.org/2005/Atom",
                "arxiv": "http://arxiv.org/schemas/atom",
            }

            papers = []
            for entry in root.findall("atom:entry", ns):
                title = entry.find("atom:title", ns)
                summary = entry.find("atom:summary", ns)
                published = entry.find("atom:published", ns)

                authors = []
                for author in entry.findall("atom:author", ns):
                    name = author.find("atom:name", ns)
                    if name is not None:
                        authors.append({"name": name.text})

                # 提取 arXiv ID
                entry_id = entry.find("atom:id", ns)
                arxiv_id = entry_id.text.split("/abs/")[-1] if entry_id is not None else ""

                # 提取链接
                links = entry.findall("atom:link", ns)
                pdf_url = None
                for link in links:
                    if link.get("title") == "pdf":
                        pdf_url = link.get("href")

                # 尝试提取 DOI（arXiv 条目可能包含已发表论文的 DOI）
                doi = None
                arxiv_doi = entry.find("arxiv:doi", ns)
                if arxiv_doi is not None and arxiv_doi.text:
                    doi = normalize_doi(arxiv_doi.text)

                # 优先使用 DOI 作为 external_id
                external_id = doi if doi and is_valid_doi(doi) else f"arXiv:{arxiv_id}"

                papers.append({
                    "external_id": external_id,
                    "source": "arxiv",
                    "title": title.text.strip().replace("\n", " ") if title is not None else "",
                    "abstract": summary.text.strip().replace("\n", " ") if summary is not None else "",
                    "authors": authors,
                    "publication_date": published.text if published is not None else "",
                    "year": published.text[:4] if published is not None else "",
                    "url": entry_id.text if entry_id is not None else "",
                    "pdf_url": pdf_url,
                    "doi": doi,
                    "citation_count": 0,  # arXiv API 不提供引用数
                })

            logger.info(
                "arXiv search completed",
                query=query,
                results=len(papers),
            )

            return papers

        except Exception as e:
            logger.error(
                "arXiv search failed",
                query=query,
                limit=limit,
                categories=categories,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []


# =============================================================================
# OpenAlex
# =============================================================================

def _get_openalex_journal(work: dict) -> Optional[str]:
    """从 OpenAlex work 中安全提取期刊名称"""
    primary_location = work.get("primary_location")
    if not primary_location:
        return None
    source = primary_location.get("source")
    if not source:
        return None
    return source.get("display_name")


async def search_openalex(
    query: str,
    limit: int = 100,
    from_year: Optional[int] = None,
    to_year: Optional[int] = None,
) -> list[dict]:
    """
    搜索 OpenAlex

    API 文档: https://docs.openalex.org/
    """
    url = "https://api.openalex.org/works"

    params = {
        "search": query,
        "per_page": min(limit, 200),
        "mailto": await get_effective_source_value("pubmed_email") or "user@example.com",
    }

    if from_year:
        params["filter"] = f"publication_year:{from_year}-{to_year or 2024}"

    async with httpx.AsyncClient() as client:
        try:
            response = await _request_with_retry(
                client, "GET", url, "openalex",
                params=params, timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            papers = []
            for work in data.get("results", []):
                # 提取作者
                authors = [
                    {"name": a.get("author", {}).get("display_name", "")}
                    for a in work.get("authorships", [])
                ]

                # 提取并标准化 DOI
                raw_doi = work.get("doi", "")
                doi = normalize_doi(raw_doi) if raw_doi else None

                # 优先使用 DOI 作为 external_id
                openalex_id = work.get("id", "").split("/")[-1]
                external_id = doi if doi and is_valid_doi(doi) else openalex_id

                papers.append({
                    "external_id": external_id,
                    "source": "openalex",
                    "title": work.get("title", ""),
                    "abstract": "",  # OpenAlex 需要单独获取摘要
                    "authors": authors,
                    "publication_date": work.get("publication_date"),
                    "year": work.get("publication_year"),
                    "journal": _get_openalex_journal(work),
                    "doi": doi,
                    "url": work.get("id"),
                    "citation_count": work.get("cited_by_count", 0),
                    "fields_of_study": [
                        t.get("display_name")
                        for t in work.get("topics", [])
                    ],
                })

            logger.info(
                "OpenAlex search completed",
                query=query,
                results=len(papers),
            )

            return papers

        except httpx.HTTPError as e:
            logger.error(
                "OpenAlex search failed",
                query=query,
                limit=limit,
                from_year=from_year,
                to_year=to_year,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []
        except Exception as e:
            logger.error(
                "OpenAlex search failed with unexpected error",
                query=query,
                limit=limit,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []


# =============================================================================
# Crossref
# =============================================================================

async def search_crossref(
    query: str,
    limit: int = 200,
    from_year: Optional[int] = None,
    to_year: Optional[int] = None,
) -> list[dict]:
    """
    搜索 Crossref

    API 文档: https://api.crossref.org/swagger-ui/index.html
    对齐 Rust 版 academic-cluster-rs 的 crossref 实现。
    """
    url = "https://api.crossref.org/works"

    params = {
        "query": query,
        "rows": min(limit, 200),
        "select": "DOI,title,author,published-print,container-title,is-referenced-by-count,abstract,ISSN,subject",
    }

    if from_year:
        params["filter"] = f"from-pub-date:{from_year}"
        if to_year:
            params["filter"] += f",until-pub-date:{to_year}"

    pubmed_email = await get_effective_source_value("pubmed_email")
    headers = {}
    if pubmed_email:
        headers["User-Agent"] = f"academic-cluster/1.0 (mailto:{pubmed_email})"

    async with httpx.AsyncClient() as client:
        try:
            response = await _request_with_retry(
                client, "GET", url, "crossref",
                params=params, headers=headers, timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            papers = []
            for item in data.get("message", {}).get("items", []):
                # 提取标题
                title_list = item.get("title", [])
                title = title_list[0] if title_list else ""

                # 提取作者
                authors = []
                for author in item.get("author", []):
                    name_parts = []
                    if author.get("given"):
                        name_parts.append(author["given"])
                    if author.get("family"):
                        name_parts.append(author["family"])
                    if name_parts:
                        authors.append({"name": " ".join(name_parts)})

                # 提取年份
                pub_date = item.get("published-print", item.get("published-online", {}))
                year = None
                date_parts = pub_date.get("date-parts", [[]])
                if date_parts and date_parts[0]:
                    year = date_parts[0][0]

                # 提取期刊
                container = item.get("container-title", [])
                journal = container[0] if container else ""

                # 提取 DOI
                raw_doi = item.get("DOI", "")
                doi = normalize_doi(raw_doi) if raw_doi else None

                # 提取摘要（Crossref 有时包含摘要）
                abstract = item.get("abstract", "")
                # Crossref 摘要可能包含 JATS XML 标签，简单清理
                if abstract:
                    import re
                    abstract = re.sub(r'<[^>]+>', '', abstract).strip()

                external_id = doi if doi and is_valid_doi(doi) else raw_doi or f"crossref:{raw_doi}"

                papers.append({
                    "external_id": external_id,
                    "source": "crossref",
                    "title": title,
                    "abstract": abstract,
                    "authors": authors,
                    "publication_date": f"{year}" if year else None,
                    "year": year,
                    "journal": journal,
                    "doi": doi,
                    "url": f"https://doi.org/{doi}" if doi else "",
                    "citation_count": item.get("is-referenced-by-count", 0),
                    "fields_of_study": item.get("subject", []),
                })

            logger.info(
                "Crossref search completed",
                query=query,
                results=len(papers),
            )

            return papers

        except httpx.HTTPError as e:
            logger.error(
                "Crossref search failed",
                query=query,
                limit=limit,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []
        except Exception as e:
            logger.error(
                "Crossref search failed with unexpected error",
                query=query,
                limit=limit,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []


# =============================================================================
# 统一搜索接口
# =============================================================================

async def search_all_sources(
    query: str,
    limit_per_source: int = 200,
    sources: Optional[list[str]] = None,
    timeout: float = 120.0,
    per_source_limits: Optional[dict[str, int]] = None,
) -> list[dict]:
    """
    并行搜索所有数据源

    对齐 Rust 版 academic-cluster-rs：默认 5 个源，每源 200 结果。

    Args:
        query: 搜索查询
        limit_per_source: 每个源的默认最大结果数
        sources: 要搜索的源列表，默认全部 5 个源
        timeout: 总体超时时间（秒）
        per_source_limits: 各源独立限制，如 {"arxiv": 50, "semantic_scholar": 300}，覆盖 limit_per_source

    Returns:
        合并的论文列表
    """
    if sources is None:
        sources = ["semantic_scholar", "openalex", "crossref", "arxiv", "pubmed"]

    search_functions = {
        "semantic_scholar": search_semantic_scholar,
        "pubmed": search_pubmed,
        "arxiv": search_arxiv,
        "openalex": search_openalex,
        "crossref": search_crossref,
    }

    tasks = []
    active_sources = []
    for source in sources:
        if source in search_functions:
            limit = per_source_limits.get(source, limit_per_source) if per_source_limits else limit_per_source
            tasks.append(search_functions[source](query, limit=limit))
            active_sources.append(source)

    # 使用 wait_for 添加总体超时，避免某个源卡住阻塞整个搜索
    source_counts: dict[str, int] = {}
    all_papers = []
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout,
        )
        for source_name, result in zip(active_sources, results):
            if isinstance(result, Exception):
                logger.error(
                    "Search source failed",
                    source=source_name,
                    query=query,
                    error=str(result),
                    error_type=type(result).__name__,
                )
                source_counts[source_name] = 0
                continue
            source_counts[source_name] = len(result)
            all_papers.extend(result)
    except asyncio.TimeoutError:
        logger.error(
            "Multi-source search timed out",
            query=query,
            timeout_seconds=timeout,
            sources=active_sources,
        )
        # 超时时尝试从已完成的任务中收集结果
        for i, task in enumerate(tasks):
            source_name = active_sources[i]
            if task.done() and not task.cancelled():
                try:
                    result = task.result()
                    if isinstance(result, list):
                        source_counts[source_name] = len(result)
                        all_papers.extend(result)
                    else:
                        source_counts[source_name] = 0
                except Exception:
                    source_counts[source_name] = 0
            else:
                source_counts[source_name] = 0
                task.cancel()

    logger.info(
        "Multi-source search completed",
        query=query,
        sources=active_sources,
        source_counts=source_counts,
        total_results=len(all_papers),
    )

    return all_papers
