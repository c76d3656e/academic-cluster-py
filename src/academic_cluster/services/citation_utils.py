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
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?(?:</think>|$)", re.IGNORECASE | re.DOTALL)


def _looks_like_revision_commentary(block: str) -> bool:
    lowered = block.lower()
    hits = sum(1 for marker in _REVISION_COMMENTARY_MARKERS if marker.lower() in lowered)
    return hits >= 2


def strip_revision_commentary(content: str) -> str:
    """Remove visible revision notes accidentally emitted into section bodies."""
    if not content:
        return ""

    content = _THINK_BLOCK_RE.sub("", content)

    def _drop_meta_block(match: re.Match) -> str:
        block = match.group(0)
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
            skip_continuation = (
                stripped.count("（") > stripped.count("）")
                or stripped.count("(") > stripped.count(")")
            )
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


_PRECISE_METRIC_RE = re.compile(
    r"(?:[A-Za-zα-ωΑ-Ω]\s*=\s*)?-?\d+(?:\.\d+)?\s*(?:%|％|倍|秒|ms|毫秒|分钟|次/分钟|次/小时)"
    r"|(?:D|F|γ|Gamma|gamma)\s*=\s*-?\d+(?:\.\d+)?",
    re.IGNORECASE,
)


def _evidence_metric_text(evidence_cards: list[dict] | None) -> str:
    if not evidence_cards:
        return ""
    fields = ("claim", "evidence_span", "metric", "method", "limitation", "paper_title", "title")
    parts: list[str] = []
    for card in evidence_cards:
        if not isinstance(card, dict):
            continue
        for field in fields:
            value = card.get(field)
            if value is None:
                continue
            parts.append(str(value))
    return "\n".join(parts)


def strip_unsupported_precise_metrics(
    content: str,
    evidence_cards: list[dict] | None,
) -> str:
    """Drop sentences containing precise metrics absent from section evidence cards.

    This intentionally targets strong quantitative claims only. General years,
    citation numbers, and non-metric integers are left untouched.
    """
    if not content:
        return ""
    evidence_text = _evidence_metric_text(evidence_cards)
    if not evidence_text:
        return content

    parts = re.split(r"([。！？!?]\s*)", content)
    kept: list[str] = []
    dropped = False
    for idx in range(0, len(parts), 2):
        sentence = parts[idx]
        punctuation = parts[idx + 1] if idx + 1 < len(parts) else ""
        if not sentence:
            if punctuation:
                kept.append(punctuation)
            continue
        metrics = [match.group(0).strip() for match in _PRECISE_METRIC_RE.finditer(sentence)]
        unsupported = [
            metric for metric in metrics
            if metric and metric not in evidence_text and metric.replace("％", "%") not in evidence_text
        ]
        if unsupported:
            # 如果句子有引用标记 [N]，说明指标来自被引文献，保留
            if re.search(r"\[\d+\]", sentence):
                kept.append(sentence + punctuation)
            else:
                dropped = True
                continue
        else:
            kept.append(sentence + punctuation)

    cleaned = "".join(kept)
    if dropped:
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()

# Matches [N] or [N,M,K] or [N-M] style citation tokens inside markdown.
# We exclude year-like brackets [1800-2200] via a negative lookahead in
# the caller rather than here, because the regex itself is intentionally
# greedy to capture any bracket content that *might* be a citation.
_CITATION_RE = re.compile(r"\[([0-9,\s;–—、，·\-]+)\]")

# Matches a bare year-like bracket such as [2024] or [2020-2023].
_YEAR_BRACKET_RE = re.compile(r"\[(\d{4})(?:\s*[-–—]\s*(\d{4}))?\]")

# Matches UUID-style paper_id in brackets, e.g. [433802d1-ebf8-49f7-8efc-0183ef0170b8]
_UUID_CITATION_RE = re.compile(r"\[([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]")
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
    paper_map: dict,
) -> tuple[str, list[dict]]:
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
    next_num = 1

    def _remap_number(orig: int) -> int:
        nonlocal next_num
        if orig not in first_appearance:
            first_appearance[orig] = next_num
            next_num += 1
        return first_appearance[orig]

    def _replace_token(match: re.Match) -> str:
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
    mappings: list[dict] = []
    for orig, new in sorted(first_appearance.items(), key=lambda kv: kv[1]):
        paper_info = paper_map.get(orig, paper_map.get(str(orig), {}))
        mappings.append({
            "new_number": new,
            "original_number": orig,
            "paper_id": paper_info.get("paper_id", ""),
            "title": paper_info.get("title", ""),
            "authors": paper_info.get("authors", ""),
            "venue": paper_info.get("venue", ""),
            "year": paper_info.get("year", ""),
            "doi": paper_info.get("doi", ""),
        })

    return renumbered, mappings


