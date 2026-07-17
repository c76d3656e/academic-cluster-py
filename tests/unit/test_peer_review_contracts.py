"""Peer-review model output and document chunking quality-gate contracts."""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from academic_cluster.agents import peer_review_team


def _report(**updates: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "overall_score": 80,
        "summary": " sound review ",
        "strengths": [" grounded ", ""],
        "weaknesses": [],
        "suggestions": ["clarify"],
    }
    report.update(updates)
    return report


@pytest.mark.parametrize(
    ("report", "message"),
    [
        ({"overall_score": 80}, "incomplete report"),
        (_report(overall_score="not-a-score"), "overall_score must be a number"),
        (_report(strengths="grounded"), "strengths must be a list"),
        (_report(dimension_scores=[]), "dimension_scores must be an object"),
        (
            _report(dimension_scores={"rigor": {"comment": "missing score"}}),
            "dimension_scores.rigor is incomplete",
        ),
        (
            _report(
                dimension_scores={"rigor": {"score": math.inf, "comment": "invalid"}}
            ),
            "finite and between 0 and 100",
        ),
    ],
)
def test_validate_peer_review_report_rejects_invalid_gate_payloads(
    report: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        peer_review_team.validate_peer_review_report(report)


def test_validate_and_merge_reports_normalizes_weighted_dimensions() -> None:
    first = peer_review_team.validate_peer_review_report(
        _report(
            overall_score="70",
            strengths=["grounded", "shared"],
            suggestions=["clarify"],
            dimension_scores={"rigor": {"score": 60, "comment": "first"}},
        )
    )
    second = peer_review_team.validate_peer_review_report(
        _report(
            overall_score=90,
            summary="second",
            strengths=["shared", "complete"],
            suggestions=["clarify", "expand"],
            dimension_scores={
                "rigor": {"score": 90, "comment": "second"},
                "citations": {"score": 80},
            },
        )
    )

    merged = peer_review_team._merge_peer_review_reports(
        [first, second],
        [1, 3],
    )

    assert merged["overall_score"] == 85.0
    assert merged["summary"] == "Part 1: sound review\nPart 2: second"
    assert merged["strengths"] == ["grounded", "shared", "complete"]
    assert merged["suggestions"] == ["clarify", "expand"]
    assert merged["reviewed_chunks"] == 2
    assert merged["dimension_scores"]["rigor"] == {
        "score": 82.5,
        "comment": "first | second",
    }
    assert merged["dimension_scores"]["citations"] == {
        "score": 80.0,
        "comment": "",
    }


def test_review_chunking_keeps_document_tail_and_markdown_boundaries() -> None:
    assert peer_review_team._split_review_text("   ") == []
    sentinel = "TAIL_SENTINEL_[9]"
    text = ("paragraph evidence [1].\n\n" * 120) + "\n## Final\n" + sentinel

    chunks = peer_review_team._split_review_text(text, max_chars=1_000)

    assert len(chunks) > 1
    assert all(len(chunk) <= 1_000 for chunk in chunks)
    assert chunks[-1].endswith(sentinel)
    assert sum(chunk.count("paragraph evidence") for chunk in chunks) == 120


@pytest.mark.asyncio
async def test_run_peer_review_rejects_empty_or_invalid_tool_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        await peer_review_team.run_peer_review(" ", "topic")

    class _Tool:
        async def ainvoke(self, _inputs: dict[str, Any]) -> str:
            return "not-json"

    monkeypatch.setattr(peer_review_team, "peer_review_survey", _Tool())

    with pytest.raises(RuntimeError, match="invalid JSON"):
        await peer_review_team.run_peer_review("Supported review [1].", "topic")


@pytest.mark.asyncio
async def test_run_peer_review_rejects_incomplete_tool_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Tool:
        async def ainvoke(self, _inputs: dict[str, Any]) -> str:
            return json.dumps({"overall_score": 90})

    monkeypatch.setattr(peer_review_team, "peer_review_survey", _Tool())

    with pytest.raises(RuntimeError, match="incomplete report"):
        await peer_review_team.run_peer_review("Supported review [1].", "topic")
