"""Reference-map, citation, and score validation tests for Agent output."""

import math

import pytest

from academic_cluster.agents.agent_graph import (
    build_reference_map,
    validate_citations,
)
from academic_cluster.tools.agent_tools import (
    _normalized_text_items,
    _validated_coverage_score,
)


def test_reference_map_is_stable_and_deduplicated() -> None:
    papers = [
        {"id": "p1", "title": "First", "year": 2024, "doi": "10.1/one"},
        {"id": "p1", "title": "Duplicate"},
        {"id": "p2", "title": "Second", "publication_date": "2023-01-02"},
    ]

    references = build_reference_map(papers, limit=30)

    assert [ref["number"] for ref in references] == [1, 2]
    assert [ref["paper_id"] for ref in references] == ["p1", "p2"]
    assert references[1]["year"] == "2023"


def test_validate_citations_accepts_known_numbers() -> None:
    result = validate_citations("Prior work [1] agrees with [2, 3].", 3)

    assert result.cited_numbers == {1, 2, 3}
    assert result.invalid_numbers == set()


def test_validate_citations_rejects_out_of_range_numbers() -> None:
    result = validate_citations("Valid [1], invalid [4] and [0].", 3)

    assert result.cited_numbers == {1}
    assert result.invalid_numbers == {0, 4}


def test_validate_citations_reports_uncited_output() -> None:
    result = validate_citations("No citations in this generated section.", 5)

    assert result.cited_numbers == set()
    assert result.invalid_numbers == set()


def test_validate_citations_rejects_numbers_outside_section_plan() -> None:
    result = validate_citations(
        "Planned evidence [2], unprovided evidence [1].",
        3,
        allowed_numbers={2, 3},
    )

    assert result.cited_numbers == {1, 2}
    assert result.invalid_numbers == set()
    assert result.disallowed_numbers == {1}


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, -0.1, 1.1, True])
def test_coverage_score_rejects_nonfinite_or_out_of_range(value: object) -> None:
    with pytest.raises(ValueError, match="coverage_score"):
        _validated_coverage_score(value)


def test_coverage_text_lists_reject_scalar_and_non_string_payloads() -> None:
    assert _normalized_text_items("one query") == []
    assert _normalized_text_items([" query ", 3, None, ""]) == ["query"]
