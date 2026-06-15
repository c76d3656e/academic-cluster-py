from academic_cluster.services.review_finalizer import (
    finalize_review_markdown,
    remap_section_local_citations,
)


def test_remap_section_local_citations_preserves_section_candidate_identity():
    paper_number_by_id = {"paper-a": 1, "paper-b": 2, "paper-c": 3}

    remapped, invalid = remap_section_local_citations(
        "方法一形成基线 [1]，方法二提供补充证据 [2]。",
        ["paper-b", "paper-c"],
        paper_number_by_id,
    )

    assert invalid == set()
    assert remapped == "方法一形成基线 [2]，方法二提供补充证据 [3]。"


def test_remap_section_local_citations_reports_outside_candidate_numbers():
    remapped, invalid = remap_section_local_citations(
        "该论断引用了不存在的章节候选 [3]。",
        ["paper-a", "paper-b"],
        {"paper-a": 1, "paper-b": 2},
    )

    assert invalid == {3}
    assert remapped == "该论断引用了不存在的章节候选 。"


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
