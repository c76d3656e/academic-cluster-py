"""Production multi-agent workflow with deterministic, bounded routing."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field

from ..services.citation_utils import (
    normalize_citation_surface,
    strip_body_structure_leakage,
    strip_meta_commentary,
    strip_prompt_leakage,
    strip_revision_commentary,
    strip_section_reference_block,
)
from ..services.observability import (
    pop_current_agent_phase,
    pop_current_execution,
    pop_current_project,
    push_current_agent_phase,
    push_current_execution,
    push_current_project,
)

logger = structlog.get_logger()

PHASES = ("research", "analysis", "writing", "peer_review")
TERMINAL_PHASE = "finalize"


class AgentState(BaseModel):
    """JSON-serializable state persisted by LangGraph."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    project_id: str
    execution_id: str
    topic: str
    target_papers: int = Field(default=50, ge=1, le=500)
    target_words: int = Field(default=12000, ge=1000, le=100000)
    quality_threshold: float = Field(default=75.0, ge=0.0, le=100.0)

    current_phase: str = "supervisor"
    status: str = "created"
    decision_reason: str = ""

    papers: list[dict[str, Any]] = Field(default_factory=list)
    paper_ids: list[str] = Field(default_factory=list)
    research_summary: dict[str, Any] = Field(default_factory=dict)
    research_complete: bool = False
    research_round: int = Field(default=0, ge=0, le=10)
    max_research_rounds: int = Field(default=2, ge=1, le=10)
    suggested_queries: list[str] = Field(default_factory=list)

    embeddings_ready: bool = False
    embedding_model: str = ""
    coverage: dict[str, Any] = Field(default_factory=dict)
    coverage_score: float = Field(default=0.0, ge=0.0, le=1.0)
    knowledge_graph: dict[str, Any] = Field(default_factory=dict)
    evidence_cards: list[dict[str, Any]] = Field(default_factory=list)
    gap_analysis: dict[str, Any] = Field(default_factory=dict)
    analysis_complete: bool = False

    outline: dict[str, Any] = Field(default_factory=dict)
    sections: list[dict[str, Any]] = Field(default_factory=list)
    reference_map: list[dict[str, Any]] = Field(default_factory=list)
    cited_reference_numbers: list[int] = Field(default_factory=list)
    final_references: list[dict[str, Any]] = Field(default_factory=list)
    abstract: str = ""
    final_review: str = ""
    writing_complete: bool = False

    peer_review_report: dict[str, Any] = Field(default_factory=dict)
    quality_score: float | None = Field(default=None, ge=0.0, le=100.0)
    peer_review_complete: bool = False
    needs_revision: bool = False
    revision_feedback: str = ""
    revision_attempt: int = Field(default=0, ge=0, le=10)
    max_revision_attempts: int = Field(default=2, ge=0, le=10)

    phase_attempts: dict[str, int] = Field(default_factory=dict)
    max_phase_attempts: int = Field(default=2, ge=1, le=10)
    failed_phase: str | None = None
    terminal_failure: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class CitationValidation:
    """Citation numbers observed in a generated review."""

    cited_numbers: set[int]
    invalid_numbers: set[int]
    disallowed_numbers: set[int]


def _paper_year(paper: dict[str, Any]) -> str:
    value = paper.get("year") or paper.get("publication_date") or ""
    match = re.search(r"\b(19|20)\d{2}\b", str(value))
    return match.group(0) if match else ""


