"""Writing Agent responsible for producing a structured review outline."""

from __future__ import annotations

import json
from typing import Any

import structlog

from ..tools.agent_tools import generate_outline

logger = structlog.get_logger()


async def run_writing(
    topic: str,
    evidence_cards: list[dict[str, Any]],
    target_words: int = 12000,
    model_name: str = "provider-default",
) -> dict[str, Any]:
    """Generate and validate one outline without a redundant ReAct loop."""

    del model_name
    evidence_summary = [
        {
            "paper_id": card.get("paper_id"),
            "title": card.get("title") or card.get("paper_title"),
            "claim": str(card.get("claim") or "")[:300],
            "method": card.get("method"),
            "limitation": card.get("limitation"),
        }
        for card in evidence_cards[:80]
        if isinstance(card, dict)
    ]
    raw_outline = await generate_outline.ainvoke(
        {
            "topic": topic,
            "evidence_json": json.dumps(evidence_summary, ensure_ascii=False),
            "target_words": target_words,
        }
    )
    try:
        parsed = json.loads(str(raw_outline))
    except (json.JSONDecodeError, TypeError) as error:
        raise RuntimeError("outline tool returned invalid JSON") from error
    outline = parsed if isinstance(parsed, dict) else {}
    sections = outline.get("sections") if isinstance(outline, dict) else None
    if not isinstance(sections, list) or len(sections) < 3:
        raise RuntimeError("writing agent returned an invalid outline")
    logger.info("Writing outline completed", topic=topic, sections=len(sections))
    return {"outline": outline, "status": "completed"}
