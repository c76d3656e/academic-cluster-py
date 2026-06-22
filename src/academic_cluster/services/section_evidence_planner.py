"""Section-level evidence planning for review writing.

This module turns broad citation candidates into a tighter evidence matrix.
It follows the same design pressure as AutoSurvey/SurveyG: section writing
should consume a small, relevant set of claims, not the whole candidate pool.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from .citation_planner import SectionCitationPlan

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}")


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_text(v) for v in value)
    return " ".join(str(value or "").split())


def _tokens(value: Any) -> set[str]:
    text = _text(value).lower()
    tokens = set(_TOKEN_RE.findall(text))
    cjk = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    if len(cjk) >= 2:
        tokens.update(cjk[i:i + 2] for i in range(len(cjk) - 1))
    return tokens


def _score_overlap(query_tokens: set[str], value: Any) -> float:
    if not query_tokens:
        return 0.0
    value_tokens = _tokens(value)
    if not value_tokens:
        return 0.0
    return len(query_tokens & value_tokens) / max(1, min(len(query_tokens), len(value_tokens)))


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _source_weight(source: str) -> float:
    if source in {"community_core", "community_auxiliary"}:
        return 0.30
    if source in {"hybrid_neighbor_core", "hybrid_neighbor_auxiliary"}:
        return 0.18
    if source in {"remaining_core", "remaining_auxiliary"}:
        return 0.08
    return 0.0


def _section_query(section: dict, memories: list[dict]) -> str:
    target = {str(x) for x in (
        section.get("target_communities")
        or section.get("key_clusters")
        or section.get("clusters")
        or []
    )}
    related = [m for m in memories if str(m.get("cluster_id")) in target]
    parts: list[Any] = [
        section.get("title"),
        section.get("description"),
        section.get("section_role"),
        section.get("core_question_hint"),
        section.get("method_families"),
        section.get("expected_claims"),
        section.get("limitations_to_cover"),
        section.get("future_directions_to_cover"),
    ]
    for memory in related:
        parts.extend([
            memory.get("summary"),
            memory.get("method_families"),
            memory.get("key_claims"),
            memory.get("limitations"),
            memory.get("future_directions"),
        ])
    return _text(parts)


def _memory_by_cluster(memories: list[dict]) -> dict[str, dict]:
    return {
        str(memory.get("cluster_id")): memory
        for memory in memories
        if memory.get("cluster_id") is not None
    }


def _cards_by_paper(evidence_cards: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for card in evidence_cards:
        pid = str(card.get("paper_id") or "")
        if pid:
            grouped.setdefault(pid, []).append(card)
    return grouped


def _paper_cluster_map(clusters: list[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for cluster in clusters:
        cid = str(cluster.get("id"))
        for pid in cluster.get("paper_ids") or []:
            result[str(pid)] = cid
    return result


def _support_item(
    *,
    paper_id: str,
    card: dict | None,
    paper: dict,
    score: float,
    source: str,
) -> dict:
    return {
        "paper_id": paper_id,
        "title": paper.get("title", ""),
        "evidence_card_id": str((card or {}).get("id") or ""),
        "claim": (card or {}).get("claim", ""),
        "evidence_span": (card or {}).get("evidence_span", ""),
        "method": (card or {}).get("method", ""),
        "metric": (card or {}).get("metric", ""),
        "limitation": (card or {}).get("limitation", ""),
        "confidence": (card or {}).get("confidence", 0.0),
        "relevance_score": round(score, 4),
        "candidate_source": source,
    }


def _render_community_context(section: dict, memories: list[dict]) -> str:
    target = {
        str(x)
        for x in (
            section.get("target_communities")
            or section.get("key_clusters")
            or section.get("clusters")
            or []
        )
    }
    related = [m for m in memories if str(m.get("cluster_id")) in target]
    lines = []
    for memory in related:
        metadata = memory.get("metadata") or {}
        coherence = metadata.get("coherence_assessment") or {}
        topic_rel = metadata.get("topic_relevance") or {}
        lines.append(f"community {memory.get('cluster_id')}: {memory.get('summary', '')}")
        methods = memory.get("method_families") or []
        if methods:
            lines.append("method_families: " + "; ".join(str(x) for x in methods[:8]))
        limitations = memory.get("limitations") or []
        if limitations:
            lines.append("limitations: " + "; ".join(str(x) for x in limitations[:6]))
        future = memory.get("future_directions") or []
        if future:
            lines.append("future_directions: " + "; ".join(str(x) for x in future[:5]))
        if coherence:
            lines.append(
                f"coherence: score={coherence.get('score')}; {coherence.get('rationale', '')}"
            )
        if topic_rel:
            lines.append(
                f"topic_relevance: score={topic_rel.get('score')}; {topic_rel.get('rationale', '')}"
            )
    return "\n".join(lines)


def plan_section_evidence(
    *,
    topic: str,
    sections: list[dict],
    citation_plans: list[SectionCitationPlan],
    evidence_cards: list[dict],
    community_memories: list[dict],
    paper_map: dict[str, dict],
    clusters: list[dict],
    max_references_per_section: int = 18,
    min_references_per_section: int = 8,
) -> tuple[list[SectionCitationPlan], dict[int, dict]]:
    """Filter citation plans and build per-section support matrices."""
    cards_by_pid = _cards_by_paper(evidence_cards)
    paper_to_cluster = _paper_cluster_map(clusters)
    memory_map = _memory_by_cluster(community_memories)
    filtered_plans: list[SectionCitationPlan] = []
    evidence_plans: dict[int, dict] = {}
    topic_tokens = _tokens(topic)

    for plan in citation_plans:
        section = sections[plan.section_index] if plan.section_index < len(sections) else {}
        query = _section_query(section, community_memories)
        query_tokens = _tokens(query) | topic_tokens
        target_clusters = {
            str(x)
            for x in (
                section.get("target_communities")
                or section.get("key_clusters")
                or section.get("clusters")
                or []
            )
        }

        scored: list[tuple[float, int, dict]] = []
        for rank, detail in enumerate(plan.candidate_details):
            pid = str(detail.get("paper_id") or "")
            if not pid:
                continue
            paper = paper_map.get(pid, {})
            cards = cards_by_pid.get(pid, [])
            cluster_id = str(detail.get("cluster_id") or paper_to_cluster.get(pid) or "")
            source = str(detail.get("source") or "")
            cluster_bonus = 0.28 if cluster_id in target_clusters else 0.0
            paper_score = _score_overlap(query_tokens, [paper.get("title"), paper.get("abstract")])
            card_score = max((_score_overlap(query_tokens, card) for card in cards), default=0.0)
            memory_score = _score_overlap(query_tokens, memory_map.get(cluster_id, {}))
            evidence_bonus = 0.12 if cards else 0.0
            score = (
                0.40 * card_score
                + 0.24 * paper_score
                + 0.16 * memory_score
                + cluster_bonus
                + evidence_bonus
                + _source_weight(source)
            )
            scored.append((score, rank, detail))

        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = scored[:max_references_per_section]
        if len(selected) < min_references_per_section:
            selected = scored[:min(min_references_per_section, len(scored))]
        selected_pids = [str(detail.get("paper_id")) for _, _, detail in selected]
        selected_set = set(selected_pids)
        selected_details = [
            detail for detail in plan.candidate_details
            if str(detail.get("paper_id")) in selected_set
        ]
        selected_details.sort(key=lambda d: selected_pids.index(str(d.get("paper_id"))))

        filtered_plans.append(replace(
            plan,
            candidate_paper_ids=selected_pids,
            candidate_details=selected_details,
        ))

        support_matrix = []
        for score, _, detail in selected:
            pid = str(detail.get("paper_id") or "")
            paper = paper_map.get(pid, {})
            cards = cards_by_pid.get(pid) or [None]
            best_card = max(
                cards,
                key=lambda card: _score_overlap(query_tokens, card) if card else 0.0,
            )
            support_matrix.append(_support_item(
                paper_id=pid,
                card=best_card,
                paper=paper,
                score=score,
                source=str(detail.get("source") or ""),
            ))

        weak = [item for item in support_matrix if item["relevance_score"] < 0.25]
        evidence_plans[plan.section_index] = {
            "section_index": plan.section_index,
            "section_title": section.get("title", plan.section_title),
            "section_thesis": section.get("description", ""),
            "selected_paper_ids": selected_pids,
            "support_matrix": support_matrix,
            "community_context": _render_community_context(section, community_memories),
            "evidence_limitations": "\n".join(
                f"- weak_or_indirect: {item['paper_id']} {item['title']}"
                for item in weak[:8]
            ),
            "diagnostics": {
                "candidate_count_before": len(plan.candidate_paper_ids),
                "candidate_count_after": len(selected_pids),
                "weak_support_count": len(weak),
            },
        }

    return filtered_plans, evidence_plans


def cards_from_support_matrix(support_matrix: list[dict]) -> list[dict]:
    """Convert support matrix rows back to evidence-card-like rows for writers."""
    cards = []
    for item in support_matrix:
        if not item.get("evidence_card_id") and not item.get("claim"):
            continue
        cards.append({
            "id": item.get("evidence_card_id"),
            "paper_id": item.get("paper_id"),
            "title": item.get("title"),
            "claim": item.get("claim"),
            "evidence_span": item.get("evidence_span"),
            "method": item.get("method"),
            "metric": item.get("metric"),
            "limitation": item.get("limitation"),
            "confidence": item.get("confidence"),
            "relevance_score": item.get("relevance_score"),
        })
    return cards
