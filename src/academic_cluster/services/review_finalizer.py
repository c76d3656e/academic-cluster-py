"""
Deterministic review finalization utilities.

This mirrors the Rust review_writer finalizer policy: section-local citations
are first bound to their section candidate plans, then the assembled markdown is
renumbered by first appearance and finalized with a reference list generated
from that exact mapping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .citation_utils import (
    iter_citation_number_groups,
    normalize_citation_surface,
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


def citation_reference_numbers(
    markdown: str, max_reference_count: int | None = None
) -> set[int]:
    """Return citation numbers used in markdown, excluding year-like brackets."""
    numbers: set[int] = set()
    for group in iter_citation_number_groups(markdown):
        for number in group:
            if max_reference_count is None or 1 <= number <= max_reference_count:
                numbers.add(number)
    return numbers


def assemble_review_deterministic(
    review_title: str,
    sections: list[dict[str, Any]],
    section_bodies: list[str],
    max_reference_count: int,
    abstract: str = "",
) -> tuple[str, AssemblyReport]:
    """Assemble sections in outline order without asking an LLM to rewrite."""
    rendered_sections: list[str] = []
    for idx, section in enumerate(sections):
        title = normalize_citation_surface(
            str(section.get("title") or f"Section {idx + 1}")
        )
        body = section_bodies[idx].strip() if idx < len(section_bodies) else ""
        body = normalize_citation_surface(body)
        if not body:
            body = "No supported section draft was generated."
        rendered_sections.append(f"## {idx + 1}. {title}\n\n{body}")

    normalized_title = normalize_citation_surface(review_title)
    normalized_abstract = normalize_citation_surface(abstract)
    document_parts = [f"# {normalized_title}"]
    if normalized_abstract:
        document_parts.append(f"## 摘要\n\n{normalized_abstract}")
    document_parts.extend(rendered_sections)
    markdown = "\n\n".join(document_parts)
    draft_fragments = [review_title, abstract, *section_bodies]
    draft_fragments.extend(str(section.get("title") or "") for section in sections)
    draft_refs = (
        set().union(
            *[
                citation_reference_numbers(fragment, max_reference_count)
                for fragment in draft_fragments
            ]
        )
        if draft_fragments
        else set()
    )
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
    sections: list[dict[str, Any]],
    section_bodies: list[str],
    paper_metadata_map: dict[int, dict[str, Any]],
    abstract: str = "",
) -> FinalizedReview:
    """Build final markdown and references from deterministic assembly."""
    assembled, assembly_report = assemble_review_deterministic(
        review_title=review_title,
        sections=sections,
        section_bodies=section_bodies,
        max_reference_count=len(paper_metadata_map),
        abstract=abstract,
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
        author_parts = [
            part.strip()
            for part in re.split(r";|,\s*(?=[A-Z])", authors)
            if part.strip()
        ]
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