def _format_authors(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    names: list[str] = []
    for author in value:
        if isinstance(author, str):
            names.append(author)
        elif isinstance(author, dict):
            name = author.get("name") or author.get("full_name")
            if name:
                names.append(str(name))
    return ", ".join(names)


def build_reference_map(
    papers: list[dict[str, Any]],
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Create one stable, project-scoped citation map for every section."""

    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for paper in papers:
        paper_id = str(paper.get("id") or paper.get("paper_id") or "").strip()
        if not paper_id or paper_id in seen:
            continue
        seen.add(paper_id)
        references.append(
            {
                "number": len(references) + 1,
                "paper_id": paper_id,
                "title": str(paper.get("title") or "Untitled"),
                "authors": _format_authors(paper.get("authors")),
                "year": _paper_year(paper),
                "venue": str(paper.get("journal") or paper.get("venue") or ""),
                "doi": str(paper.get("doi") or ""),
            }
        )
        if len(references) >= limit:
            break
    return references


def validate_citations(
    text: str,
    reference_count: int,
    *,
    allowed_numbers: set[int] | None = None,
) -> CitationValidation:
    """Validate bracketed numeric citations against a fixed reference map."""

    cited: set[int] = set()
    invalid: set[int] = set()
    for match in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", text):
        raw_numbers = match.group(1).split(",")
        if len(raw_numbers) == 1 and 1900 <= int(raw_numbers[0]) <= 2099:
            continue
        for raw_number in raw_numbers:
            number = int(raw_number.strip())
            if 1 <= number <= reference_count:
                cited.add(number)
            else:
                invalid.add(number)
    disallowed = cited - allowed_numbers if allowed_numbers is not None else set()
    return CitationValidation(
        cited_numbers=cited,
        invalid_numbers=invalid,
        disallowed_numbers=disallowed,
    )


def decide_next_phase(state: AgentState) -> str:
    """Return the next phase with bounded retry and revision behavior."""

    if state.terminal_failure:
        return TERMINAL_PHASE
    if state.failed_phase:
        attempts = state.phase_attempts.get(state.failed_phase, 0)
        return (
            state.failed_phase
            if attempts < state.max_phase_attempts
            else TERMINAL_PHASE
        )
    if state.status == "needs_more_research":
        return (
            "research"
            if state.research_round < state.max_research_rounds
            else TERMINAL_PHASE
        )
    if state.status == "needs_revision" or state.needs_revision:
        return (
            "writing"
            if state.revision_attempt < state.max_revision_attempts
            else TERMINAL_PHASE
        )
    if not state.research_complete or not state.papers:
        return "research"
    if not state.analysis_complete:
        return "analysis"
    if not state.writing_complete or not state.final_review:
        return "writing"
    if not state.peer_review_complete:
        return "peer_review"
    return TERMINAL_PHASE


def _phase_failure(
    state: AgentState,
    phase: str,
    error: Exception,
) -> dict[str, Any]:
    attempts = dict(state.phase_attempts)
    attempts[phase] = attempts.get(phase, 0) + 1
    message = f"{phase}: {error!s}"
    terminal = attempts[phase] >= state.max_phase_attempts
    return {
        "current_phase": phase,
        "status": f"{phase}_failed",
        "failed_phase": phase,
        "terminal_failure": terminal,
        "phase_attempts": attempts,
        "errors": [*state.errors, message] if terminal else list(state.errors),
        "warnings": (
            list(state.warnings)
            if terminal
            else [*state.warnings, f"Retrying after {message}"]
        ),
    }


async def _record_decision(
    state: AgentState,
    decision: str,
    reason: str,
) -> None:
    if not state.execution_id:
        return
    try:
        from ..services.database import get_database

        await get_database().record_agent_decision(
            execution_id=state.execution_id,
            project_id=state.project_id,
            agent_name="supervisor",
            decision=decision,
            reason=reason,
        )
    except Exception as error:
        logger.warning(
            "Failed to persist supervisor decision",
            error=str(error),
            project_id=state.project_id,
        )


async def _supervisor_node(state: AgentState) -> dict[str, Any]:
    decision = decide_next_phase(state)
    reason = "phase completion state"
    update: dict[str, Any] = {"current_phase": decision}

    if state.status == "needs_more_research":
        if decision == "research":
            update.update(
                status="running",
                research_complete=False,
                analysis_complete=False,
                embeddings_ready=False,
            )
            reason = "coverage below threshold; supplemental research allowed"
        else:
            message = (
                "Coverage remained below threshold after "
                f"{state.max_research_rounds} research rounds"
            )
            update.update(
                status="failed",
                terminal_failure=True,
                errors=[*state.errors, message],
            )
            reason = message
    elif state.failed_phase:
        attempts = state.phase_attempts.get(state.failed_phase, 0)
        if decision == state.failed_phase:
            update.update(status="running", failed_phase=None)
            reason = f"retry {state.failed_phase} attempt {attempts + 1}"
        else:
            update.update(status="failed", terminal_failure=True)
            reason = f"{state.failed_phase} exhausted {attempts} attempts"
    elif state.status == "needs_revision" or state.needs_revision:
        if decision == "writing":
            update.update(
                status="running",
                writing_complete=False,
                peer_review_complete=False,
            )
            reason = f"peer review requested revision {state.revision_attempt}"
        else:
            update.update(
                status="completed_with_warnings",
                needs_revision=False,
                warnings=[
                    *state.warnings,
                    "Peer-review threshold was not met after all revisions",
                ],
            )
            reason = "revision limit reached; preserving review with warning"
    else:
        update["status"] = "finalizing" if decision == TERMINAL_PHASE else "running"

    update["decision_reason"] = reason
    await _record_decision(state, decision, reason)
    logger.info(
        "Supervisor decision",
        project_id=state.project_id,
        execution_id=state.execution_id,
        decision=decision,
        reason=reason,
    )
    return update


def _route_from_supervisor(state: AgentState) -> str:
    allowed = {*PHASES, TERMINAL_PHASE}
    return state.current_phase if state.current_phase in allowed else TERMINAL_PHASE


async def _research_node(state: AgentState) -> dict[str, Any]:
    project_token = push_current_project(state.project_id)
    execution_token = push_current_execution(state.execution_id)
    phase_token = push_current_agent_phase("research")
    started = time.monotonic()
    try:
        from .research_team import run_research

        result = await run_research(
            topic=state.topic,
            project_id=state.project_id,
            target_papers=state.target_papers,
            supplemental_queries=state.suggested_queries,
        )
        papers = result.get("papers") or []
        if not papers:
            raise RuntimeError("research completed without any project papers")
        paper_ids = [
            str(paper.get("id") or paper.get("paper_id") or "")
            for paper in papers
            if paper.get("id") or paper.get("paper_id")
        ]
        return {
            "current_phase": "research",
            "status": "running",
            "papers": papers,
            "paper_ids": paper_ids,
            "research_summary": {
                key: value for key, value in result.items() if key != "papers"
            },
            "research_complete": True,
            "research_round": state.research_round + 1,
            "suggested_queries": [],
            "failed_phase": None,
            "terminal_failure": False,
        }
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Research phase failed", project_id=state.project_id)
        return _phase_failure(state, "research", error)
    finally:
        pop_current_agent_phase(phase_token)
        pop_current_execution(execution_token)
        pop_current_project(project_token)
        logger.info(
            "Research phase finished",
            project_id=state.project_id,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )


async def _analysis_node(state: AgentState) -> dict[str, Any]:
    project_token = push_current_project(state.project_id)
    execution_token = push_current_execution(state.execution_id)
    phase_token = push_current_agent_phase("analysis")
    warnings = list(state.warnings)
    try:
        if not state.papers:
            raise RuntimeError("analysis requires project-scoped papers")

        from ..services.embedding_service import (
            ensure_paper_embeddings,
            get_active_embedding_model,
        )
        from ..tools.agent_tools import (
            analyze_gaps_from_evidence,
            cluster_and_evaluate_coverage,
            extract_knowledge_graph,
            generate_evidence,
        )

        embedding_model = get_active_embedding_model()
        embedding_count = await ensure_paper_embeddings(
            state.papers,
            model_name=embedding_model,
        )
        expected_embeddings = len(
            {
                str(paper.get("id") or paper.get("paper_id"))
                for paper in state.papers
                if paper.get("id") or paper.get("paper_id")
            }
        )
        if embedding_count != expected_embeddings:
            raise RuntimeError(
                f"only {embedding_count}/{expected_embeddings} project papers "
                "have embeddings"
            )

        coverage_raw = await cluster_and_evaluate_coverage.ainvoke(
            {
                "topic": state.topic,
                "target_papers": state.target_papers,
                "embedding_model": embedding_model,
            }
        )
        coverage = json.loads(coverage_raw)
        if coverage.get("error"):
            raise RuntimeError(str(coverage["error"]))
        coverage_score = float(coverage.get("coverage_score", 0.0))
        suggested_queries = [
            str(query)
            for query in coverage.get("suggested_new_queries", [])
            if str(query).strip()
        ]
        cluster_save_failures = int(coverage.get("cluster_save_failures") or 0)
        if cluster_save_failures:
            warnings.append(
                f"Cluster persistence failed for {cluster_save_failures} clusters"
            )
        if coverage_score < 0.55:
            return {
                "current_phase": "analysis",
                "status": "needs_more_research",
                "embeddings_ready": True,
                "embedding_model": embedding_model,
                "coverage": coverage,
                "coverage_score": coverage_score,
                "suggested_queries": suggested_queries or [state.topic],
                "analysis_complete": False,
                "failed_phase": None,
                "terminal_failure": False,
                "warnings": warnings,
            }

        papers_json = json.dumps(
            [
                {
                    "id": paper.get("id"),
                    "title": paper.get("title"),
                    "abstract": paper.get("abstract"),
                }
                for paper in state.papers
            ],
            ensure_ascii=False,
        )

        knowledge_graph: dict[str, Any] = {}
        try:
            kg_raw = await extract_knowledge_graph.ainvoke({"papers_json": papers_json})
            knowledge_graph = json.loads(kg_raw)
            if knowledge_graph.get("error"):
                warnings.append(f"Knowledge graph: {knowledge_graph['error']}")
            truncated_papers = int(knowledge_graph.get("truncated_papers") or 0)
            if truncated_papers:
                warnings.append(
                    "Knowledge graph extraction budget skipped "
                    f"{truncated_papers} lower-priority papers"
                )
        except Exception as error:
            warnings.append(f"Knowledge graph extraction degraded: {error!s}")

        evidence_raw = await generate_evidence.ainvoke(
            {"papers_json": papers_json, "topic": state.topic}
        )
        evidence_result = json.loads(evidence_raw)
        if evidence_result.get("error"):
            raise RuntimeError(str(evidence_result["error"]))
        evidence_cards = evidence_result.get("evidence_cards") or []
        if not evidence_cards:
            raise RuntimeError("evidence generation returned no cards")
        fallback_count = int(evidence_result.get("fallback_count") or 0)
        if fallback_count:
            warnings.append(
                "Evidence extraction discarded "
                f"{fallback_count} transient fallback cards"
            )
        save_failures = int(evidence_result.get("save_failures") or 0)
        if save_failures:
            warnings.append(
                f"Evidence persistence skipped {save_failures} invalid cards"
            )

        claims_json = json.dumps(
            [
                {"claim": card.get("claim", "")}
                for card in evidence_cards[:20]
                if isinstance(card, dict)
            ],
            ensure_ascii=False,
        )
        gaps_raw = await analyze_gaps_from_evidence.ainvoke(
            {
                "topic": state.topic,
                "evidence_count": len(evidence_cards),
                "key_claims_json": claims_json,
            }
        )
        gaps = json.loads(gaps_raw)
        if gaps.get("error"):
            warnings.append(f"Gap analysis degraded: {gaps['error']}")

        return {
            "current_phase": "analysis",
            "status": "running",
            "embeddings_ready": True,
            "embedding_model": embedding_model,
            "coverage": coverage,
            "coverage_score": coverage_score,
            "knowledge_graph": knowledge_graph,
            "evidence_cards": evidence_cards,
            "gap_analysis": gaps,
            "analysis_complete": True,
            "failed_phase": None,
            "terminal_failure": False,
            "warnings": warnings,
        }
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Analysis phase failed", project_id=state.project_id)
        return _phase_failure(state, "analysis", error)
    finally:
        pop_current_agent_phase(phase_token)
        pop_current_execution(execution_token)
        pop_current_project(project_token)


def _build_abstract(sections: list[dict[str, Any]]) -> str:
    """Build the persisted abstract from section opening claims."""

    abstract_parts: list[str] = []
    for section in sections:
        content = str(section.get("content") or "")
        first_paragraph = content.split("\n\n")[0].strip()
        if len(first_paragraph) > 30:
            abstract_parts.append(first_paragraph[:240])
        if sum(map(len, abstract_parts)) >= 500:
            break
    return "；".join(abstract_parts) if abstract_parts else "本综述暂无可用摘要。"


def _remap_citation_numbers(
    text: str,
    number_map: dict[int, int],
    *,
    keep_unmapped: bool = False,
) -> str:
    """Apply the final first-use numbering to one persisted section."""

    def replace(match: re.Match[str]) -> str:
        raw_numbers = [int(value.strip()) for value in match.group(1).split(",")]
        if len(raw_numbers) == 1 and 1900 <= raw_numbers[0] <= 2099:
            return match.group(0)
        mapped = [
            number_map.get(number, number if keep_unmapped else None)
            for number in raw_numbers
        ]
        mapped = [number for number in mapped if number is not None]
        return "[" + ",".join(map(str, dict.fromkeys(mapped))) + "]" if mapped else ""

    return re.sub(r"\[(\d+(?:\s*,\s*\d+)*)\]", replace, text)


def _clean_section_output(value: Any) -> str:
    """Remove model-only commentary and section-local rendering artifacts."""

    text = str(value or "").strip()
    text = re.sub(r"^\s*```(?:markdown|md|text)?\s*\n?", "", text, flags=re.I)
    text = re.sub(r"\n?\s*```\s*$", "", text)
    text = strip_revision_commentary(text)
    text = strip_meta_commentary(text)
    text = strip_prompt_leakage(text)
    text = strip_section_reference_block(text)
    text = strip_body_structure_leakage(text)
    return normalize_citation_surface(text)


def _word_units(text: str) -> int:
    """Count CJK characters and non-CJK word tokens on a comparable scale."""

    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    non_cjk = re.sub(r"[\u4e00-\u9fff]", " ", text)
    return cjk_count + len(re.findall(r"\b[\w'-]+\b", non_cjk, flags=re.UNICODE))


def _minimum_review_word_units(target_words: int) -> int:
    return min(target_words, max(300, math.ceil(target_words * 0.40)))


def _relevance_tokens(value: Any) -> set[str]:
    text = str(value or "").casefold()
    tokens = set(re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text))
    cjk = "".join(char for char in text if "\u4e00" <= char <= "\u9fff")
    tokens.update(cjk[index : index + 2] for index in range(max(0, len(cjk) - 1)))
    return tokens


def _build_section_sources(
    plan: dict[str, Any],
    references: list[dict[str, Any]],
    papers: list[dict[str, Any]],
    evidence_cards: list[dict[str, Any]],
    *,
    limit: int = 18,
    preferred_paper_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Select grounded evidence while preserving global reference numbers."""

    papers_by_id = {
        str(paper.get("id") or paper.get("paper_id")): paper for paper in papers
    }
    cards_by_paper: dict[str, list[dict[str, Any]]] = {}
    for card in evidence_cards:
        paper_id = str(card.get("paper_id") or "")
        if paper_id:
            cards_by_paper.setdefault(paper_id, []).append(card)

    query_tokens = _relevance_tokens(
        " ".join(
            [
                str(plan.get("title") or ""),
                str(plan.get("description") or ""),
                " ".join(str(value) for value in plan.get("key_points") or []),
            ]
        )
    )
    preferred_order = {
        paper_id: index for index, paper_id in enumerate(preferred_paper_ids or [])
    }
    candidate_references = (
        [
            reference
            for reference in references
            if str(reference.get("paper_id") or "") in preferred_order
        ]
        if preferred_order
        else list(references)
    )
    candidate_references.sort(
        key=lambda reference: preferred_order.get(
            str(reference.get("paper_id") or ""),
            len(preferred_order),
        )
    )

    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for position, reference in enumerate(candidate_references):
        paper_id = str(reference.get("paper_id") or "")
        paper = papers_by_id.get(paper_id, {})
        cards = cards_by_paper.get(paper_id, [])
        evidence_claims = [
            str(card.get("claim") or card.get("evidence_span") or "")[:400]
            for card in cards[:3]
            if card.get("claim") or card.get("evidence_span")
        ]
        source = {
            **reference,
            "abstract": str(paper.get("abstract") or "")[:900],
            "evidence_claims": evidence_claims,
        }
        source_tokens = _relevance_tokens(
            " ".join(
                [
                    str(reference.get("title") or ""),
                    source["abstract"],
                    " ".join(evidence_claims),
                ]
            )
        )
        ranked.append((len(query_tokens & source_tokens), position, source))

    if not preferred_order:
        ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = ranked[: max(1, min(limit, len(ranked)))]
    return [source for _score, _position, source in selected]


async def _write_new_sections(
    state: AgentState,
    outline: dict[str, Any],
    references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from ..services.citation_planner import plan_review_citations
    from ..services.section_evidence_planner import plan_section_evidence
    from ..tools.agent_tools import write_section

    plans = outline.get("sections") or []
    if not isinstance(plans, list) or not plans:
        raise RuntimeError("writing agent returned an empty outline")

    reference_ids = {str(reference.get("paper_id") or "") for reference in references}
    planner_papers = [
        paper
        for paper in state.papers
        if str(paper.get("id") or paper.get("paper_id") or "") in reference_ids
    ]
    clusters = state.coverage.get("clusters") or []
    if not isinstance(clusters, list):
        clusters = []
    citation_plans = plan_review_citations(
        plans,
        planner_papers,
        clusters,
        section_reference_target=min(18, len(references)),
        core_reference_count=min(30, len(references)),
    )
    _filtered_plans, evidence_plans = plan_section_evidence(
        topic=state.topic,
        sections=plans,
        citation_plans=citation_plans,
        evidence_cards=state.evidence_cards,
        paper_map={
            str(paper.get("id") or paper.get("paper_id") or ""): paper
            for paper in planner_papers
        },
        clusters=clusters,
        max_references_per_section=min(18, len(references)),
        min_references_per_section=min(8, len(references)),
    )
    semaphore = asyncio.Semaphore(3)

    async def write_one(index: int, plan: dict[str, Any]) -> dict[str, Any]:
        sources = _build_section_sources(
            plan,
            references,
            state.papers,
            state.evidence_cards,
            preferred_paper_ids=list(
                evidence_plans.get(index, {}).get("selected_paper_ids") or []
            ),
        )
        async with semaphore:
            content = await write_section.ainvoke(
                {
                    "topic": state.topic,
                    "section_title": str(plan.get("title") or f"Section {index + 1}"),
                    "section_plan_json": json.dumps(plan, ensure_ascii=False),
                    "available_papers_json": json.dumps(sources, ensure_ascii=False),
                }
            )
        text = _clean_section_output(content)
        if len(text) < 100:
            raise RuntimeError(
                f"section {index + 1} returned insufficient content ({len(text)} chars)"
            )
        return {
            "section_id": str(plan.get("id") or index + 1),
            "title": str(plan.get("title") or f"Section {index + 1}"),
            "content": text,
            "target_words": int(plan.get("target_words") or 0),
            "allowed_reference_numbers": sorted(
                {
                    int(source["number"])
                    for source in sources
                    if int(source.get("number") or 0) > 0
                }
            ),
        }

    tasks: list[asyncio.Task[dict[str, Any]]] = []
    async with asyncio.TaskGroup() as task_group:
        tasks = [
            task_group.create_task(
                write_one(index, plan),
                name=f"agent-write-section:{state.execution_id}:{index}",
            )
            for index, plan in enumerate(plans)
        ]
    return [task.result() for task in tasks]


async def _revise_sections(state: AgentState) -> list[dict[str, Any]]:
    from ..tools.agent_tools import revise_section

    if not state.sections:
        raise RuntimeError("revision requested without existing sections")
    semaphore = asyncio.Semaphore(3)
    restore_map = {
        int(reference["new_number"]): int(reference["original_number"])
        for reference in state.final_references
        if reference.get("new_number") and reference.get("original_number")
    }
    instructions = state.revision_feedback or "Improve rigor, evidence, and citations."
    if restore_map:
        instructions = _remap_citation_numbers(
            instructions,
            restore_map,
            keep_unmapped=True,
        )
    source_sections = (
        [
            {
                **section,
                "content": _remap_citation_numbers(
                    str(section.get("content") or ""),
                    restore_map,
                ),
            }
            for section in state.sections
        ]
        if restore_map
        else list(state.sections)
    )

    async def revise_one(section: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            content = await revise_section.ainvoke(
                {
                    "section_text": str(section.get("content") or ""),
                    "revision_instructions": instructions,
                }
            )
        text = _clean_section_output(content)
        if len(text) < 100:
            raise RuntimeError(
                f"revision for {section.get('title', 'section')} was too short"
            )
        return {**section, "content": text}

    tasks: list[asyncio.Task[dict[str, Any]]] = []
    async with asyncio.TaskGroup() as task_group:
        tasks = [
            task_group.create_task(
                revise_one(section),
                name=(
                    "agent-revise-section:"
                    f"{state.execution_id}:{section.get('section_id', index)}"
                ),
            )
            for index, section in enumerate(source_sections)
        ]
    return [task.result() for task in tasks]


async def _persist_writing_artifacts(
    state: AgentState,
    outline: dict[str, Any],
    sections: list[dict[str, Any]],
) -> None:
    from ..services.database import get_database

    db = get_database()
    outline_id = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"academic-cluster:outline:{state.project_id}")
    )
    active_section_ids = [
        str(section.get("section_id") or index)
        for index, section in enumerate(sections, 1)
    ]
    await db.save_outline(
        {
            "id": outline_id,
            "project_id": state.project_id,
            "title": outline.get("title") or state.topic,
            "sections": outline.get("sections") or [],
            "active_section_ids": active_section_ids,
            "status": "approved",
            "version": max(1, state.revision_attempt + 1),
        }
    )
    for index, section in enumerate(sections, 1):
        await db.save_written_section(
            {
                "outline_id": outline_id,
                "section_id": str(section.get("section_id") or index),
                "content": section.get("content") or "",
                "word_count": _word_units(str(section.get("content") or "")),
                "quality_score": state.quality_score or 0.0,
                "version": max(1, state.revision_attempt + 1),
            }
        )


async def _writing_node(state: AgentState) -> dict[str, Any]:
    project_token = push_current_project(state.project_id)
    execution_token = push_current_execution(state.execution_id)
    phase_token = push_current_agent_phase("writing")
    try:
        references = state.reference_map or build_reference_map(state.papers)
        if not references:
            raise RuntimeError("writing requires a non-empty project reference map")

        is_revision = state.needs_revision
        if is_revision:
            outline = state.outline
            sections = await _revise_sections(state)
        else:
            from .writing_team import run_writing

            result = await run_writing(
                topic=state.topic,
                evidence_cards=state.evidence_cards,
                target_words=state.target_words,
            )
            outline = result.get("outline") or {}
            sections = await _write_new_sections(state, outline, references)

        for index, section in enumerate(sections, 1):
            raw_allowed = section.get("allowed_reference_numbers")
            allowed_numbers = (
                {
                    int(number)
                    for number in raw_allowed
                    if 1 <= int(number) <= len(references)
                }
                if isinstance(raw_allowed, list)
                else None
            )
            section_validation = validate_citations(
                str(section.get("content") or ""),
                len(references),
                allowed_numbers=allowed_numbers,
            )
            if section_validation.invalid_numbers:
                numbers = ", ".join(
                    map(str, sorted(section_validation.invalid_numbers))
                )
                raise RuntimeError(
                    f"section {index} contains invalid citation numbers: {numbers}"
                )
            if section_validation.disallowed_numbers:
                numbers = ", ".join(
                    map(str, sorted(section_validation.disallowed_numbers))
                )
                raise RuntimeError(
                    f"section {index} cites numbers outside its evidence plan: {numbers}"
                )
            if not section_validation.cited_numbers:
                raise RuntimeError(f"section {index} contains no verifiable citations")

        actual_word_units = sum(
            _word_units(str(section.get("content") or "")) for section in sections
        )
        required_word_units = _minimum_review_word_units(state.target_words)
        if actual_word_units < required_word_units:
            raise RuntimeError(
                "generated review body is below required minimum: "
                f"{actual_word_units}/{required_word_units} word units"
            )

        body_text = "\n\n".join(
            str(section.get("content") or "") for section in sections
        )
        citation_result = validate_citations(body_text, len(references))
        if citation_result.invalid_numbers:
            numbers = ", ".join(map(str, sorted(citation_result.invalid_numbers)))
            raise RuntimeError(f"invalid citation numbers: {numbers}")
        if not citation_result.cited_numbers:
            raise RuntimeError("generated review body contains no verifiable citations")

        from ..services.review_finalizer import finalize_review_markdown

        abstract = _build_abstract(sections)
        finalized = finalize_review_markdown(
            review_title=str(outline.get("title") or f"综述：{state.topic}"),
            sections=list(outline.get("sections") or []),
            section_bodies=[str(section.get("content") or "") for section in sections],
            paper_metadata_map={
                int(reference["number"]): reference for reference in references
            },
            abstract=abstract,
        )
        number_map = {
            int(reference["original_number"]): int(reference["new_number"])
            for reference in finalized.reference_mappings
        }
        sections = [
            {
                **section,
                "title": _remap_citation_numbers(
                    str(section.get("title") or ""),
                    number_map,
                    keep_unmapped=True,
                ),
                "content": _remap_citation_numbers(
                    str(section.get("content") or ""),
                    number_map,
                ),
            }
            for section in sections
        ]
        outline = {
            **outline,
            "title": _remap_citation_numbers(
                str(outline.get("title") or f"综述：{state.topic}"),
                number_map,
                keep_unmapped=True,
            ),
            "sections": [
                {
                    **plan,
                    "title": _remap_citation_numbers(
                        str(plan.get("title") or ""),
                        number_map,
                        keep_unmapped=True,
                    ),
                }
                for plan in list(outline.get("sections") or [])
            ],
        }
        final_references = finalized.reference_mappings
        abstract = _remap_citation_numbers(
            abstract,
            number_map,
            keep_unmapped=True,
        )
        final_review = finalized.markdown
        cited_numbers = sorted(
            int(reference["new_number"]) for reference in final_references
        )

        await _persist_writing_artifacts(state, outline, sections)
        return {
            "current_phase": "writing",
            "status": "running",
            "outline": outline,
            "sections": sections,
            "reference_map": references,
            "cited_reference_numbers": cited_numbers,
            "final_references": final_references,
            "abstract": abstract,
            "final_review": final_review,
            "writing_complete": True,
            "needs_revision": False,
            "revision_feedback": "",
            "peer_review_complete": False,
            "revision_attempt": (
                state.revision_attempt + 1 if is_revision else state.revision_attempt
            ),
            "failed_phase": None,
            "terminal_failure": False,
        }
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Writing phase failed", project_id=state.project_id)
        return _phase_failure(state, "writing", error)
    finally:
        pop_current_agent_phase(phase_token)
        pop_current_execution(execution_token)
        pop_current_project(project_token)


async def _peer_review_node(state: AgentState) -> dict[str, Any]:
    project_token = push_current_project(state.project_id)
    execution_token = push_current_execution(state.execution_id)
    phase_token = push_current_agent_phase("peer_review")
    try:
        if not state.final_review:
            raise RuntimeError("peer review requires generated review text")

        from .peer_review_team import run_peer_review, validate_peer_review_report

        result = await run_peer_review(
            review_text=state.final_review,
            topic=state.topic,
        )
        report = validate_peer_review_report(result.get("review_report") or {})
        score = report["overall_score"]
        suggestions = report.get("suggestions") or report.get("weaknesses") or []
        feedback = "\n".join(str(item) for item in suggestions if str(item).strip())

        if score < state.quality_threshold:
            if state.revision_attempt < state.max_revision_attempts:
                return {
                    "current_phase": "peer_review",
                    "status": "needs_revision",
                    "peer_review_report": report,
                    "quality_score": score,
                    "peer_review_complete": False,
                    "needs_revision": True,
                    "revision_feedback": feedback,
                    "failed_phase": None,
                }
            return {
                "current_phase": "peer_review",
                "status": "completed_with_warnings",
                "peer_review_report": report,
                "quality_score": score,
                "peer_review_complete": True,
                "needs_revision": False,
                "warnings": [
                    *state.warnings,
                    (
                        f"Peer-review score {score:.1f} remained below "
                        f"threshold {state.quality_threshold:.1f}"
                    ),
                ],
                "failed_phase": None,
            }

        return {
            "current_phase": "peer_review",
            "status": "running",
            "peer_review_report": report,
            "quality_score": score,
            "peer_review_complete": True,
            "needs_revision": False,
            "failed_phase": None,
            "terminal_failure": False,
        }
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Peer-review phase failed", project_id=state.project_id)
        return _phase_failure(state, "peer_review", error)
    finally:
        pop_current_agent_phase(phase_token)
        pop_current_execution(execution_token)
        pop_current_project(project_token)


async def _finalize_node(state: AgentState) -> dict[str, Any]:
    from ..services.database import get_database

    if state.terminal_failure or not state.final_review:
        final_status = "failed"
    elif state.status == "completed_with_warnings" or state.warnings:
        final_status = "completed_with_warnings"
    else:
        final_status = "completed"

    if state.final_review:
        snapshot = {
            "final_review": state.final_review,
            "body_markdown": state.final_review,
            "references": state.final_references,
            "abstract": state.abstract,
            "outline": state.outline,
            "peer_review": state.peer_review_report,
            "quality_score": state.quality_score,
            "coverage": state.coverage,
            "warnings": state.warnings,
        }
        await get_database().save_pipeline_checkpoint(
            {
                "project_id": state.project_id,
                "node_name": "final_review_artifact",
                "state_snapshot": snapshot,
                "status": final_status,
            }
        )

    return {"current_phase": "completed", "status": final_status}


def _create_agent_graph() -> StateGraph[AgentState]:
    workflow = StateGraph(AgentState)
    workflow.add_node("supervisor", _supervisor_node)
    workflow.add_node("research", _research_node)
    workflow.add_node("analysis", _analysis_node)
    workflow.add_node("writing", _writing_node)
    workflow.add_node("peer_review", _peer_review_node)
    workflow.add_node("finalize", _finalize_node)
    workflow.set_entry_point("supervisor")
    workflow.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "research": "research",
            "analysis": "analysis",
            "writing": "writing",
            "peer_review": "peer_review",
            "finalize": "finalize",
        },
    )
    for phase in PHASES:
        workflow.add_edge(phase, "supervisor")
    workflow.add_edge("finalize", END)
    return workflow


