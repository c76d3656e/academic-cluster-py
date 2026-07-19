import pytest

from academic_cluster.services.citation_utils import (
    MalformedCitationError,
    normalize_citation_surface,
    renumber_citations_by_first_use,
    strip_body_structure_leakage,
    strip_reference_block,
    strip_revision_commentary,
    strip_section_reference_block,
)


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


def test_full_width_semicolon_citations_are_parsed_and_renumbered():
    renumbered, mappings = renumber_citations_by_first_use(
        "联合证据 [2；1]。",
        {
            1: {"paper_id": "paper-1", "title": "First"},
            2: {"paper_id": "paper-2", "title": "Second"},
        },
    )

    assert renumbered == "联合证据 [1,2]。"
    assert [mapping["original_number"] for mapping in mappings] == [2, 1]


def test_normalize_citation_surface_preserves_code_and_math_regions():
    content = (
        "正文占位符([x])应删除，真实引用([8])应展开。\n\n"
        "```python\n"
        "matrix[x] = refs[1,2]\n"
        "wrapped = ([x])\n"
        "```\n\n"
        "    indented[x] = refs[1,2]\n\n"
        "`inline[x] + refs[1,2] + ([x])`\n\n"
        "$A[x] + B[1,2]$\n\n"
        "$$\nC[x] + D[1,2]\n$$\n\n"
        r"\(E[x] + F[1,2]\)"
        "\n\n"
        r"\[G[x] + H[1,2]\]"
    )

    cleaned = normalize_citation_surface(content)

    assert "正文占位符" in cleaned
    assert "([x])应删除" not in cleaned
    assert "真实引用[8]应展开" in cleaned
    assert "```python\nmatrix[x] = refs[1,2]\nwrapped = ([x])\n```" in cleaned
    assert "    indented[x] = refs[1,2]" in cleaned
    assert "`inline[x] + refs[1,2] + ([x])`" in cleaned
    assert "$A[x] + B[1,2]$" in cleaned
    assert "$$\nC[x] + D[1,2]\n$$" in cleaned
    assert r"\(E[x] + F[1,2]\)" in cleaned
    assert r"\[G[x] + H[1,2]\]" in cleaned


def test_renumber_citations_ignores_code_and_math_first_appearances():
    markdown = (
        "```text\nprotected [2]\n```\n"
        "    indented [1,2]\n"
        "`inline [1]` $math[2]$ $$block[1,2]$$ "
        r"\(latex[2]\) \[display[1,2]\]"
        "\n"
        "Visible second paper [2], then first paper [1]."
    )
    paper_map = {
        1: {
            "paper_id": "paper-1",
            "title": "First",
            "url": "https://example.org/paper-1",
        },
        2: {"paper_id": "paper-2", "title": "Second"},
    }

    renumbered, mappings = renumber_citations_by_first_use(markdown, paper_map)

    assert "```text\nprotected [2]\n```" in renumbered
    assert "    indented [1,2]" in renumbered
    assert "`inline [1]`" in renumbered
    assert "$math[2]$" in renumbered
    assert "$$block[1,2]$$" in renumbered
    assert r"\(latex[2]\)" in renumbered
    assert r"\[display[1,2]\]" in renumbered
    assert renumbered.endswith("Visible second paper [1], then first paper [2].")
    assert [mapping["original_number"] for mapping in mappings] == [2, 1]
    assert mappings[1]["url"] == "https://example.org/paper-1"


def test_reference_block_strippers_ignore_headings_inside_fenced_code():
    content = (
        "Body cites [1].\n\n"
        "```markdown\n"
        "## References\n"
        '[1] Example, "Code only", 2024\n'
        "```"
    )

    assert strip_reference_block(content) == content
    assert strip_section_reference_block(content) == content


