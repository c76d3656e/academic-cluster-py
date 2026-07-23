"""DOI normalization and validation used by academic source adapters."""

from __future__ import annotations

import re


def normalize_doi(doi: str) -> str:
    """Return a lowercase DOI without resolver prefixes or trailing periods."""

    if not doi:
        return ""
    normalized = doi.strip()
    for prefix in (
        "doi:",
        "DOI:",
        "https://doi.org/",
        "https://dx.doi.org/",
        "http://doi.org/",
        "http://dx.doi.org/",
    ):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized.strip().rstrip(".").lower()


def is_valid_doi(doi: str) -> bool:
    """Return whether a value matches the DOI registrant/suffix shape."""

    return bool(doi and re.fullmatch(r"10\.\d{4,9}/[^\s]+", normalize_doi(doi)))