# ---------------------------------------------------------------------------
# 3. validate_citations
# ---------------------------------------------------------------------------

def validate_citations(
    markdown: str,
    valid_paper_count: int,
    allowed_indices: set[int] | None = None,
) -> dict[str, Any]:
    """Validate citations in *markdown*.

    Parameters
    ----------
    markdown : str
        Text containing ``[N]`` citation tokens.
    valid_paper_count : int
        Highest valid citation number (1-based).  Numbers > this are
        considered out-of-range.
    allowed_indices : set[int] | None
        If provided, citation numbers not in this set are flagged as
        ``outside_plan`` even if they are in range.

    Returns
    -------
    dict
        ``valid_count``, ``invalid_count``, ``invalid_numbers``,
        ``out_of_range``, ``outside_plan``.
    """
    all_numbers: list[int] = []
    for match in _CITATION_RE.finditer(markdown):
        # Skip year-like brackets.
        if _YEAR_BRACKET_RE.fullmatch(match.group(0)):
            continue
        nums = parse_citation_numbers(match.group(1))
        all_numbers.extend(nums)

    unique_nums = set(all_numbers)

    out_of_range: list[int] = sorted(n for n in unique_nums if n > valid_paper_count or n < 1)
    outside_plan: list[int] = []
    if allowed_indices is not None:
        outside_plan = sorted(n for n in unique_nums if n not in allowed_indices and n not in out_of_range)

    invalid_numbers_set: set[int] = set(out_of_range)
    if allowed_indices is not None:
        invalid_numbers_set.update(outside_plan)

    invalid_numbers = sorted(invalid_numbers_set)
    # Count how many citation *tokens* contain at least one invalid number.
    invalid_count = 0
    for match in _CITATION_RE.finditer(markdown):
        if _YEAR_BRACKET_RE.fullmatch(match.group(0)):
            continue
        nums = parse_citation_numbers(match.group(1))
        if any(n in invalid_numbers_set for n in nums):
            invalid_count += 1

    return {
        "valid_count": len(all_numbers) - sum(1 for n in all_numbers if n in invalid_numbers_set),
        "invalid_count": invalid_count,
        "invalid_numbers": invalid_numbers,
        "out_of_range": out_of_range,
        "outside_plan": outside_plan,
    }


# ---------------------------------------------------------------------------
# 4. strip_invalid_citations
# ---------------------------------------------------------------------------

def strip_invalid_citations(
    markdown: str,
    invalid_numbers: set[int],
) -> str:
    """Remove invalid citation numbers from ``[N,M,K]`` tokens.

    If a token contains a mix of valid and invalid numbers, only the valid
    ones are kept.  If all numbers in a token are invalid, the entire
    ``[...]`` block is removed.  Year brackets like ``[2024]`` are
    preserved.
    """
    def _clean_token(match: re.Match) -> str:
        original = match.group(0)
        # Preserve year brackets.
        if _YEAR_BRACKET_RE.fullmatch(original):
            return original

        nums = parse_citation_numbers(match.group(1))
        if not nums:
            return original

        remaining = [n for n in nums if n not in invalid_numbers]
        if not remaining:
            # All invalid – remove the entire token.
            return ""
        # Rebuild with only valid numbers.
        return "[" + ",".join(str(n) for n in remaining) + "]"

    return _CITATION_RE.sub(_clean_token, markdown)


# ---------------------------------------------------------------------------
# 4b. replace_uuid_citations
# ---------------------------------------------------------------------------