def test_strip_reference_block_preserves_a_following_appendix():
    content = (
        "# Review\n\nBody cites [1].\n\n"
        "## References\n\n[1] Canonical source.\n\n"
        "## Appendix\n\nSupplementary method."
    )

    cleaned = strip_reference_block(content)

    assert (
        cleaned == "# Review\n\nBody cites [1].\n\n## Appendix\n\nSupplementary method."
    )


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_renumber_citations_preserves_crlf_fenced_code(fence: str):
    markdown = (
        f"{fence}text\r\nprotected [2]\r\n{fence}\r\n"
        "Visible second paper [2], then first paper [1]."
    )
    paper_map = {
        1: {"paper_id": "paper-1", "title": "First"},
        2: {"paper_id": "paper-2", "title": "Second"},
    }

    renumbered, mappings = renumber_citations_by_first_use(markdown, paper_map)

    assert f"{fence}text\r\nprotected [2]\r\n{fence}" in renumbered
    assert renumbered.endswith("Visible second paper [1], then first paper [2].")
    assert [mapping["original_number"] for mapping in mappings] == [2, 1]


def test_renumber_citations_does_not_pair_currency_with_inline_math():
    markdown = (
        "Cost was $1,000,000 [2] and $5m [1]. "
        "Formula $x[99]$ and visible [3]. Paired math $5 million$ stays protected."
    )
    paper_map = {
        1: {"paper_id": "paper-1", "title": "First"},
        2: {"paper_id": "paper-2", "title": "Second"},
        3: {"paper_id": "paper-3", "title": "Third"},
    }

    renumbered, mappings = renumber_citations_by_first_use(markdown, paper_map)

    assert "Cost was $1,000,000 [1] and $5m [2]." in renumbered
    assert "Formula $x[99]$" in renumbered
    assert renumbered.endswith("visible [3]. Paired math $5 million$ stays protected.")
    assert [mapping["original_number"] for mapping in mappings] == [2, 1, 3]


def test_renumber_citations_supports_common_currency_surfaces():
    markdown = (
        "Rates were $5/GB [2], $-10 [1], $.50 [3], $2\u202f000 [4], and $5mm [5]."
    )
    paper_map = {
        number: {"paper_id": f"paper-{number}", "title": str(number)}
        for number in range(1, 6)
    }

    renumbered, mappings = renumber_citations_by_first_use(markdown, paper_map)

    assert renumbered == (
        "Rates were $5/GB [1], $-10 [2], $.50 [3], $2\u202f000 [4], and $5mm [5]."
    )
    assert [mapping["original_number"] for mapping in mappings] == [2, 1, 3, 4, 5]


def test_renumber_citations_preserves_currency_like_numeric_math():
    markdown = (
        "Formula $5[99]$ and $5 million [98]$ remain protected; "
        "visible second [2], then first [1]."
    )
    paper_map = {
        1: {"paper_id": "paper-1", "title": "First"},
        2: {"paper_id": "paper-2", "title": "Second"},
    }

    renumbered, mappings = renumber_citations_by_first_use(markdown, paper_map)

    assert "$5[99]$" in renumbered
    assert "$5 million [98]$" in renumbered
    assert renumbered.endswith("visible second [1], then first [2].")
    assert [mapping["original_number"] for mapping in mappings] == [2, 1]


@pytest.mark.parametrize(
    "token,pattern",
    [
        ("3-1", "ascending"),
        ("2-50", "exceeds"),
        ("1-", "malformed"),
    ],
)
def test_renumber_citations_rejects_malformed_ranges(token: str, pattern: str):
    with pytest.raises(MalformedCitationError, match=pattern):
        renumber_citations_by_first_use(
            f"Unsupported range [{token}].",
            {1: {"paper_id": "paper-1"}},
        )


def test_four_digit_values_outside_year_range_are_not_year_brackets():
    with pytest.raises(ValueError, match="unknown citation number: 9999"):
        renumber_citations_by_first_use(
            "Unsupported citation [9999].",
            {1: {"paper_id": "paper-1"}},
        )


def test_strip_section_reference_block_removes_unquoted_bibliography_lines():
    content = (
        "Body cites [1].\n\n"
        "[1] Smith. Paper title. Journal, 2024.\n"
        "[2] J. Doe, Another paper title, Journal, 2023.\n"
        "[3] 王伟, 李明. 中文标题. 期刊, 2022."
    )

    assert strip_section_reference_block(content) == "Body cites [1]."


def test_strip_section_reference_block_preserves_narrative_citation_lines():
    content = (
        "Body cites [1].\n\n[1] Smith proposed the method in 2024.\n"
        "[2] 王伟提出了方法，发表于2024年。\n"
        "[3] Smith. Their method improved in 2024."
    )

    assert strip_section_reference_block(content) == content
