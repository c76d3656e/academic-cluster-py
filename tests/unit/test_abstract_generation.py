from academic_cluster.graphs.nodes.abstract_generation import (
    _review_body_for_abstract,
    clean_generated_abstract,
)


def test_review_body_for_abstract_strips_references_and_citations():
    markdown = """# Title

## Section

多智能体系统在规划与工具使用方面形成了新的技术路线[1,2]。

## References

[1] Example paper.
"""

    body = _review_body_for_abstract(markdown)

    assert "References" not in body
    assert "[1,2]" not in body
    assert "多智能体系统" in body


def test_clean_generated_abstract_removes_heading_and_citations():
    raw = """## Abstract

摘要：多智能体系统综述强调规划、工具调用与安全评估之间的协同关系[3]，并指出跨场景泛化仍需改进。
"""

    cleaned = clean_generated_abstract(raw)

    assert "Abstract" not in cleaned
    assert "摘要：" not in cleaned
    assert "[3]" not in cleaned
    assert "跨场景泛化" in cleaned