def replace_uuid_citations(
    markdown: str,
    paper_id_to_number: dict[str, int],
) -> str:
    """Replace UUID-style citations like [433802d1-...] with proper [N] numbers.

    Parameters
    ----------
    markdown : str
        The review markdown text that may contain UUID citations.
    paper_id_to_number : dict[str, int]
        Mapping from paper_id (UUID string) to citation number (int).

    Returns
    -------
    str
        Markdown with UUID citations replaced by [N] numbers.
    """
    def _replace_uuid(match: re.Match) -> str:
        uuid = match.group(1)
        num = paper_id_to_number.get(uuid)
        if num is not None:
            return f"[{num}]"
        # Unknown UUID – remove the citation entirely
        return ""

    return _UUID_CITATION_RE.sub(_replace_uuid, markdown)


def normalize_citation_surface(content: str) -> str:
    """Normalize visible citation shapes to plain numeric [N] tokens.

    LLMs sometimes emit parenthesized citations like ``([11])`` or placeholder
    markers such as ``([x])``. The review renderer and finalizer only accept
    numeric bracket citations, so this function removes the wrapper around real
    citations and deletes non-numeric placeholders.
    """
    if not content:
        return ""

    def _unwrap_numeric_citation(match: re.Match) -> str:
        inner = re.sub(r"\]\s*\[", ",", match.group(1).strip())
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
# 5. render_reference_list
# ---------------------------------------------------------------------------

def render_reference_list(
    papers: list[dict],
    mappings: list[dict] | None = None,
) -> str:
    """Render a numbered reference list in IEEE format.

    Parameters
    ----------
    papers : list[dict]
        Each dict should have ``authors``, ``title``, ``venue``, ``year``,
        ``doi`` keys (values may be empty strings).
    mappings : list[dict] | None
        If provided, each dict must have a ``new_number`` key.  The list
        length must match *papers*.  Otherwise papers are numbered 1..N
        in list order.

    Returns
    -------
    str
        The reference list as a multi-line string, each line starting
        with ``[N]``.
    """
    lines: list[str] = []
    for idx, paper in enumerate(papers):
        if mappings is not None and idx < len(mappings):
            num = mappings[idx].get("new_number", idx + 1)
        else:
            num = idx + 1

        raw_authors = paper.get("authors") or ""
        if isinstance(raw_authors, list):
            # DB stores authors as [{"id": ..., "name": ...}, ...]
            authors = ", ".join(
                a.get("name", str(a)) if isinstance(a, dict) else str(a)
                for a in raw_authors
            )
        else:
            authors = str(raw_authors).strip()

        title = str(paper.get("title") or "").strip()
        venue = str(paper.get("journal") or paper.get("venue") or "").strip()
        year = str(paper.get("year") or "").strip()
        doi = str(paper.get("doi") or "").strip()

        # Truncate author list: first 3 authors + "et al." if more.
        if authors:
            author_parts = [a.strip() for a in re.split(r"[;]", authors) if a.strip()]
            # If no semicolons, try comma-split but be conservative
            # (author names often contain commas).
            if len(author_parts) <= 1:
                author_parts = [a.strip() for a in re.split(r",\s*(?=[A-Z])", authors) if a.strip()]
            if len(author_parts) > 3:
                authors = ", ".join(author_parts[:3]) + " et al."
            else:
                authors = ", ".join(author_parts)

        parts: list[str] = [f"[{num}]"]
        if authors:
            parts.append(f"{authors},")
        if title:
            parts.append(f'"{title}",')
        if venue:
            parts.append(f"{venue},")
        if year:
            parts.append(f"{year}.")
        if doi:
            parts.append(f"DOI:{doi}.")

        line = " ".join(parts)
        # Clean up double punctuation / trailing spaces.
        line = re.sub(r"\.\.", ".", line)
        line = re.sub(r",\.", ".", line)
        line = line.rstrip() + "\n"
        lines.append(line)

    return "".join(lines)


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
    heading_level = len(match.group(0).lstrip()) - len(match.group(0).lstrip().lstrip("#"))

    # Search for the next heading after the references heading.
    rest = markdown[match.end():]
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
# 6c. clean_filler_phrases
# ---------------------------------------------------------------------------

