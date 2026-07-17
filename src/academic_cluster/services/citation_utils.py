"""
Citation utilities for academic review writing.

Handles citation validation, renumbering, and reference list generation.
"""

from __future__ import annotations

import re
from typing import Any

_REVISION_COMMENTARY_MARKERS = (
    "本修改",
    "本次修改",
    "以上修改",
    "修改严格",
    "严格遵循",
    "用户规则",
    "仅修改当前段落",
    "保留所有原始引用",
    "不新增",
    "消除",
    "改用数据支撑",
    "保持段落独立",
    "与前后段落形成递进",
    "revision",
    "revise",
)

_FULLWIDTH_META_BLOCK_RE = re.compile(
    r"[（(]\s*(?:注|说明|备注|Note|Revision note|修改说明)\s*[:：][^（）()]{0,1200}[）)]",
    re.IGNORECASE | re.DOTALL,
)

_INLINE_REVISION_SENTENCE_RE = re.compile(
    r"(?:(?:^|[\n。！？.!?])\s*)"
    r"(?:本次?修改|本修改|以上修改|该修改|修改后文本|修订说明|说明)"
    r"[^。！？\n]{0,500}"
    r"(?:严格遵循|用户规则|仅修改|保留所有|不新增|消除|改用|整合|补充)"
    r"[^。！？\n]*(?:[。！？.!?]|$)",
    re.IGNORECASE,
)
_THINK_BLOCK_RE = re.compile(
    r"<think\b[^>]*>.*?(?:</think>|$)", re.IGNORECASE | re.DOTALL
)


def _looks_like_revision_commentary(block: str) -> bool:
    lowered = block.lower()
    hits = sum(
        1 for marker in _REVISION_COMMENTARY_MARKERS if marker.lower() in lowered
    )
    return hits >= 2


