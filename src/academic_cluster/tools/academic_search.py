"""
学术搜索工具

实现对多个学术数据源的搜索：
- Semantic Scholar
- PubMed
- arXiv
- OpenAlex
- Crossref
"""

import asyncio
from typing import Optional

import httpx
import structlog

from ..config import get_settings

logger = structlog.get_logger()


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
    """
    settings = get_settings()
    api_key = settings.academic_sources.semantic_scholar_api_key

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

    headers = {}
    if api_key:
        headers["x-api-key"] = api_key

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            papers = []
            for item in data.get("data", []):
                papers.append({
                    "external_id": item.get("paperId"),
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
                    "doi": item.get("externalIds", {}).get("DOI"),
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
    email = settings.academic_sources.pubmed_email
    tool = settings.academic_sources.pubmed_tool
    api_key = settings.academic_sources.pubmed_api_key

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
            search_response = await client.get(search_url, params=search_params, timeout=30)
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

            fetch_response = await client.get(fetch_url, params=fetch_params, timeout=30)
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

                papers.append({
                    "external_id": f"PMID:{pmid}",
                    "source": "pubmed",
                    "title": article.get("title", ""),
                    "abstract": "",  # esummary 不返回摘要，需要额外调用 efetch
                    "authors": authors,
                    "publication_date": article.get("pubdate"),
                    "year": article.get("pubdate", "")[:4],
                    "journal": article.get("fulljournalname", article.get("source", "")),
                    "doi": article.get("elocationid", "").replace("doi: ", ""),
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
    url = "http://export.arxiv.org/api/query"

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
            response = await client.get(url, params=params, timeout=30)
            response.raise_for_status()

            # arXiv 返回 XML，需要解析
            import xml.etree.ElementTree as ET

            root = ET.fromstring(response.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

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

                papers.append({
                    "external_id": f"arXiv:{arxiv_id}",
                    "source": "arxiv",
                    "title": title.text.strip().replace("\n", " ") if title is not None else "",
                    "abstract": summary.text.strip().replace("\n", " ") if summary is not None else "",
                    "authors": authors,
                    "publication_date": published.text if published is not None else "",
                    "year": published.text[:4] if published is not None else "",
                    "url": entry_id.text if entry_id is not None else "",
                    "pdf_url": pdf_url,
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
        "mailto": get_settings().academic_sources.pubmed_email,
    }

    if from_year:
        params["filter"] = f"publication_year:{from_year}-{to_year or 2024}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            papers = []
            for work in data.get("results", []):
                # 提取作者
                authors = [
                    {"name": a.get("author", {}).get("display_name", "")}
                    for a in work.get("authorships", [])
                ]

                # 提取 DOI
                doi = work.get("doi", "")
                if doi and doi.startswith("https://doi.org/"):
                    doi = doi[16:]

                papers.append({
                    "external_id": work.get("id", "").split("/")[-1],
                    "source": "openalex",
                    "title": work.get("title", ""),
                    "abstract": "",  # OpenAlex 需要单独获取摘要
                    "authors": authors,
                    "publication_date": work.get("publication_date"),
                    "year": work.get("publication_year"),
                    "journal": work.get("primary_location", {}).get("source", {}).get("display_name"),
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
