"""
证据生成 Agent

负责为论文生成结构化证据卡片。
"""

import json
from collections.abc import Callable
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()

CORE_EVIDENCE_CARD_TARGET = 160
DEFAULT_EVIDENCE_CARD_TIMEOUT_S = 300


EVIDENCE_SYSTEM_PROMPT = """你是一个学术证据分析专家。你的任务是从学术论文中提取结构化的证据信息。

对于每篇论文，你需要生成一个证据卡片，包含：
- claim: 论文的核心主张或贡献
- evidence_span: 支持主张的关键证据片段（直接引用或摘要）
- method: 使用的主要方法
- metric: 使用的评估指标
- limitation: 论文提到的局限性
- confidence: 证据的置信度 (0-1)

输出格式（严格 JSON）：
{
  "claim": "核心主张",
  "evidence_span": "证据片段",
  "method": "使用方法",
  "metric": "评估指标",
  "limitation": "局限性",
  "confidence": 0.85
}
"""


EVIDENCE_PROMPT = """请分析以下论文并生成证据卡片。

标题: {title}
摘要: {abstract}
社区主题: {cluster_topics}

请以 JSON 格式输出。
"""


def create_evidence_agent(
    model: str | None = None,
    temperature: float = 0.2,
) -> ChatOpenAI:
    """创建证据生成 Agent"""
    from ..services.llm_client import create_llm

    return create_llm(temperature=temperature)


async def generate_evidence_card(
    paper: dict[str, Any],
    cluster_topics: list[str] | None = None,
) -> dict[str, Any]:
    """
    为单篇论文生成证据卡片

    Args:
        paper: 论文信息，包含 title 和 abstract
        cluster_topics: 论文所属社区的主题

    Returns:
        证据卡片数据
    """
    agent = create_evidence_agent()

    prompt = EVIDENCE_PROMPT.format(
        title=paper.get("title", ""),
        abstract=paper.get("abstract", "无摘要"),
        cluster_topics=", ".join(cluster_topics) if cluster_topics else "未知",
    )

    messages = [
        SystemMessage(content=EVIDENCE_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    from ..services.llm_client import ainvoke_with_callbacks

    response = await ainvoke_with_callbacks(agent, messages)

    # LLM 响应 content 可能是 list（多模态格式）或 string
    raw_content = response.content
    if isinstance(raw_content, list):
        raw_content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in raw_content
        )

    try:
        result = json.loads(raw_content)
    except json.JSONDecodeError:
        # 去掉 markdown 代码块
        content = raw_content.replace("```json", "").replace("```", "").strip()
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取 JSON 对象
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end > start:
                try:
                    result = json.loads(content[start : end + 1])
                except json.JSONDecodeError:
                    logger.error(
                        "Failed to parse evidence response", response=raw_content[:500]
                    )
                    raise ValueError(
                        f"LLM returned invalid JSON for evidence card: {raw_content[:200]}"
                    ) from None
            else:
                logger.error(
                    "Failed to parse evidence response", response=raw_content[:500]
                )
                raise ValueError(
                    f"LLM returned invalid JSON for evidence card: {raw_content[:200]}"
                ) from None

    # 添加论文 ID
    result["paper_id"] = paper.get("id")

    return result  # type: ignore[no-any-return]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _truncate_text(value: Any, max_chars: int) -> str:
    return _clean_text(value)[:max_chars]


def _paper_year(paper: dict[str, Any]) -> int | None:
    year = paper.get("year")
    if year:
        try:
            return int(str(year)[:4])
        except (TypeError, ValueError):
            pass
    publication_date = paper.get("publication_date")
    if publication_date:
        try:
            return int(str(publication_date)[:4])
        except (TypeError, ValueError):
            return None
    return None


def _clean_optional(value: Any, max_chars: int) -> str | None:
    cleaned = _truncate_text(value, max_chars)
    return cleaned or None


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if confidence != confidence:
        return 0.0
    return max(0.0, min(1.0, confidence))


def fallback_missing_card(paper: dict[str, Any]) -> dict[str, Any]:
    title = _clean_text(paper.get("title")) or "Untitled"
    abstract = _clean_text(paper.get("abstract")) or title
    return {
        "paper_id": str(paper.get("id", "")),
        "title": title,
        "authors": paper.get("authors"),
        "year": _paper_year(paper),
        "claim": _truncate_text(abstract, 220),
        "evidence_span": _truncate_text(abstract, 320),
        "method": None,
        "metric": None,
        "limitation": "LLM evidence card extraction did not return a usable card for this paper.",
        "source_api": "fallback_missing_card",
        "confidence": 0.05,
    }


def normalize_evidence_card(
    raw_card: dict[str, Any] | None, paper: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(raw_card, dict):
        return fallback_missing_card(paper)

    card = dict(raw_card)
    claim = _truncate_text(card.get("claim") or card.get("key_finding"), 500)
    evidence_span = _truncate_text(card.get("evidence_span"), 500)
    if not claim or not evidence_span:
        return fallback_missing_card(paper)

    return {
        **card,
        "paper_id": str(paper.get("id", "")),
        "title": _clean_text(paper.get("title"))
        or _clean_text(card.get("title"))
        or "Untitled",
        "authors": card.get("authors") or paper.get("authors"),
        "year": card.get("year") or _paper_year(paper),
        "claim": claim,
        "evidence_span": evidence_span,
        "method": _clean_optional(card.get("method"), 240),
        "metric": card.get("metric"),
        "limitation": _clean_optional(card.get("limitation"), 240),
        "source_api": _clean_text(card.get("source_api")) or "llm",
        "confidence": _clamp_confidence(card.get("confidence")),
    }


async def generate_evidence_cards_batch(
    papers: list[dict[str, Any]],
    cluster_topics: dict[str, list[str]] | None = None,
    concurrency: int | None = None,
    timeout_s: int = DEFAULT_EVIDENCE_CARD_TIMEOUT_S,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """
    批量生成证据卡片

    Args:
        papers: 论文列表
        cluster_topics: 论文 ID 到社区主题的映射
        progress_callback: 进度回调 (completed, total)

    Returns:
        证据卡片列表
    """
    import asyncio

    if cluster_topics is None:
        cluster_topics = {}

    max_concurrency = max(1, int(concurrency or len(papers) or 1))
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _bounded_generate(
        idx: int, paper: dict[str, Any]
    ) -> tuple[int, dict[str, Any] | None, Exception | None]:
        async with semaphore:
            try:
                card = await asyncio.wait_for(
                    generate_evidence_card(
                        paper=paper,
                        cluster_topics=cluster_topics.get(str(paper.get("id", ""))),
                    ),
                    timeout=max(1, timeout_s),
                )
                return idx, card, None
            except Exception as e:
                return idx, None, e

    tasks = [_bounded_generate(i, paper) for i, paper in enumerate(papers)]
    evidence_cards: list[dict[str, Any] | None] = [None] * len(papers)
    total = len(papers)

    for completed, future in enumerate(asyncio.as_completed(tasks), 1):
        idx, card, error = await future
        if error:
            logger.error(
                "Evidence generation failed, using fallback card",
                paper_id=papers[idx].get("id"),
                error=str(error),
            )
            evidence_cards[idx] = fallback_missing_card(papers[idx])
        else:
            evidence_cards[idx] = normalize_evidence_card(card, papers[idx])

        if progress_callback:
            progress_callback(completed, total)

    result_cards = [c for c in evidence_cards if c is not None]

    logger.info(
        "Evidence cards generated",
        total=total,
        successful=len(result_cards),
        concurrency=max_concurrency,
    )

    return result_cards
