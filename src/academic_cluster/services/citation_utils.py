"""
Citation utilities for academic review writing.

Handles citation validation, renumbering, and reference list generation.
"""

from __future__ import annotations

import re
from typing import Any

# Matches [N] or [N,M,K] or [N-M] style citation tokens inside markdown.
# We exclude year-like brackets [1800-2200] via a negative lookahead in
# the caller rather than here, because the regex itself is intentionally
# greedy to capture any bracket content that *might* be a citation.
_CITATION_RE = re.compile(r"\[([0-9,\s;–—、，·\-]+)\]")

# Matches a bare year-like bracket such as [2024] or [2020-2023].
_YEAR_BRACKET_RE = re.compile(r"\[(\d{4})(?:\s*[-–—]\s*(\d{4}))?\]")

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
        end = match.end() + next_heading.start()
    else:
        end = len(markdown)

    return markdown[:start].rstrip() + "\n"
