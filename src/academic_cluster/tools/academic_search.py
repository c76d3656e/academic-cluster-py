"""
学术搜索工具

实现对多个学术数据源的搜索：
- Semantic Scholar
- PubMed
- arXiv
- OpenAlex
- Crossref

各 API 速率限制（已在 _RATE_LIMITS 中配置）：
- arXiv:            1 请求 / 3 秒（无认证，最严格）
- Semantic Scholar:  1 请求 / 秒（无 key），100 请求 / 秒（有 key）
- PubMed:           3 请求 / 秒（无 key），10 请求 / 秒（有 key）
- OpenAlex:         ~10 请求 / 秒（无 mailto），~100 请求 / 秒（polite pool）
"""

import asyncio
import time
from typing import Optional

import httpx
import structlog

from ..config import get_settings
from .doi import normalize_doi, is_valid_doi, extract_doi

logger = structlog.get_logger()


# =============================================================================
# 速率限制器
# =============================================================================

# 各源最小请求间隔（秒），根据配置动态计算
_RATE_LIMITS: dict[str, float] | None = None


def _get_rate_limits() -> dict[str, float]:
    """根据实际配置动态生成各源的最小请求间隔"""
    global _RATE_LIMITS
    if _RATE_LIMITS is not None:
        return _RATE_LIMITS

    settings = get_settings()
    _RATE_LIMITS = {
        "arxiv": 3.0,                                           # 1 req / 3s（无认证）
        "semantic_scholar": 1.0,                                 # 1 req / s / key
        "pubmed": 0.1 if settings.pubmed_api_key else 0.34,      # 有 key: 10 rps, 无 key: 3 rps
        "openalex": 0.1,                                         # polite pool
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
        min_interval = _get_rate_limits().get(source, 1.0)
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


def _get_s2_key_pool() -> SemanticScholarKeyPool | None:
    """获取或创建 Semantic Scholar key pool"""
    global _s2_key_pool
    if _s2_key_pool is not None:
        return _s2_key_pool

    settings = get_settings()
    keys = settings.semantic_scholar_api_keys
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
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait = float(retry_after)
            else:
                wait = min(2 ** (attempt + 1), 30)
            logger.warning(
                "Rate limited (429), retrying",
                source=source,
                attempt=attempt + 1,
                wait_seconds=wait,
            )
            await asyncio.sleep(wait)
            continue

        return response

    # 所有重试用尽，返回最后一次响应让调用方处理
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
    pool = _get_s2_key_pool()

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
                settings = get_settings()
                headers = {}
                if settings.semantic_scholar_api_key:
                    headers["x-api-key"] = settings.semantic_scholar_api_key
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
            logger.error("Semantic Scholar search failed", error=str(e))
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
    settings = get_settings()
    email = settings.pubmed_email
    tool = "academic-cluster"
    api_key = settings.pubmed_api_key

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
            logger.error("PubMed search failed", error=str(e))
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
            logger.error("arXiv search failed", error=str(e))
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
        "mailto": get_settings().pubmed_email,
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
            logger.error("OpenAlex search failed", error=str(e))
            return []


# =============================================================================
# 统一搜索接口
# =============================================================================

async def search_all_sources(
    query: str,
    limit_per_source: int = 100,
    sources: Optional[list[str]] = None,
) -> list[dict]:
    """
    并行搜索所有数据源

    Args:
        query: 搜索查询
        limit_per_source: 每个源的最大结果数
        sources: 要搜索的源列表，默认全部

    Returns:
        合并的论文列表
    """
    if sources is None:
        sources = ["semantic_scholar", "pubmed", "arxiv", "openalex"]

    search_functions = {
        "semantic_scholar": search_semantic_scholar,
        "pubmed": search_pubmed,
        "arxiv": search_arxiv,
        "openalex": search_openalex,
    }

    tasks = []
    for source in sources:
        if source in search_functions:
            tasks.append(search_functions[source](query, limit=limit_per_source))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_papers = []
    for result in results:
        if isinstance(result, Exception):
            logger.error("Search source failed", error=str(result))
            continue
        all_papers.extend(result)

    logger.info(
        "Multi-source search completed",
        query=query,
        sources=sources,
        total_results=len(all_papers),
    )

    return all_papers
