"""Post-review abstract generation node."""

from __future__ import annotations

import re

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from ...prompts import get_generate_abstract_prompt
from ...services.citation_utils import strip_reference_block
from ...services.database import get_database
from ...services.llm_client import ainvoke_with_callbacks, create_llm
from ...services.observability import get_current_tracker
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()

_CITATION_TOKEN_RE = re.compile(r"\[[0-9,\s;、，\-–—]+\]")
_AUTHOR_YEAR_RE = re.compile(
    r"[（(][A-Z][a-z]+(?:\s+(?:et\s+al\.?|&\s+[A-Z][a-z]+))?"
    r"(?:\s*[,;]\s*[A-Z][a-z]+(?:\s+(?:et\s+al\.?|&\s+[A-Z][a-z]+))?)*"
    r"\s*,\s*\d{4}(?:\s*[;,]\s*\d{4})*[）)]"
)
_MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+.*$", re.MULTILINE)


def _coerce_text(content) -> str:
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content or "")


def _review_body_for_abstract(markdown: str, max_chars: int = 24000) -> str:
    """Prepare finalized review body for abstract generation."""
    body = strip_reference_block(markdown or "")
    body = _CITATION_TOKEN_RE.sub("", body)
    body = _AUTHOR_YEAR_RE.sub("", body)
    body = re.sub(r"^\s*#\s+.*$", "", body, flags=re.MULTILINE)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()[:max_chars]


def clean_generated_abstract(text: str) -> str:
    """Remove headings, citations, references, and formatting from an abstract."""
    text = _coerce_text(text)
    text = text.replace("```", "").strip()
    text = _MARKDOWN_HEADING_RE.sub("", text)
    text = re.sub(r"^\s*(?:摘要|Abstract)\s*[:：]?\s*", "", text, flags=re.IGNORECASE)
    text = strip_reference_block(text)
    text = _CITATION_TOKEN_RE.sub("", text)
    text = _AUTHOR_YEAR_RE.sub("", text)
    text = re.sub(r"\[[A-Za-z0-9_,:\-\s]+\]", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([，。；：、！？,.!?;:])", r"\1", text)
    return text.strip()


def _fallback_abstract(review_body: str, max_chars: int = 360) -> str:
    """Deterministic fallback: first coherent body sentences without citations."""
    text = clean_generated_abstract(review_body)
    sentences = re.split(r"(?<=[。！？.!?])\s*", text)
    selected: list[str] = []
    total = 0
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence or sentence.startswith("#"):
            continue
        selected.append(sentence)
        total += len(sentence)
        if total >= 260:
            break
    fallback = "".join(selected).strip()
    return fallback[:max_chars].rstrip("，,；;：:")


async def generate_abstract_node(state: PipelineState) -> dict:
    """Generate a citation-free abstract after final review writing."""
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("abstract_generation", "llm", index=14)

    await send_progress(
        state.project_id,
        "abstract_generation",
        "正在根据全文生成无引用摘要...",
    )

    final_review = state.final_review or ""
    if not final_review.strip():
        raise ValueError("No final review content available for abstract generation")

    review_body = _review_body_for_abstract(final_review)
    outline_data = state.outline_data or {}
    review_title = outline_data.get("title") or f"Review: {state.query}"

    prompt_template = get_generate_abstract_prompt()
    prompt = prompt_template.format(
        topic=state.query,
        review_title=review_title,
        review_body=review_body,
    )

    try:
        llm = create_llm(temperature=0.2, max_tokens=1024)
        response = await ainvoke_with_callbacks(
            llm,
            [
                SystemMessage(content="Write only a citation-free Chinese abstract. No markdown, no citations, no references."),
                HumanMessage(content=prompt),
            ],
            timeout=240.0,
        )
        abstract = clean_generated_abstract(response.content)
        if len(abstract) < 80:
            abstract = _fallback_abstract(review_body)
    except Exception as e:
        logger.warning("Abstract LLM generation failed, using fallback", error=str(e))
        abstract = _fallback_abstract(review_body)

    if not abstract:
        raise ValueError("Abstract generation produced empty output")

    db = get_database()
    try:
        final_artifact = await db.get_pipeline_checkpoint(state.project_id, "final_review_artifact")
        snapshot = final_artifact.get("state_snapshot") if final_artifact else {}
        if isinstance(snapshot, str):
            import json as _json
            try:
                snapshot = _json.loads(snapshot)
            except (_json.JSONDecodeError, TypeError):
                snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        snapshot["abstract"] = abstract
        await db.save_pipeline_checkpoint({
            "project_id": state.project_id,
            "node_name": "final_review_artifact",
            "state_snapshot": snapshot,
            "status": "completed",
        })
    except Exception as e:
        logger.warning("Failed to persist abstract into final artifact checkpoint", error=str(e))

    logger.info("Abstract generation completed", chars=len(abstract))
    if tracker:
        await tracker.end_node("abstract_generation", "succeeded", output_summary={
            "abstract_chars": len(abstract),
        })

    return {
        "abstract": abstract,
        "status": "abstract_generated",
    }

