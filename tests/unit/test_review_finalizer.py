import pytest

from academic_cluster.services.review_finalizer import (
    citation_reference_numbers,
    finalize_review_markdown,
)


def test_finalize_review_markdown_uses_first_appearance_reference_mapping():
    paper_metadata = {
        1: {
            "paper_id": "paper-a",
            "title": "Foundational Method",
            "authors": "Alice",
            "venue": "Journal A",
            "year": "2020",
            "doi": "10.1/a",
        },
        2: {
            "paper_id": "paper-b",
            "title": "Frontier Method",
            "authors": "Bob",
            "venue": "Journal B",
            "year": "2024",
            "doi": "10.1/b",
        },
    }

    finalized = finalize_review_markdown(
        review_title="测试综述",
        sections=[{"title": "方法对比"}],
        section_bodies=["前沿方法先出现 [2]，随后回到基础方法 [1]。"],
        paper_metadata_map=paper_metadata,
    )

    assert finalized.body_markdown.startswith("# 测试综述")
    assert "前沿方法先出现 [1]，随后回到基础方法 [2]。" in finalized.markdown
    assert "[1] Bob," in finalized.markdown
    assert '"Frontier Method"' in finalized.markdown
    assert "[2] Alice," in finalized.markdown
    assert finalized.reference_mappings[0]["paper_id"] == "paper-b"
    assert finalized.reference_mappings[1]["paper_id"] == "paper-a"


def test_finalize_review_markdown_references_only_cited_papers():
    paper_metadata = {
        1: {"paper_id": "paper-a", "title": "Cited Paper", "authors": "Alice"},
        2: {"paper_id": "paper-b", "title": "Uncited Paper", "authors": "Bob"},
    }

    finalized = finalize_review_markdown(
        review_title="Review",
        sections=[{"title": "Only cited references"}],
        section_bodies=["Only one paper is cited ([1]); placeholder ([x]) is invalid."],
        paper_metadata_map=paper_metadata,
    )

    assert "([1])" not in finalized.markdown
    assert "([x])" not in finalized.markdown
    assert "[1] Alice," in finalized.markdown
    assert "Cited Paper" in finalized.markdown
    assert "Uncited Paper" not in finalized.markdown
    assert len(finalized.reference_mappings) == 1


def test_finalize_review_counts_abstract_and_titles_in_first_use_order():
    finalized = finalize_review_markdown(
        review_title="Review [3]",
        abstract="Abstract cites the second section first [2].",
        sections=[
            {"title": "Background [1]"},
            {"title": "Applications"},
        ],
        section_bodies=[
            "Background body uses [1] and then [3].",
            "Applications body uses [2].",
        ],
        paper_metadata_map={
            1: {"paper_id": "paper-a", "title": "A"},
            2: {"paper_id": "paper-b", "title": "B"},
            3: {"paper_id": "paper-c", "title": "C"},
        },
    )

    assert [mapping["original_number"] for mapping in finalized.reference_mappings] == [
        3,
        2,
        1,
    ]
    assert finalized.body_markdown.startswith("# Review [1]")
    assert "## 摘要\n\nAbstract cites the second section first [2]." in (
        finalized.body_markdown
    )
    assert "## 1. Background [3]" in finalized.body_markdown


def test_finalize_rejects_unknown_title_citation():
    with pytest.raises(ValueError, match="unknown citation number: 99"):
        finalize_review_markdown(
            review_title="Survey [99]",
            sections=[{"title": "Body"}],
            section_bodies=["Supported claim [1]."],
            paper_metadata_map={1: {"paper_id": "paper-1", "title": "Known paper"}},
        )


def test_citation_reference_numbers_ignores_code_and_math_regions():
    markdown = (
        "```python\nprotected = refs[99]\n```\n`inline[98]` "
        "$math[97]$ $$display[96]$$ "
        r"\(latex[95]\) \[display[94]\] "
        "Visible citation [3]."
    )

    assert citation_reference_numbers(markdown) == {3}


def test_finalize_review_rejects_malformed_citation_range():
    with pytest.raises(ValueError, match="citation range exceeds"):
        finalize_review_markdown(
            review_title="Review",
            sections=[{"title": "Body"}],
            section_bodies=["A valid citation [1] cannot hide [2-50]."],
            paper_metadata_map={1: {"paper_id": "paper-1", "title": "Known"}},
        )
