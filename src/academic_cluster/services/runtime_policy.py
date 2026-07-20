"""Persistent, administrator-controlled policy for future Agent runs."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


@dataclass(frozen=True)
class RuntimePolicy:
    embedding_target_dimensions: int
    default_target_papers: int
    default_target_words: int
    quality_threshold: float
    minimum_body_ratio: float
    minimum_body_tolerance: float
    enabled_sources: tuple[str, ...]
    results_per_source: int
    max_search_calls: int
    max_phase_attempts: int
    max_research_rounds: int
    max_revision_attempts: int
    search_request_timeout_seconds: float
    search_total_timeout_seconds: float
    search_max_retries: int
    search_retry_after_cap_seconds: float
    search_backoff_cap_seconds: float
    analysis_processing_limit: int
    kg_entities_per_paper: int
    kg_relations_per_paper: int
    kg_timeout_seconds: float
    evidence_processing_limit: int
    evidence_timeout_seconds: float
    knn_neighbors: int
    knn_similarity_threshold: float
    min_references_per_section: int
    max_references_per_section: int
    provider_request_timeout_seconds: float
    provider_router_retries: int
    provider_timeout_retries: int
    provider_retry_delay_seconds: float
    provider_timeout_grace_seconds: float
    provider_allowed_failures: int
    provider_cooldown_seconds: float
    provider_default_rpm: int
    rerank_enabled: bool
    rerank_candidate_limit: int
    rerank_top_n: int
    rerank_timeout_seconds: float
    rerank_max_retries: int
    rerank_failure_mode: str
    rerank_max_concurrent_requests: int
    rerank_max_queued_requests: int
    rerank_queue_wait_timeout_seconds: float


def config_definitions() -> dict[str, dict[str, Any]]:
    raw = (
        files("academic_cluster.config").joinpath("pipeline_defaults.toml").read_bytes()
    )
    parsed = tomllib.loads(raw.decode("utf-8"))
    return {str(item["key"]): dict(item) for item in parsed["items"]}


def validate_config_value(definition: dict[str, Any], value: str) -> str:
    config_type = str(definition["type"])
    normalized = value.strip()
    if config_type == "bool":
        if normalized.lower() not in {"true", "false"}:
            raise ValueError("Boolean values accept only true or false")
        return normalized.lower()
    if config_type in {"integer", "number"}:
        try:
            number = int(normalized) if config_type == "integer" else float(normalized)
        except ValueError as error:
            raise ValueError("Value must be numeric") from error
        if number < definition.get("minimum", number) or number > definition.get(
            "maximum", number
        ):
            raise ValueError(
                f"Value must be between {definition.get('minimum')} and {definition.get('maximum')}"
            )
        return str(number)
    if config_type == "sources":
        try:
            selected = json.loads(normalized)
        except json.JSONDecodeError as error:
            raise ValueError("Sources must be a JSON array") from error
        options = set(definition.get("options") or [])
        if (
            not isinstance(selected, list)
            or not selected
            or any(item not in options for item in selected)
        ):
            raise ValueError("Select at least one supported search source")
        return json.dumps(list(dict.fromkeys(selected)))
    if config_type == "choice":
        options = {str(option) for option in definition.get("options") or []}
        if normalized not in options:
            raise ValueError(f"Value must be one of: {', '.join(sorted(options))}")
        return normalized
    return normalized


async def get_runtime_policy(db: Any | None = None) -> RuntimePolicy:
    definitions = config_definitions()
    values = {key: str(definition["value"]) for key, definition in definitions.items()}
    if db is None:
        from .database import get_database

        db = get_database()
    try:
        async with db.session() as session:
            result = await session.execute(
                text("SELECT key, value FROM pipeline_config")
            )
            for key, value in result.fetchall():
                if str(key) in values:
                    values[str(key)] = str(value)
    except (AttributeError, OSError, SQLAlchemyError, TypeError):
        # Startup and isolated tests retain the TOML policy if PostgreSQL is unavailable.
        pass
    return RuntimePolicy(
        embedding_target_dimensions=int(values["embedding.target_dimensions"]),
        default_target_papers=int(values["research.default_target_papers"]),
        default_target_words=int(values["writing.default_target_words"]),
        quality_threshold=float(values["writing.quality_threshold"]),
        minimum_body_ratio=float(values["writing.minimum_body_ratio"]),
        minimum_body_tolerance=float(values["writing.minimum_body_tolerance"]),
        enabled_sources=tuple(json.loads(values["research.enabled_sources"])),
        results_per_source=int(values["research.results_per_source"]),
        max_search_calls=int(values["research.max_search_calls"]),
        max_phase_attempts=int(values["workflow.max_phase_attempts"]),
        max_research_rounds=int(values["workflow.max_research_rounds"]),
        max_revision_attempts=int(values["workflow.max_revision_attempts"]),
        search_request_timeout_seconds=float(values["research.request_timeout_seconds"]),
        search_total_timeout_seconds=float(values["research.total_timeout_seconds"]),
        search_max_retries=int(values["research.max_retries"]),
        search_retry_after_cap_seconds=float(values["research.retry_after_cap_seconds"]),
        search_backoff_cap_seconds=float(values["research.backoff_cap_seconds"]),
        analysis_processing_limit=int(values["analysis.processing_limit"]),
        kg_entities_per_paper=int(values["analysis.kg_entities_per_paper"]),
        kg_relations_per_paper=int(values["analysis.kg_relations_per_paper"]),
        kg_timeout_seconds=float(values["analysis.kg_timeout_seconds"]),
        evidence_processing_limit=int(values["analysis.evidence_processing_limit"]),
        evidence_timeout_seconds=float(values["analysis.evidence_timeout_seconds"]),
        knn_neighbors=int(values["analysis.knn_neighbors"]),
        knn_similarity_threshold=float(values["analysis.knn_similarity_threshold"]),
        min_references_per_section=int(values["writing.min_references_per_section"]),
        max_references_per_section=int(values["writing.max_references_per_section"]),
        provider_request_timeout_seconds=float(values["provider.request_timeout_seconds"]),
        provider_router_retries=int(values["provider.router_retries"]),
        provider_timeout_retries=int(values["provider.timeout_retries"]),
        provider_retry_delay_seconds=float(values["provider.retry_delay_seconds"]),
        provider_timeout_grace_seconds=float(values["provider.timeout_grace_seconds"]),
        provider_allowed_failures=int(values["provider.allowed_failures"]),
        provider_cooldown_seconds=float(values["provider.cooldown_seconds"]),
        provider_default_rpm=int(values["provider.default_rpm"]),
        rerank_enabled=values["rerank.enabled"] == "true",
        rerank_candidate_limit=int(values["rerank.candidate_limit"]),
        rerank_top_n=int(values["rerank.top_n"]),
        rerank_timeout_seconds=float(values["rerank.timeout_seconds"]),
        rerank_max_retries=int(values["rerank.max_retries"]),
        rerank_failure_mode=values["rerank.failure_mode"],
        rerank_max_concurrent_requests=int(values["rerank.max_concurrent_requests"]),
        rerank_max_queued_requests=int(values["rerank.max_queued_requests"]),
        rerank_queue_wait_timeout_seconds=float(values["rerank.queue_wait_timeout_seconds"]),
    )