_compiled_graph: CompiledStateGraph[AgentState, Any, Any, Any] | None = None
_graph_checkpointer: BaseCheckpointSaver[Any] | None = None


async def compile_agent_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    *,
    force: bool = False,
) -> CompiledStateGraph[AgentState, Any, Any, Any]:
    """Compile once; the application supplies a persistent checkpointer."""

    global _compiled_graph, _graph_checkpointer
    if (
        _compiled_graph is not None
        and not force
        and (checkpointer is None or checkpointer is _graph_checkpointer)
    ):
        return _compiled_graph

    if checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver

        checkpointer = InMemorySaver()
        logger.warning(
            "Agent graph initialized with InMemorySaver; resume is process-local"
        )

    _graph_checkpointer = checkpointer
    _compiled_graph = _create_agent_graph().compile(checkpointer=checkpointer)
    return _compiled_graph


async def reset_agent_graph() -> None:
    """Drop the compiled graph; checkpointer lifetime is owned by the app."""

    global _compiled_graph, _graph_checkpointer
    _compiled_graph = None
    _graph_checkpointer = None


def agent_thread_prefix(project_id: str) -> str:
    """Return the stable LangGraph thread prefix for one project."""

    return f"academic-cluster:agent:v1:{project_id}:"


def agent_thread_id(project_id: str, execution_id: str) -> str:
    """Return the isolated LangGraph thread ID for one execution."""

    if not execution_id:
        raise ValueError("execution_id is required for checkpoint isolation")
    return f"{agent_thread_prefix(project_id)}{execution_id}"


