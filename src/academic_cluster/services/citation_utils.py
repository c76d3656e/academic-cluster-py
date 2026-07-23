"""
Citation utilities for academic review writing.

Handles citation validation, renumbering, and reference list generation.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
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
_CITATION_RE = re.compile(r"\[([0-9,\s;；–—、，·\-]+)\]")

# Matches the shape of a bare year-like bracket. Numeric bounds are enforced by
# ``_is_year_bracket`` so arbitrary four-digit citations cannot bypass checks.
_YEAR_BRACKET_RE = re.compile(r"\[(\d{4})(?:\s*[-–—]\s*(\d{4}))?\]")
_MIN_PUBLICATION_YEAR = 1800
_MAX_PUBLICATION_YEAR = 2200
_MAX_CITATION_RANGE_SPAN = 20

_PAREN_NUMERIC_CITATION_RE = re.compile(
    r"[（(]\s*((?:\[[0-9,\s;；–—、，·\-]+\]\s*)+)\s*[）)]"
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

_FENCE_OPEN_RE = re.compile(
    r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})[^\r\n]*(?:\r?\n|$)",
    re.MULTILINE,
)
_INDENTED_CODE_LINE_RE = re.compile(r"^(?: {4}|\t).*?(?:\n|$)", re.MULTILINE)
_CURRENCY_AMOUNT_RE = re.compile(
    r"-?(?:\d{1,3}(?:[,\u00a0\u202f]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
)
_CURRENCY_CITATION_RE = re.compile(r"\s*\[\d+(?:\s*(?:[,;、，·；\s]|[-–—])\s*\d+)*\]")
_CURRENCY_AFTER_AMOUNT_RE = re.compile(
    r"(?:"
    r"\s*usd\b"
    r"|\s+(?:us\s+dollars?|dollars?|million|billion|trillion)\b"
    r"|\s*(?:k|m|mn|mm|b|bn|t)(?=[\s.,;:!?，。；：！？\[]|$)"
    r"|\s*/[a-z][a-z0-9._-]*(?=[\s.,;:!?，。；：！？\[]|$)"
    r"|\s*\[\d+(?:\s*(?:[,;、，·；\s]|[-–—])\s*\d+)*\]"
    r"|\s*(?:美元|美金|元)"
    r"|(?=[,.;:!?，。；：！？](?:\s|$))"
    r"|$"
    r")",
    re.IGNORECASE,
)


def _has_immediate_math_close(content: str, index: int, end: int) -> bool:
    """Return whether optional citation suffixes end at a closing dollar."""

    cursor = index
    while cursor < end:
        citation = _CURRENCY_CITATION_RE.match(content, cursor, end)
        if citation is None:
            break
        cursor = citation.end()
    return cursor < end and content[cursor] == "$"


def _is_escaped(content: str, index: int) -> bool:
    """Return whether the character at ``index`` is preceded by odd slashes."""

    slash_count = 0
    cursor = index - 1
    while cursor >= 0 and content[cursor] == "\\":
        slash_count += 1
        cursor -= 1
    return slash_count % 2 == 1


def _run_length(content: str, index: int, character: str, end: int) -> int:
    cursor = index
    while cursor < end and content[cursor] == character:
        cursor += 1
    return cursor - index


def _find_backtick_close(
    content: str,
    start: int,
    run_length: int,
    end: int,
) -> int | None:
    cursor = start
    while cursor < end:
        if content[cursor] != "`":
            cursor += 1
            continue
        run = _run_length(content, cursor, "`", end)
        if run == run_length and not _is_escaped(content, cursor):
            return cursor
        cursor += run
    return None


def _find_dollar_close(
    content: str,
    start: int,
    delimiter_length: int,
    end: int,
) -> int | None:
    cursor = start
    while cursor < end:
        if content[cursor] != "$":
            cursor += 1
            continue
        run = _run_length(content, cursor, "$", end)
        if (
            run == delimiter_length
            and not _is_escaped(content, cursor)
            and not (
                delimiter_length == 1 and cursor > start and content[cursor - 1] == "$"
            )
        ):
            if delimiter_length != 1:
                return cursor

            # Match remark-math's conservative single-dollar boundaries. A
            # closing delimiter cannot follow whitespace. If an otherwise
            # valid opener appears before a close, abandon the earlier pair;
            # this prevents ``$5 million ... $x$`` from swallowing prose.
            previous = content[cursor - 1] if cursor > 0 else ""
            following = content[cursor + 1] if cursor + 1 < end else ""
            can_close = bool(previous and not previous.isspace())
            can_open = bool(following and not following.isspace())
            if can_close:
                return cursor
            if can_open:
                return None
        cursor += run
    return None


def _looks_like_currency_dollar(content: str, index: int, end: int) -> bool:
    """Return whether a single dollar starts a likely currency amount.

    The Markdown math grammar cannot distinguish every monetary value from an
    equation beginning with a number. We only classify common amount surfaces
    (``$5 million``, ``$5 [1]``, ``$5 USD`` and punctuation/end-of-sentence
    forms) as currency; algebraic forms such as ``$5 + x$`` remain protected.
    """

    if index + 1 >= end:
        return False
    amount = _CURRENCY_AMOUNT_RE.match(content, index + 1, end)
    if amount is None:
        return False
    after = amount.end()
    if _has_immediate_math_close(content, after, end):
        return False
    suffix = _CURRENCY_AFTER_AMOUNT_RE.match(content, after, end)
    if suffix is None:
        return False
    return not _has_immediate_math_close(content, suffix.end(), end)


def _find_sequence_close(
    content: str,
    start: int,
    delimiter: str,
    end: int,
) -> int | None:
    cursor = content.find(delimiter, start, end)
    while cursor >= 0:
        if not _is_escaped(content, cursor):
            return cursor
        cursor = content.find(delimiter, cursor + len(delimiter), end)
    return None


def _scan_inline_protected_ranges(
    content: str,
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    """Find inline code and common math delimiters in one un-fenced span."""

    ranges: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        if _is_escaped(content, cursor):
            cursor += 1
            continue

        if content[cursor] == "`":
            run_length = _run_length(content, cursor, "`", end)
            close = _find_backtick_close(content, cursor + run_length, run_length, end)
            if close is not None:
                ranges.append((cursor, close + run_length))
                cursor = close + run_length
                continue
            cursor += run_length
            continue

        if content.startswith("$$", cursor):
            if _run_length(content, cursor, "$", end) == 2:
                close = _find_dollar_close(content, cursor + 2, 2, end)
                if close is not None:
                    ranges.append((cursor, close + 2))
                    cursor = close + 2
                    continue
            cursor += 2
            continue

        if content[cursor] == "$":
            if _run_length(content, cursor, "$", end) == 1:
                if _looks_like_currency_dollar(content, cursor, end):
                    cursor += 1
                    continue
                following = content[cursor + 1] if cursor + 1 < end else ""
                close = (
                    _find_dollar_close(content, cursor + 1, 1, end)
                    if following and not following.isspace()
                    else None
                )
                if close is not None and "\n" not in content[cursor + 1 : close]:
                    ranges.append((cursor, close + 1))
                    cursor = close + 1
                    continue
            cursor += 1
            continue

        if content.startswith(r"\(", cursor):
            close = _find_sequence_close(content, cursor + 2, r"\)", end)
            if close is not None:
                ranges.append((cursor, close + 2))
                cursor = close + 2
                continue

        if content.startswith(r"\[", cursor):
            close = _find_sequence_close(content, cursor + 2, r"\]", end)
            if close is not None:
                ranges.append((cursor, close + 2))
                cursor = close + 2
                continue

        cursor += 1

    return ranges


def _protected_markdown_ranges(content: str) -> list[tuple[int, int]]:
    """Return fenced-code, inline-code, and math ranges in source order."""

    fences: list[tuple[int, int]] = []
    for opening in _FENCE_OPEN_RE.finditer(content):
        if fences and opening.start() < fences[-1][1]:
            continue
        fence = opening.group("fence")
        assert fence is not None
        character = fence[0]
        length = len(fence)
        closing_re = re.compile(
            rf"^[ \t]{{0,3}}{re.escape(character)}{{{length},}}[ \t]*(?:\r?\n|$)",
            re.MULTILINE,
        )
        closing = closing_re.search(content, opening.end())
        fences.append((opening.start(), closing.end() if closing else len(content)))

    blocks = list(fences)
    for indented in _INDENTED_CODE_LINE_RE.finditer(content):
        if any(start <= indented.start() < end for start, end in fences):
            continue
        blocks.append((indented.start(), indented.end()))
    blocks.sort()

    ranges = list(blocks)
    cursor = 0
    for block_start, block_end in blocks:
        if cursor < block_start:
            ranges.extend(_scan_inline_protected_ranges(content, cursor, block_start))
        cursor = max(cursor, block_end)
    if cursor < len(content):
        ranges.extend(_scan_inline_protected_ranges(content, cursor, len(content)))

    return sorted(ranges)


def _mask_protected_markdown(content: str) -> str:
    """Mask protected spans while preserving offsets and line boundaries."""

    masked = list(content)
    for start, end in _protected_markdown_ranges(content):
        masked[start:end] = [
            "\n" if character == "\n" else "\r" if character == "\r" else "\x00"
            for character in content[start:end]
        ]
    return "".join(masked)


def _substitute_unprotected(
    pattern: re.Pattern[str],
    replacement: str | Callable[[re.Match[str]], str],
    content: str,
) -> str:
    """Apply one regex only outside protected Markdown spans."""

    masked = _mask_protected_markdown(content)
    pieces: list[str] = []
    cursor = 0
    for match in pattern.finditer(masked):
        pieces.append(content[cursor : match.start()])
        pieces.append(
            replacement(match) if callable(replacement) else match.expand(replacement)
        )
        cursor = match.end()
    pieces.append(content[cursor:])
    return "".join(pieces)


def iter_citation_matches(markdown: str) -> Iterator[re.Match[str]]:
    """Yield citation regex matches outside code and math spans."""

    yield from _CITATION_RE.finditer(_mask_protected_markdown(markdown))


def replace_citation_matches(
    markdown: str,
    replacement: str | Callable[[re.Match[str]], str],
) -> str:
    """Replace citation tokens outside code and math spans."""

    return _substitute_unprotected(_CITATION_RE, replacement, markdown)


class MalformedCitationError(ValueError):
    """Raised when a numeric citation token has an invalid range surface."""


def _is_year_bracket(surface: str) -> bool:
    """Return whether *surface* is a bounded publication-year bracket."""

    match = _YEAR_BRACKET_RE.fullmatch(surface.strip())
    if match is None:
        return False
    start = int(match.group(1))
    end = int(match.group(2) or match.group(1))
    return (
        _MIN_PUBLICATION_YEAR <= start <= _MAX_PUBLICATION_YEAR
        and _MIN_PUBLICATION_YEAR <= end <= _MAX_PUBLICATION_YEAR
        and (match.group(2) is None or start <= end)
    )


# ---------------------------------------------------------------------------
# 1. parse_citation_numbers
# ---------------------------------------------------------------------------


def parse_citation_numbers(text: str) -> list[int]:
    """Parse citation content like ``"1, 3-5, 7"`` into ``[1, 3, 4, 5, 7]``.

    Supported separators: comma, semicolon (ASCII / full-width), CJK comma
    (U+3001 / U+FF0C), and middle dot (U+00B7), with optional whitespace.
    Supported range delimiters: hyphen-minus, en-dash (U+2013), em-dash (U+2014).

    Returns an empty list if *text* looks like a year (1800-2200) or is empty.

    Raises
    ------
    MalformedCitationError
        If a range is descending, incomplete, or exceeds the bounded span.
    """
    text = text.strip()
    if not text:
        return []

    # A bounded year is prose metadata, not a citation token. Four-digit
    # values outside the publication-year range remain ordinary numbers and
    # are therefore validated against the reference map.
    if _is_year_bracket(f"[{text}]"):
        return []

    # Normalise separators to commas for uniform splitting.
    normalised = re.sub(r"[;；、，·]+", ",", text)
    # Normalise range delimiters to a standard hyphen.
    normalised = re.sub(r"[–—]", "-", normalised)
    # Remove whitespace around a range dash before treating remaining
    # whitespace as a list separator (``[1 2]`` is a supported surface).
    normalised = re.sub(r"\s*-\s*", "-", normalised)

    # Split by comma or whitespace between numeric items.
    parts: list[str] = [
        part for part in re.split(r"\s*,\s*|\s+(?=\d)", normalised.strip()) if part
    ]

    numbers: list[int] = []
    for part in parts:
        # Is it a range? e.g. "3-5"
        range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start > end:
                raise MalformedCitationError(
                    f"citation range must be ascending: {part}"
                )
            span = end - start + 1
            if span > _MAX_CITATION_RANGE_SPAN:
                raise MalformedCitationError(
                    "citation range exceeds "
                    f"{_MAX_CITATION_RANGE_SPAN} references: {part}"
                )
            numbers.extend(range(start, end + 1))
        elif part.isdigit():
            val = int(part)
            numbers.append(val)
        elif any(character.isdigit() or character == "-" for character in part):
            raise MalformedCitationError(f"malformed citation token: {part}")
        # Non-numeric fragments are ignored for backwards compatibility.

    return numbers


def iter_citation_number_groups(markdown: str) -> Iterator[list[int]]:
    """Yield parsed citation number groups while ignoring protected spans."""

    for match in iter_citation_matches(markdown):
        if _is_year_bracket(match.group(0)):
            continue
        numbers = parse_citation_numbers(match.group(1))
        if numbers:
            yield numbers


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
        if _is_year_bracket(match.group(0)):
            return match.group(0)

        nums = parse_citation_numbers(inner)
        if not nums:
            # Not a real citation – keep original text.
            return match.group(0)

        remapped = [_remap_number(n) for n in nums]
        # Rebuild the bracket content, collapsing to comma-separated.
        return "[" + ",".join(str(n) for n in remapped) + "]"

    renumbered = replace_citation_matches(markdown, _replace_token)

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
                "url": paper_info.get("url", ""),
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

    content = _substitute_unprotected(
        _PAREN_NUMERIC_CITATION_RE, _unwrap_numeric_citation, content
    )
    content = _substitute_unprotected(_PAREN_PLACEHOLDER_CITATION_RE, "", content)
    content = _substitute_unprotected(_PLACEHOLDER_CITATION_RE, "", content)
    content = _substitute_unprotected(
        re.compile(r"（\s*([A-Za-z]{1,3})\s*）"), "", content
    )
    content = _substitute_unprotected(
        re.compile(r"\(\s*([A-Za-z]{1,3})\s*\)"), "", content
    )
    content = _substitute_unprotected(re.compile(r"[ \t]{2,}"), " ", content)
    content = _substitute_unprotected(re.compile(r"\s+([，,。；;：:])"), r"\1", content)
    content = _substitute_unprotected(
        re.compile(r"([。！？])([A-Za-z\u4e00-\u9fff])"), r"\1 \2", content
    )
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
    masked = _mask_protected_markdown(markdown)
    match = _REF_HEADING_RE.search(masked)
    if match is None:
        return markdown

    start = match.start()
    # Find the next heading at the same or higher level (fewer or equal
    # leading ``#`` characters).
    heading_level = len(match.group(0).lstrip()) - len(
        match.group(0).lstrip().lstrip("#")
    )

    # Search for the next heading after the references heading.
    rest = masked[match.end() :]
    next_heading = re.search(rf"^#{{{1},{heading_level}}}\s+\S", rest, re.MULTILINE)

    prefix = markdown[:start].rstrip()
    if next_heading is None:
        return prefix + "\n"

    end = match.end() + next_heading.start()
    suffix = markdown[end:].lstrip()
    if not prefix:
        return suffix
    if not suffix:
        return prefix + "\n"
    return f"{prefix}\n\n{suffix}"


# ---------------------------------------------------------------------------
# 6b. strip_section_reference_block
# ---------------------------------------------------------------------------

# Matches reference-like blocks inside a single section: lines starting with
# [N] followed by author/title text, or a "参考文献"/"References" sub-heading.
_SECTION_REF_PREFIX_RE = re.compile(r"^\s*\[\d+\]\s+(?P<body>\S.+?)\s*$")
_SECTION_REF_QUOTED_TITLE_RE = re.compile(
    r"^[^,，\n]{1,160}[,，]\s*[\"“][^\"”\n]+[\"”]\s*[,，]"
)
_SECTION_REF_AUTHOR_PREFIX_RE = re.compile(
    r"^(?:"
    r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.\-]*"
    r"(?:\s+(?:[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.\-]*|et\s+al\.?)){0,8}"
    r"|[\u4e00-\u9fff]{2,12}(?:等)?"
    r")\s*[,.;，；。]"
)
_SECTION_REF_STRONG_MARKER_RE = re.compile(
    r"(?:"
    r"(?<!\d)(?:18\d{2}|19\d{2}|20\d{2}|21\d{2}|2200)(?!\d)"
    r"|https?://"
    r"|\bdoi\s*:?\s*10\.\d{4,9}/"
    r"|\b10\.\d{4,9}/\S+"
    r"|\barxiv\s*:"
    r")",
    re.IGNORECASE,
)
_SECTION_REF_NARRATIVE_VERB_RE = re.compile(
    r"(?:"
    r"\b(?:proposes?|proposed|finds?|found|shows?|showed|demonstrates?|"
    r"demonstrated|reports?|reported|argues?|argued)\b"
    r"|提出|认为|发现|表明|证明|指出|报道"
    r")",
    re.IGNORECASE,
)
_SECTION_REF_HEADING_RE = re.compile(
    r"^#{1,4}\s*(?:references?|bibliography|参考文献|引用文献)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _looks_like_section_reference_line(line: str) -> bool:
    match = _SECTION_REF_PREFIX_RE.fullmatch(line)
    if match is None:
        return False
    body = str(match.group("body"))
    if _SECTION_REF_QUOTED_TITLE_RE.match(body):
        return True
    if _SECTION_REF_STRONG_MARKER_RE.search(body) is None:
        return False
    leading_segment = re.split(r"[,.;，；。]", body, maxsplit=1)[0]
    if _SECTION_REF_NARRATIVE_VERB_RE.search(leading_segment):
        return False
    if _SECTION_REF_AUTHOR_PREFIX_RE.match(body) is None:
        return False
    punctuation_count = len(re.findall(r"[,.;，；。]", body))
    has_link_marker = bool(re.search(r"https?://|doi\s*:|arxiv\s*:", body, re.I))
    return punctuation_count >= (2 if has_link_marker else 3)


def strip_section_reference_block(content: str) -> str:
    """Remove any inline reference list from a single section's content.

    Handles cases where the LLM appends a ``[N] author, "title", venue, year``
    list at the end of a section despite being told not to.

    Also strips a trailing ``## References`` / ``## 参考文献`` sub-heading
    and everything after it.
    """
    # 1. Strip trailing reference sub-heading and everything after it.
    masked_content = _mask_protected_markdown(content)
    match = _SECTION_REF_HEADING_RE.search(masked_content)
    if match is not None:
        content = content[: match.start()].rstrip()
        masked_content = _mask_protected_markdown(content)

    # 2. Strip trailing block of consecutive [N] reference lines.
    lines = content.split("\n")
    masked_lines = masked_content.split("\n")
    # Walk backwards to find where the reference block starts.
    ref_start = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        stripped = masked_lines[i].strip()
        if not stripped:
            # Allow blank lines inside the reference block.
            if ref_start == i + 1:
                continue  # trailing blank line
            break
        if _looks_like_section_reference_line(stripped):
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