def strip_revision_commentary(content: str) -> str:
    """Remove visible revision notes accidentally emitted into section bodies."""
    if not content:
        return ""

    content = _THINK_BLOCK_RE.sub("", content)

    def _drop_meta_block(match: re.Match[str]) -> str:
        block = str(match.group(0))
        return "" if _looks_like_revision_commentary(block) else block

    content = _FULLWIDTH_META_BLOCK_RE.sub(_drop_meta_block, content)
    content = _INLINE_REVISION_SENTENCE_RE.sub("", content)

    cleaned_lines: list[str] = []
    skip_continuation = False
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append(line)
            skip_continuation = False
            continue
        if _looks_like_revision_commentary(stripped):
            skip_continuation = stripped.count("（") > stripped.count(
                "）"
            ) or stripped.count("(") > stripped.count(")")
            continue
        if skip_continuation:
            if "）" in stripped or ")" in stripped:
                skip_continuation = False
            continue
        cleaned_lines.append(line)

    content = "\n".join(cleaned_lines)
    content = re.sub(r"[ \t]{2,}", " ", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


# Matches [N] or [N,M,K] or [N-M] style citation tokens inside markdown.
# We exclude year-like brackets [1800-2200] via a negative lookahead in
# the caller rather than here, because the regex itself is intentionally
# greedy to capture any bracket content that *might* be a citation.
_CITATION_RE = re.compile(r"\[([0-9,\s;–—、，·\-]+)\]")

# Matches a bare year-like bracket such as [2024] or [2020-2023].
_YEAR_BRACKET_RE = re.compile(r"\[(\d{4})(?:\s*[-–—]\s*(\d{4}))?\]")

_PAREN_NUMERIC_CITATION_RE = re.compile(
    r"[（(]\s*((?:\[[0-9,\s;–—、，·\-]+\]\s*)+)\s*[）)]"
)
_PAREN_PLACEHOLDER_CITATION_RE = re.compile(
    r"[（(]\s*(?:\[[A-Za-z][A-Za-z0-9,\s;、，]*\]\s*)+\s*[）)]"
)
_PLACEHOLDER_CITATION_RE = re.compile(r"\[[A-Za-z][A-Za-z0-9,\s;、，]*\]")

# Pattern for the References heading (## or #) and everything after it.
_REF_HEADING_RE = re.compile(
    r"^#{1,3}\s*(?:references?|bibliography)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


# ---------------------------------------------------------------------------
# 1. parse_citation_numbers
# ---------------------------------------------------------------------------


def parse_citation_numbers(text: str) -> list[int]:
    """Parse citation content like ``"1, 3-5, 7"`` into ``[1, 3, 4, 5, 7]``.

    Supported separators: comma, semicolon, CJK comma (U+3001 / U+FF0C),
    middle dot (U+00B7), whitespace.
    Supported range delimiters: hyphen-minus, en-dash (U+2013), em-dash (U+2014).

    Returns an empty list if *text* looks like a year (1800-2200) or is empty.
    """
    text = text.strip()
    if not text:
        return []

    # Quick bail-out: if the entire text is a single 4-digit year in the
    # 1800-2200 range, or a year range, treat it as NOT a citation.
    year_match = _YEAR_BRACKET_RE.fullmatch(f"[{text}]")
    if year_match:
        return []

    # Normalise separators to commas for uniform splitting.
    normalised = re.sub(r"[;、，·]+", ",", text)
    # Normalise range delimiters to a standard hyphen.
    normalised = re.sub(r"[–—]", "-", normalised)

    # Split by comma (possibly surrounded by whitespace).
    parts: list[str] = [p.strip() for p in normalised.split(",") if p.strip()]

    numbers: list[int] = []
    for part in parts:
        # Is it a range? e.g. "3-5"
        range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            # Reject year-like ranges.
            if 1800 <= start <= 2200 and 1800 <= end <= 2200:
                continue
            if start > end:
                start, end = end, start
            span = end - start + 1
            if span > 20:
                # Unreasonably large range – skip.
                continue
            numbers.extend(range(start, end + 1))
        elif part.isdigit():
            val = int(part)
            # Skip year-like single values.
            if 1800 <= val <= 2200:
                continue
            numbers.append(val)
        # else: ignore non-numeric fragments silently

    return numbers


# ---------------------------------------------------------------------------
# 2. renumber_citations_by_first_use
# ---------------------------------------------------------------------------


def renumber_citations_by_first_use(
    markdown: str,
    paper_map: dict[Any, dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Renumber citations sequentially by first appearance.

    Parameters
    ----------
    markdown : str
        The review markdown text containing ``[N]`` citation tokens.
    paper_map : dict
        Mapping from **original** citation number (int or str) to a dict
        with keys: ``paper_id``, ``title``, ``authors``, ``venue``,
        ``year``, ``doi``.

    Returns
    -------
    tuple[str, list[dict]]
        ``(renumbered_markdown, reference_mappings)`` where each mapping
        dict contains ``new_number``, ``original_number``, and the paper
        metadata fields.
    """
    first_appearance: dict[int, int] = {}  # original -> new
    resolved_papers: dict[int, dict[str, Any]] = {}
    next_num = 1

    def _resolve_paper(orig: int) -> dict[str, Any]:
        if orig in resolved_papers:
            return resolved_papers[orig]
        paper_info = paper_map.get(orig, paper_map.get(str(orig)))
        if not isinstance(paper_info, dict):
            raise ValueError(f"unknown citation number: {orig}")
        resolved_papers[orig] = paper_info
        return paper_info

    def _remap_number(orig: int) -> int:
        nonlocal next_num
        _resolve_paper(orig)
        if orig not in first_appearance:
            first_appearance[orig] = next_num
            next_num += 1
        return first_appearance[orig]

    def _replace_token(match: re.Match[str]) -> str:
        inner = match.group(1)
        # If the inner text is a year, leave it alone.
        if _YEAR_BRACKET_RE.fullmatch(match.group(0)):
            return match.group(0)

        nums = parse_citation_numbers(inner)
        if not nums:
            # Not a real citation – keep original text.
            return match.group(0)

        remapped = [_remap_number(n) for n in nums]
        # Rebuild the bracket content, collapsing to comma-separated.
        return "[" + ",".join(str(n) for n in remapped) + "]"

    renumbered = _CITATION_RE.sub(_replace_token, markdown)

    # Build the reference mapping list in new-number order.
    mappings: list[dict[str, Any]] = []
    for orig, new in sorted(first_appearance.items(), key=lambda kv: kv[1]):
        paper_info = _resolve_paper(orig)
        mappings.append(
            {
                "new_number": new,
                "original_number": orig,
                "paper_id": paper_info.get("paper_id", ""),
                "title": paper_info.get("title", ""),
                "authors": paper_info.get("authors", ""),
                "venue": paper_info.get("venue", ""),
                "year": paper_info.get("year", ""),
                "doi": paper_info.get("doi", ""),
            }
        )

    return renumbered, mappings


def normalize_citation_surface(content: str) -> str:
    """Normalize visible citation shapes to plain numeric [N] tokens.

    LLMs sometimes emit parenthesized citations like ``([11])`` or placeholder
    markers such as ``([x])``. The review renderer and finalizer only accept
    numeric bracket citations, so this function removes the wrapper around real
    citations and deletes non-numeric placeholders.
    """
    if not content:
        return ""

    def _unwrap_numeric_citation(match: re.Match[str]) -> str:
        inner = re.sub(r"\]\s*\[", ",", str(match.group(1)).strip())
        return inner

    content = _PAREN_NUMERIC_CITATION_RE.sub(_unwrap_numeric_citation, content)
    content = _PAREN_PLACEHOLDER_CITATION_RE.sub("", content)
    content = _PLACEHOLDER_CITATION_RE.sub("", content)
    content = re.sub(r"（\s*([A-Za-z]{1,3})\s*）", "", content)
    content = re.sub(r"\(\s*([A-Za-z]{1,3})\s*\)", "", content)
    content = re.sub(r"[ \t]{2,}", " ", content)
    content = re.sub(r"\s+([，,。；;：:])", r"\1", content)
    content = re.sub(r"([。！？])([A-Za-z\u4e00-\u9fff])", r"\1 \2", content)
    return content.strip()


# ---------------------------------------------------------------------------
# 6. strip_reference_block
# ---------------------------------------------------------------------------


def strip_reference_block(markdown: str) -> str:
    """Remove ``## References`` heading and everything after it.

    Stops at the next heading of equal or higher level, or end of file.
    The heading itself is removed.  If there is no references block the
    original text is returned unchanged.
    """
    match = _REF_HEADING_RE.search(markdown)
    if match is None:
        return markdown

    start = match.start()
    # Find the next heading at the same or higher level (fewer or equal
    # leading ``#`` characters).
    heading_level = len(match.group(0).lstrip()) - len(
        match.group(0).lstrip().lstrip("#")
    )

    # Search for the next heading after the references heading.
    rest = markdown[match.end() :]
    next_heading = re.search(rf"^#{{{1},{heading_level}}}\s+\S", rest, re.MULTILINE)

    if next_heading is not None:
        match.end() + next_heading.start()
    else:
        len(markdown)

    return markdown[:start].rstrip() + "\n"


# ---------------------------------------------------------------------------
# 6b. strip_section_reference_block
# ---------------------------------------------------------------------------

# Matches reference-like blocks inside a single section: lines starting with
# [N] followed by author/title text, or a "参考文献"/"References" sub-heading.
_SECTION_REF_LINE_RE = re.compile(
    r"^\s*\[\d+\]\s+.+,.+\".+\"," r"",
    re.MULTILINE,
)
_SECTION_REF_HEADING_RE = re.compile(
    r"^#{1,4}\s*(?:references?|bibliography|参考文献|引用文献)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def strip_section_reference_block(content: str) -> str:
    """Remove any inline reference list from a single section's content.

    Handles cases where the LLM appends a ``[N] author, "title", venue, year``
    list at the end of a section despite being told not to.

    Also strips a trailing ``## References`` / ``## 参考文献`` sub-heading
    and everything after it.
    """
    # 1. Strip trailing reference sub-heading and everything after it.
    match = _SECTION_REF_HEADING_RE.search(content)
    if match is not None:
        content = content[: match.start()].rstrip()

    # 2. Strip trailing block of consecutive [N] reference lines.
    lines = content.split("\n")
    # Walk backwards to find where the reference block starts.
    ref_start = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            # Allow blank lines inside the reference block.
            if ref_start == i + 1:
                continue  # trailing blank line
            break
        if _SECTION_REF_LINE_RE.match(stripped):
            ref_start = i
        else:
            break

    if ref_start < len(lines):
        # Remove trailing blank lines before the reference block too.
        while ref_start > 0 and not lines[ref_start - 1].strip():
            ref_start -= 1
        content = "\n".join(lines[:ref_start]).rstrip()

    return content


# ---------------------------------------------------------------------------
# strip_meta_commentary
# ---------------------------------------------------------------------------

# Matches meta-commentary blocks like "（以下为符合要求的学术综述章节正文，约1500字...）"
# or "（总字数：1523字，引用文献...）" at the beginning or end of content.
_META_COMMENTARY_RE = re.compile(
    r"^[（(][^）)]*(?:以下|总字数|字数统计|符合要求|引用文献|参考文献|引用密度|所有引用|未出现|字数达标|字数约|约\d+字|共\d+字)[^）)]*[）)]\s*",
    re.MULTILINE,
)
_META_COMMENTARY_TAIL_RE = re.compile(
    r"\n[（(][^）)]*(?:总字数|字数统计|引用文献|参考文献|引用密度|所有引用|未出现|符合要求|字数达标|字数约|约\d+字|共\d+字)[^）)]*[）)]\s*$",
    re.MULTILINE,
)


def strip_meta_commentary(content: str) -> str:
    """Strip LLM meta-commentary like '（以下为符合要求的学术综述章节正文...）'."""
    content = _META_COMMENTARY_RE.sub("", content)
    content = _META_COMMENTARY_TAIL_RE.sub("", content)
    return content.strip()


# ---------------------------------------------------------------------------
# strip_prompt_leakage
# ---------------------------------------------------------------------------

# Matches prompt leakage blocks like "（注：本节严格遵循以下规范：...）"
_PROMPT_LEAKAGE_RE = re.compile(
    r"（注：[^）]*(?:遵循|规范|引用|禁止|全文|每处|技术比较|争议性|实验数据)[^）]*）",
    re.DOTALL,
)
# Matches trailing numbered list that looks like prompt instructions
_PROMPT_LEAKAGE_LIST_RE = re.compile(
    r"\n\s*\d+\.\s*(?:全文采用|每处引用|技术比较|争议性问题|实验数据|禁止出现).*$",
    re.DOTALL,
)


def strip_prompt_leakage(content: str) -> str:
    """Strip LLM prompt leakage like '（注：本节严格遵循以下规范...）'."""
    content = _PROMPT_LEAKAGE_RE.sub("", content)
    content = _PROMPT_LEAKAGE_LIST_RE.sub("", content)
    return content.strip()


_BODY_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_BODY_LABEL_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"核心问题|研究问题|局限性|局限|限制|不足|结论|总结|未来方向|未来发展|开放问题|"
    r"Limitation|Limitations|Conclusion|Conclusions|Future directions?|Open problems?|Key question"
    r")\s*[:：]\s*",
    re.IGNORECASE | re.MULTILINE,
)
# Descriptive subtitle pattern: standalone long line without sentence-ending punctuation
# Often uses "——" to connect two parts, acts as a section divider
_BODY_DESCRIPTIVE_SUBTITLE_RE = re.compile(
    r"^\s*"
    r"(?:"  # numbered/bulleted prefix patterns
    r"[一二三四五六七八九十]+[、.]\s*"
    r"|（[一二三四五六七八九十]+）\s*"
    r"|\d+[、.]\s*"
    r"|[•●◆▪]\s*"
    r")?"
    r"[一-鿿][一-鿿\w\s，、；：！？（）()《》\-—–…·/和与及或中在的了是对为]"
    r"{15,}"  # at least 15 characters
    r"(?:[——][一-鿿][一-鿿\w\s，、；：！？（）()《》\-—–…·/和与及或中在的了是对为]{5,})?"
    r"\s*$",
    re.MULTILINE,
)


def strip_body_structure_leakage(content: str) -> str:
    """Remove body-only headings and template labels from generated sections."""
    if not content:
        return ""

    def _heading_to_sentence(match: re.Match[str]) -> str:
        heading = str(match.group(1)).strip()
        if not heading:
            return ""
        if heading[-1] not in ".!?。！？；;":
            has_cjk = any("\u4e00" <= char <= "\u9fff" for char in heading)
            heading += "。" if has_cjk else "."
        return heading

    content = _BODY_HEADING_RE.sub(_heading_to_sentence, content)
    content = _BODY_LABEL_PREFIX_RE.sub("", content)
    content = _BODY_DESCRIPTIVE_SUBTITLE_RE.sub("", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()