# Filler phrases that add no analytical value.  Each entry is (pattern, replacement).
_FILLER_PATTERNS: list[tuple[str, str]] = [
    ("从方法论角度来看，", ""),
    ("从方法论角度", ""),
    ("从技术演进角度来看，", ""),
    ("从技术演进角度", ""),
    ("从理论角度来看，", ""),
    ("从理论角度", ""),
    ("从应用角度来看，", ""),
    ("从应用角度", ""),
    ("从宏观层面来看，", ""),
    ("从宏观层面来看", ""),
    ("从宏观层面", ""),
    ("从微观层面来看，", ""),
    ("从微观层面来看", ""),
    ("从微观层面", ""),
    ("在理论层面上，", ""),
    ("在理论层面上", ""),
    ("在理论层面", ""),
    ("在实践层面上，", ""),
    ("在实践层面上", ""),
    ("在实践层面", ""),
    ("在技术层面上，", ""),
    ("在技术层面上", ""),
    ("在技术层面", ""),
    ("在方法层面上，", ""),
    ("在方法层面上", ""),
    ("在方法层面", ""),
    ("在应用层面上，", ""),
    ("在应用层面上", ""),
    ("在应用层面", ""),
    ("在模型层面上，", ""),
    ("在模型层面上", ""),
    ("在模型层面", ""),
    ("在数据层面上，", ""),
    ("在数据层面上", ""),
    ("在数据层面", ""),
    ("在性能层面上，", ""),
    ("在性能层面上", ""),
    ("在性能层面", ""),
    ("在效率层面上，", ""),
    ("在效率层面上", ""),
    ("在效率层面", ""),
    ("在架构层面上，", ""),
    ("在架构层面上", ""),
    ("在架构层面", ""),
    ("在算法层面上，", ""),
    ("在算法层面上", ""),
    ("在算法层面", ""),
    ("在系统层面上，", ""),
    ("在系统层面上", ""),
    ("在系统层面", ""),
]


def clean_filler_phrases(content: str) -> str:
    """Remove academic filler phrases that add no analytical value."""
    for pattern, replacement in _FILLER_PATTERNS:
        content = content.replace(pattern, replacement)
    # Clean up orphaned punctuation after filler removal (e.g. "，该模型" → "该模型").
    content = re.sub(r"^[，,、；;：:]+", "", content, flags=re.MULTILINE)
    # Clean up orphaned punctuation after sentence-ending marks (e.g. "。，" → "。").
    content = re.sub(r"([。！？])[，,、；;]+", r"\1", content)
    # Clean up double spaces or leading/trailing whitespace artifacts.
    content = re.sub(r"[ \t]{2,}", " ", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


# ---------------------------------------------------------------------------
# strip_author_year_citations
# ---------------------------------------------------------------------------

# Matches author-year style citations like (Friedman, 2024), (Smith et al., 2023),
# (Zhang & Li, 2022), (Wang et al., 2021; Li et al., 2022)
_AUTHOR_YEAR_CITATION_RE = re.compile(
    r"[（(]"
    r"[A-Z][a-z]+(?:\s+(?:et\s+al\.?|&\s+[A-Z][a-z]+))?"
    r"(?:\s*[,;]\s*[A-Z][a-z]+(?:\s+(?:et\s+al\.?|&\s+[A-Z][a-z]+))?)*"
    r"\s*,\s*\d{4}(?:\s*[;,]\s*\d{4})*"
    r"[）)]"
)


def strip_author_year_citations(content: str) -> str:
    """Remove author-year style citations like (Friedman, 2024) that violate [N] format."""
    return _AUTHOR_YEAR_CITATION_RE.sub("", content)


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


def is_primarily_chinese(content: str, threshold: float = 0.3) -> bool:
    """Check if content is primarily Chinese. Returns True if CJK chars > threshold of total non-space chars."""
    if not content:
        return True
    non_space = [c for c in content if not c.isspace()]
    if not non_space:
        return True
    cjk_count = sum(1 for c in non_space if "一" <= c <= "鿿")
    return cjk_count / len(non_space) >= threshold


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


def strip_body_structure_leakage(content: str) -> str:
    """Remove body-only headings and template labels from generated sections."""
    if not content:
        return ""

    def _heading_to_sentence(match: re.Match) -> str:
        heading = match.group(1).strip()
        if not heading:
            return ""
        if heading[-1] not in ".!?。！？；;":
            has_cjk = any("\u4e00" <= char <= "\u9fff" for char in heading)
            heading += "。" if has_cjk else "."
        return heading

    content = _BODY_HEADING_RE.sub(_heading_to_sentence, content)
    content = _BODY_LABEL_PREFIX_RE.sub("", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()
