from academic_cluster.services.citation_utils import (
    normalize_citation_surface,
    strip_body_structure_leakage,
    strip_revision_commentary,
    strip_unsupported_precise_metrics,
)
from academic_cluster.agents.section_evaluator import _check_citation_format


def test_strip_body_structure_leakage_removes_markdown_body_headings():
    content = "### Frontier methods\n\nThese methods improve planning [1]."

    cleaned = strip_body_structure_leakage(content)

    assert "###" not in cleaned
    assert cleaned.startswith("Frontier methods.")
    assert "These methods improve planning [1]." in cleaned


def test_strip_body_structure_leakage_removes_visible_template_labels():
    content = "Conclusion: The field still lacks robust evaluation [2].\nFuture direction: Better benchmarks are needed [3]."

    cleaned = strip_body_structure_leakage(content)

    assert "Conclusion:" not in cleaned
    assert "Future direction:" not in cleaned
    assert "The field still lacks robust evaluation [2]." in cleaned
    assert "Better benchmarks are needed [3]." in cleaned


def test_strip_revision_commentary_removes_visible_chinese_revision_note():
    content = (
        "跨模态融合仍缺乏统一评估标准[1]。\n\n"
        "（说明：本修改严格遵循用户规则，仅修改当前段落。1）保留所有原始引用[1,5,6,10,7,2,8,3]且不新增；"
        "2）消除冗余过渡词，改用数据支撑的学术表达。）\n\n"
        "后续研究需要建立任务级基准[2]。"
    )

    cleaned = strip_revision_commentary(content)

    assert "本修改严格遵循" not in cleaned
    assert "仅修改当前段落" not in cleaned
    assert "保留所有原始引用" not in cleaned
    assert "跨模态融合仍缺乏统一评估标准[1]。" in cleaned
    assert "后续研究需要建立任务级基准[2]。" in cleaned


def test_strip_revision_commentary_removes_think_blocks():
    content = "<think>我需要先分析用户要求，保持引用不变。</think>\n\n正式正文保留[1]。"

    cleaned = strip_revision_commentary(content)

    assert "<think>" not in cleaned
    assert "用户要求" not in cleaned
    assert cleaned == "正式正文保留[1]。"


def test_strip_unsupported_precise_metrics_keeps_metrics_present_in_evidence():
    content = "该系统在测试集中达到87.3%的偏好匹配率[1]。但另一个未证实指标为63.2%[1]。"
    cards = [{"metric": "87.3%", "evidence_span": "test preference rate reaches 87.3%"}]

    cleaned = strip_unsupported_precise_metrics(content, cards)

    assert "87.3%" in cleaned
    # 有引用标记 [N] 的句子即使指标不在 evidence card 中也保留（指标来自被引文献）
    assert "63.2%" in cleaned


def test_strip_unsupported_precise_metrics_removes_metric_without_citation():
    content = "该系统在测试集中达到87.3%的偏好匹配率。另一个未证实指标为63.2%。"
    cards = [{"metric": "87.3%", "evidence_span": "test preference rate reaches 87.3%"}]

    cleaned = strip_unsupported_precise_metrics(content, cards)

    # 无引用标记时，unsupported metric 仍然应该被删除
    assert "87.3%" in cleaned
    assert "63.2%" not in cleaned


def test_strip_unsupported_precise_metrics_does_not_remove_years_or_plain_citations():
    content = "2024年的研究指出该方向仍在发展[1]。该结论与后续工作一致[2]。"

    cleaned = strip_unsupported_precise_metrics(content, [{"claim": "该方向仍在发展"}])

    assert cleaned == content


def test_normalize_citation_surface_unwraps_parenthesized_numeric_citations():
    content = "医疗场景（[7]）与自动驾驶([8])存在差异，而占位符([x])应删除。"

    cleaned = normalize_citation_surface(content)

    assert "（[7]）" not in cleaned
    assert "([8])" not in cleaned
    assert "([x])" not in cleaned
    assert "[7]" in cleaned
    assert "[8]" in cleaned


def test_normalize_citation_surface_keeps_parenthesized_citation_prose_unchanged():
    content = "特别是在5G/6G网络延迟波动场景中（文献[24][28]已证实网络稳定性对技术效能的影响系数达0.65），探索轻量化评估框架。"

    cleaned = normalize_citation_surface(content)

    assert cleaned == content


def test_normalize_citation_surface_removes_placeholder_citation_chains():
    content = "该句含有占位符([x])和另一个占位符（[x1,x2,x3]），但真实引用([1][2])应保留为普通编号。"

    cleaned = normalize_citation_surface(content)

    assert "([x])" not in cleaned
    assert "（[x1,x2,x3]）" not in cleaned
    assert "[1,2]" in cleaned


def test_check_citation_format_flags_parenthesized_citation_prose():
    draft = "特别是在5G/6G网络延迟波动场景中（文献[24][28]已证实网络稳定性对技术效能的影响系数达0.65），探索轻量化评估框架。"

    result = _check_citation_format(draft)

    assert result["parenthesized_citation_count"] == 1
    assert result["issues"]


def test_check_citation_format_flags_adjacent_numeric_citations():
    draft = "已有研究[24][28]证实网络稳定性的重要性。"

    result = _check_citation_format(draft)

    assert result["adjacent_numeric_citation_count"] == 1
    assert result["issues"]
