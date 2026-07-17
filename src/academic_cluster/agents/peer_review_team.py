"""Peer-review Agent for the generated survey."""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

import structlog

from ..tools.agent_tools import peer_review_survey

logger = structlog.get_logger()

REVIEW_CHUNK_CHARS = 24_000


def _validated_score(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise RuntimeError(f"peer-review {field_name} must be a number")
    try:
        score = float(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"peer-review {field_name} must be a number") from error
    if not math.isfinite(score) or not 0.0 <= score <= 100.0:
        raise RuntimeError(
            f"peer-review {field_name} must be finite and between 0 and 100"
        )
    return score


def _normalized_text_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise RuntimeError(f"peer-review {field_name} must be a list")
    return [str(item).strip() for item in value if str(item).strip()]


def validate_peer_review_report(report: Any) -> dict[str, Any]:
    """Validate the quality gate payload before it can change graph routing."""

    required = {"overall_score", "strengths", "weaknesses", "suggestions"}
    if not isinstance(report, dict) or not required.issubset(report):
        raise RuntimeError("peer-review agent returned an incomplete report")

    normalized = dict(report)
    normalized["overall_score"] = _validated_score(
        report["overall_score"], "overall_score"
    )
    for field_name in ("strengths", "weaknesses", "suggestions"):
        normalized[field_name] = _normalized_text_list(report[field_name], field_name)

    dimensions = report.get("dimension_scores")
    if dimensions is not None:
        if not isinstance(dimensions, dict):
            raise RuntimeError("peer-review dimension_scores must be an object")
        normalized_dimensions: dict[str, dict[str, Any]] = {}
        for name, detail in dimensions.items():
            if not isinstance(detail, dict) or "score" not in detail:
                raise RuntimeError(f"peer-review dimension_scores.{name} is incomplete")
            normalized_dimensions[str(name)] = {
                **detail,
                "score": _validated_score(
                    detail["score"], f"dimension_scores.{name}.score"
                ),
                "comment": str(detail.get("comment") or "").strip(),
            }
        normalized["dimension_scores"] = normalized_dimensions

    if "summary" in normalized:
        normalized["summary"] = str(normalized.get("summary") or "").strip()
    return normalized


def _split_review_text(
    review_text: str,
    *,
    max_chars: int = REVIEW_CHUNK_CHARS,
) -> list[str]:
    """Split a review at Markdown/paragraph boundaries without dropping its tail."""

    text = review_text.strip()
    if not text:
        return []
    limit = max(1_000, max_chars)
    chunks: list[str] = []
    while len(text) > limit:
        minimum_break = limit // 2
        cut = limit
        for separator in ("\n## ", "\n\n", "\n"):
            position = text.rfind(separator, minimum_break, limit)
            if position >= minimum_break:
                cut = position + (1 if separator == "\n## " else len(separator))
                break
        chunk = text[:cut].strip()
        if chunk:
            chunks.append(chunk)
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def _unique_text(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _merge_peer_review_reports(
    reports: list[dict[str, Any]],
    weights: list[int],
) -> dict[str, Any]:
    if len(reports) == 1:
        return reports[0]
    total_weight = max(1, sum(weights))
    merged: dict[str, Any] = {
        "overall_score": round(
            sum(
                report["overall_score"] * weight
                for report, weight in zip(reports, weights, strict=True)
            )
            / total_weight,
            2,
        ),
        "summary": "\n".join(
            f"Part {index}: {report.get('summary', '')}".rstrip()
            for index, report in enumerate(reports, 1)
            if report.get("summary")
        ),
        "strengths": _unique_text(
            [item for report in reports for item in report["strengths"]]
        ),
        "weaknesses": _unique_text(
            [item for report in reports for item in report["weaknesses"]]
        ),
        "suggestions": _unique_text(
            [item for report in reports for item in report["suggestions"]]
        ),
        "reviewed_chunks": len(reports),
    }

    dimension_names = {
        str(name)
        for report in reports
        for name in (report.get("dimension_scores") or {})
    }
    if dimension_names:
        merged_dimensions: dict[str, dict[str, Any]] = {}
        for name in sorted(dimension_names):
            scored = [
                (report["dimension_scores"][name], weight)
                for report, weight in zip(reports, weights, strict=True)
                if name in (report.get("dimension_scores") or {})
            ]
            dimension_weight = max(1, sum(weight for _detail, weight in scored))
            merged_dimensions[name] = {
                "score": round(
                    sum(detail["score"] * weight for detail, weight in scored)
                    / dimension_weight,
                    2,
                ),
                "comment": " | ".join(
                    _unique_text(
                        [str(detail.get("comment") or "") for detail, _ in scored]
                    )
                ),
            }
        merged["dimension_scores"] = merged_dimensions
    return validate_peer_review_report(merged)


async def run_peer_review(
    review_text: str,
    topic: str,
    model_name: str = "provider-default",
) -> dict[str, Any]:
    """Run exactly one peer-review operation and validate its report."""

    if not review_text.strip():
        raise ValueError("review_text cannot be empty")
    del model_name
    chunks = _split_review_text(review_text)
    semaphore = asyncio.Semaphore(3)

    async def review_one(index: int, chunk: str) -> dict[str, Any]:
        payload = (
            chunk
            if len(chunks) == 1
            else f"[Document part {index + 1} of {len(chunks)}]\n\n{chunk}"
        )
        async with semaphore:
            raw_report = await peer_review_survey.ainvoke(
                {"review_text": payload, "topic": topic}
            )
        try:
            parsed = json.loads(str(raw_report))
        except (json.JSONDecodeError, TypeError) as error:
            raise RuntimeError("peer-review tool returned invalid JSON") from error
        return validate_peer_review_report(parsed)

    if len(chunks) == 1:
        reports = [await review_one(0, chunks[0])]
    else:
        tasks: list[asyncio.Task[dict[str, Any]]] = []
        async with asyncio.TaskGroup() as task_group:
            tasks = [
                task_group.create_task(
                    review_one(index, chunk),
                    name=f"agent-peer-review:{index}",
                )
                for index, chunk in enumerate(chunks)
            ]
        reports = [task.result() for task in tasks]
    report = _merge_peer_review_reports(reports, [len(chunk) for chunk in chunks])
    logger.info(
        "Peer review completed",
        topic=topic,
        score=report["overall_score"],
        chunks=len(chunks),
    )
    return {"review_report": report, "status": "completed"}