def _thread_config(project_id: str, execution_id: str) -> RunnableConfig:
    if not execution_id:
        raise ValueError("execution_id is required for checkpoint isolation")
    return {
        "configurable": {
            "thread_id": agent_thread_id(project_id, execution_id),
            "checkpoint_ns": "",
        },
        "recursion_limit": 60,
    }


async def run_agent_graph(
    *,
    topic: str,
    project_id: str,
    execution_id: str,
    target_papers: int = 50,
    target_words: int = 12000,
    model_name: str = "provider-default",
    quality_threshold: float = 75.0,
    resume: bool = False,
    sse_manager: Any = None,
) -> AgentState:
    """Run or resume one execution using its isolated checkpoint thread."""

    del model_name  # Backward-compatible argument; routing belongs to Provider Pool.
    from ..services.database import get_database

    db = get_database()
    graph = await compile_agent_graph()
    config = _thread_config(project_id, execution_id)
    input_data: AgentState | None
    if resume:
        snapshot = await graph.aget_state(config)
        if not snapshot.values:
            raise ValueError(f"No checkpoint found for execution {execution_id}")
        input_data = None
    else:
        input_data = AgentState(
            project_id=project_id,
            execution_id=execution_id,
            topic=topic,
            target_papers=target_papers,
            target_words=target_words,
            quality_threshold=quality_threshold,
        )

    await db.update_project_status(project_id, "running:agent:supervisor")
    project_token = push_current_project(project_id)
    execution_token = push_current_execution(execution_id)
    try:
        async for event in graph.astream(
            input_data,
            config=config,
            stream_mode="updates",
        ):
            for node_name, node_output in event.items():
                if not isinstance(node_output, dict):
                    continue
                phase = str(node_output.get("current_phase") or node_name)
                if phase != "completed":
                    await db.update_project_status(
                        project_id,
                        f"running:agent:{phase}",
                    )
                if sse_manager is not None:
                    await sse_manager.send_progress(
                        project_id=project_id,
                        node=node_name,
                        status=str(node_output.get("status") or "running"),
                        message=f"Agent phase: {phase}",
                    )

        snapshot = await graph.aget_state(config)
        if not snapshot.values:
            raise RuntimeError("agent graph completed without a final state")
        final_state = AgentState.model_validate(snapshot.values)
        project_status = "failed" if final_state.status == "failed" else "completed"
        await db.update_project_status(project_id, project_status)
        if sse_manager is not None:
            await sse_manager.send_complete(
                project_id,
                {
                    "status": final_state.status,
                    "warnings": final_state.warnings,
                    "errors": final_state.errors,
                    "quality_score": final_state.quality_score,
                },
            )
        return final_state
    except asyncio.CancelledError:
        await db.update_project_status(project_id, "interrupted")
        raise
    except Exception as error:
        logger.exception(
            "Agent graph execution failed",
            project_id=project_id,
            execution_id=execution_id,
        )
        await db.update_project_status(project_id, "failed")
        if sse_manager is not None:
            await sse_manager.send_error(project_id, str(error))
        raise
    finally:
        pop_current_execution(execution_token)
        pop_current_project(project_token)
