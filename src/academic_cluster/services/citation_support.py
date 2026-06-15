"""
Citation support audit - deterministic check that citations are backed by evidence cards.

Aligned with Rust version citation_support.rs.
"""

from __future__ import annotations

import re
from typing import Any

from .citation_utils import parse_citation_numbers


# Sentence-ending punctuation (Chinese + English)
_SENTENCE_END_RE = re.compile(r"[。！？.!?\n]")

# Citation pattern [N] or [N,M] or [N-M]
_CITATION_RE = re.compile(r"\[([0-9,\s;–—、，·\-]+)\]")


def _extract_sentences(text: str) -> list[str]:
    """Split text into sentences using sentence-ending punctuation."""
    sentences = re.split(r"(?<=[。！？.!?\n])", text)
    return [s.strip() for s in sentences if s.strip()]


def _find_citation_sentence(text: str, byte_offset: int) -> str:
    """Find the sentence containing the given byte offset."""
    # Convert byte offset to char offset (approximate for UTF-8)
    # For simplicity, search by character position
    sentences = _extract_sentences(text)
    pos = 0
    for sent in sentences:
        end = pos + len(sent)
        if pos <= byte_offset <= end:
            return sent
        pos = end + 1  # +1 for the separator
    return ""


def _normalize_tokens(text: str) -> set[str]:
    """Extract normalized tokens for lexical overlap computation.

    - ASCII tokens: lowercase, length > 2
    - CJK bigrams and trigrams
    """
    tokens: set[str] = set()

    # ASCII tokens
    ascii_words = re.findall(r"[a-z][a-z0-9]+", text.lower())
    for w in ascii_words:
        if len(w) > 2:
            tokens.add(w)

    # CJK bigrams and trigrams
    cjk_chars = [c for c in text if "一" <= c <= "鿿"]
    for i in range(len(cjk_chars) - 1):
        tokens.add(cjk_chars[i] + cjk_chars[i + 1])
    for i in range(len(cjk_chars) - 2):
        tokens.add(cjk_chars[i] + cjk_chars[i + 1] + cjk_chars[i + 2])

    return tokens


def _lexical_overlap(context: str, evidence: str) -> float:
    """Compute lexical overlap between context and evidence text.

    Returns overlap as a fraction (0.0 to 1.0).
    """
    context_tokens = _normalize_tokens(context)
    evidence_tokens = _normalize_tokens(evidence)

    if not context_tokens or not evidence_tokens:
        return 0.0

    intersection = context_tokens & evidence_tokens
    # Use the smaller set as denominator (Jaccard-like)
    denominator = min(len(context_tokens), len(evidence_tokens))
    if denominator == 0:
        return 0.0

    return len(intersection) / denominator


def audit_citation_support(
    section_text: str,
    evidence_cards: list[dict],
    citation_mentions: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Audit whether citations in section_text are supported by evidence cards.

    Parameters
    ----------
    section_text : str
        The section markdown text containing [N] citations.
    evidence_cards : list[dict]
        Evidence cards with keys: paper_id, title, claim, evidence_span, method, confidence.
        Indexed by position (card at index 0 corresponds to [1]).
    citation_mentions : list[dict] | None
        Pre-parsed citation mentions with keys: reference_number, byte_offset.
        If None, citations are parsed from section_text.

    Returns
    -------
    dict
        {
            "total_citations": int,
            "supported_count": int,
            "weak_count": int,
            "unsupported_count": int,
            "support_rate": float,  # 0.0-1.0
            "details": list[dict],  # per-citation details
        }
    """
    # Parse citation mentions if not provided
    if citation_mentions is None:
        citation_mentions = []
        for match in _CITATION_RE.finditer(section_text):
            inner = match.group(1)
            # Skip year-like brackets
            if re.fullmatch(r"\d{4}(?:\s*[-–—]\s*\d{4})?", inner):
                continue
            # Parse numbers using shared utility
            numbers = parse_citation_numbers(inner)
            for num in numbers:
                citation_mentions.append({
                    "reference_number": num,
                    "byte_offset": match.start(),
                })

    details: list[dict] = []
    supported = 0
    weak = 0
    unsupported = 0

    for mention in citation_mentions:
        ref_num = mention["reference_number"]
        offset = mention.get("byte_offset", 0)

        # Get evidence card (0-indexed)
        card_idx = ref_num - 1
        card: dict | None = None
        if 0 <= card_idx < len(evidence_cards):
            card = evidence_cards[card_idx]

        # Extract citation context sentence
        sentence = _find_citation_sentence(section_text, offset)

        if card is None:
            # Missing evidence card
            details.append({
                "reference_number": ref_num,
                "status": "unsupported",
                "reason": "missing_evidence_card",
                "support_score_bp": 0,
            })
            unsupported += 1
            continue

        # Build evidence text
        evidence_parts: list[str] = []
        for field in ("title", "claim", "evidence_span", "method"):
            val = card.get(field, "")
            if val:
                evidence_parts.append(str(val))
        evidence_text = " ".join(evidence_parts)

        # Compute lexical overlap
        overlap = _lexical_overlap(sentence, evidence_text)
        confidence = float(card.get("confidence", 0.0))

        # Support score in basis points (10000 = 100%)
        support_score = overlap * 0.70 + confidence * 0.30

        # Determine status
        overlap_bp = overlap * 10000
        support_bp = support_score * 10000

        if overlap_bp >= 1000 and support_bp >= 2000:
            status = "supported"
            supported += 1
        elif overlap_bp >= 500 or support_bp >= 1000:
            status = "weak"
            weak += 1
        else:
            status = "unsupported"
            unsupported += 1

        details.append({
            "reference_number": ref_num,
            "status": status,
            "lexical_overlap_bp": round(overlap_bp),
            "support_score_bp": round(support_bp),
            "confidence": confidence,
            "sentence_preview": sentence[:100],
        })

    total = len(citation_mentions)
    return {
        "total_citations": total,
        "supported_count": supported,
        "weak_count": weak,
        "unsupported_count": unsupported,
        "support_rate": supported / total if total > 0 else 0.0,
        "details": details,
    }
