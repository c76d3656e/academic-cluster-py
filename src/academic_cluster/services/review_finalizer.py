"""
Deterministic review finalization utilities.

This mirrors the Rust review_writer finalizer policy: section-local citations
are first bound to their section candidate plans, then the assembled markdown is
renumbered by first appearance and finalized with a reference list generated
from that exact mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .citation_utils import (
    _CITATION_RE,
    _YEAR_BRACKET_RE,
    normalize_citation_surface,
    parse_citation_numbers,
    renumber_citations_by_first_use,
    strip_reference_block,
)


@dataclass(frozen=True)
class AssemblyReport:
    section_count: int
    draft_unique_reference_count: int
    assembled_unique_reference_count: int
    dropped_citation_count: int
    retention_basis_points: int
    policy: str = "deterministic_section_order_preserve_citations"


@dataclass(frozen=True)
class FinalizedReview:
    markdown: str
    body_markdown: str
    reference_mappings: list[dict[str, Any]]
    assembly_report: AssemblyReport


def citation_reference_numbers(markdown: str, max_reference_count: int | None = None) -> set[int]:
    """Return citation numbers used in markdown, excluding year-like brackets."""
    numbers: set[int] = set()
    for match in _CITATION_RE.finditer(markdown):
        if _YEAR_BRACKET_RE.fullmatch(match.group(0)):
            continue
        for number in parse_citation_numbers(match.group(1)):
            if max_reference_count is None or 1 <= number <= max_reference_count:
                numbers.add(number)
    return numbers


def remap_section_local_citations(
    markdown: str,
    candidate_paper_ids: list[str],
    paper_number_by_id: dict[str, int],
) -> tuple[str, set[int]]:
    """
    Convert section-local [N] citations into stable global paper numbers.

    The LLM sees each section's references as [1..section_candidates]. Without
    this step, two sections can use [1] for different papers and final assembly
    will bind both claims to the same global paper.
    """
    invalid_local_numbers: set[int] = set()

    def _replace_token(match) -> str:
        original = match.group(0)
        if _YEAR_BRACKET_RE.fullmatch(original):
            return original

        local_numbers = parse_citation_numbers(match.group(1))
        if not local_numbers:
            return original

        global_numbers: list[int] = []
        for local_number in local_numbers:
            if local_number < 1 or local_number > len(candidate_paper_ids):
                invalid_local_numbers.add(local_number)
                continue
            paper_id = candidate_paper_ids[local_number - 1]
            global_number = paper_number_by_id.get(paper_id)
            if global_number is None:
                invalid_local_numbers.add(local_number)
                continue
            if global_number not in global_numbers:
                global_numbers.append(global_number)

        if not global_numbers:
            return ""
        return "[" + ",".join(str(number) for number in global_numbers) + "]"

    return _CITATION_RE.sub(_replace_token, markdown), invalid_local_numbers


def assemble_review_deterministic(
    review_title: str,
    sections: list[dict],
    section_bodies: list[str],
    max_reference_count: int,
) -> tuple[str, AssemblyReport]:
    """Assemble sections in outline order without asking an LLM to rewrite."""
    rendered_sections: list[str] = []
    for idx, section in enumerate(sections):
        title = str(section.get("title") or f"Section {idx + 1}").strip()
        body = section_bodies[idx].strip() if idx < len(section_bodies) else ""
        body = normalize_citation_surface(body)
        if not body:
            body = "No supported section draft was generated."
        rendered_sections.append(f"## {title}\n\n{body}")

    markdown = f"# {review_title.strip()}\n\n" + "\n\n".join(rendered_sections)
    draft_refs = set().union(
        *[
            citation_reference_numbers(body, max_reference_count)
            for body in section_bodies
        ]
    ) if section_bodies else set()
    assembled_refs = citation_reference_numbers(markdown, max_reference_count)
    dropped = len(draft_refs - assembled_refs)
    retention = _ratio_basis_points(len(assembled_refs & draft_refs), len(draft_refs))

    return markdown, AssemblyReport(
        section_count=len(sections),
        draft_unique_reference_count=len(draft_refs),
        assembled_unique_reference_count=len(assembled_refs),
        dropped_citation_count=dropped,
        retention_basis_points=retention,
    )


def finalize_review_markdown(
    review_title: str,
    sections: list[dict],
    section_bodies: list[str],
    paper_metadata_map: dict[int, dict[str, Any]],
) -> FinalizedReview:
    """Build final markdown and references from deterministic assembly."""
    assembled, assembly_report = assemble_review_deterministic(
        review_title=review_title,
        sections=sections,
        section_bodies=section_bodies,
        max_reference_count=len(paper_metadata_map),
    )
    body_without_refs = strip_reference_block(assembled).rstrip()
    renumbered_body, mappings = renumber_citations_by_first_use(
        body_without_refs,
        paper_metadata_map,
    )
    references = render_reference_list_from_mappings(mappings)
    final_markdown = renumbered_body.rstrip()
    if references:
        final_markdown += "\n\n## References\n\n" + references

    return FinalizedReview(
        markdown=final_markdown,
        body_markdown=renumbered_body,
        reference_mappings=mappings,
        assembly_report=assembly_report,
    )


def render_reference_list_from_mappings(mappings: list[dict[str, Any]]) -> str:
    """Render references from the final citation mapping, not from paper order."""
    lines: list[str] = []
    for mapping in sorted(mappings, key=lambda item: item.get("new_number", 0)):
        number = mapping.get("new_number")
        raw_authors = mapping.get("authors") or ""
        if isinstance(raw_authors, list):
            authors = ", ".join(
                item.get("name", str(item)) if isinstance(item, dict) else str(item)
                for item in raw_authors
            )
        else:
            authors = str(raw_authors).strip()
        author_parts = [part.strip() for part in re.split(r";|,\s*(?=[A-Z])", authors) if part.strip()]
        if len(author_parts) > 3:
            authors = ", ".join(author_parts[:3]) + " et al."
        title = str(mapping.get("title") or "").strip()
        venue = str(mapping.get("venue") or "").strip()
        year = str(mapping.get("year") or "").strip()
        doi = str(mapping.get("doi") or "").strip()

        parts = [f"[{number}]"]
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
        lines.append(" ".join(parts).rstrip())
    return "\n".join(lines)


def _ratio_basis_points(numerator: int, denominator: int) -> int:
    if denominator == 0:
        return 0
    return (numerator * 10_000) // denominator
