"""Thin application facade for the persistent multi-agent graph."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


class OrchestratorAgent:
    """Coordinate one complete graph execution."""

    def __init__(
        self,
        model_name: str = "provider-default",
        quality_threshold: float = 75.0,
    ) -> None:
        del model_name  # Backward-compatible argument; Provider Pool owns routing.
        self.quality_threshold = quality_threshold

    async def run(
        self,
        *,
        topic: str,
        project_id: str,
        execution_id: str,
        target_papers: int = 50,
        target_words: int = 12000,
        resume: bool = False,
        sse_manager: Any = None,
    ) -> dict[str, Any]:
        """Run or resume the only supported orchestrator mode."""

        from .agent_graph import run_agent_graph

        final_state = await run_agent_graph(
            topic=topic,
            project_id=project_id,
            execution_id=execution_id,
            target_papers=target_papers,
            target_words=target_words,
            quality_threshold=self.quality_threshold,
            resume=resume,
            sse_manager=sse_manager,
        )
        logger.info(
            "Orchestrator execution finished",
            project_id=project_id,
            execution_id=execution_id,
            status=final_state.status,
        )
        return {
            "project_id": final_state.project_id,
            "execution_id": final_state.execution_id,
            "topic": final_state.topic,
            "status": final_state.status,
            "current_phase": final_state.current_phase,
            "papers": final_state.papers,
            "coverage": final_state.coverage,
            "knowledge_graph": final_state.knowledge_graph,
            "evidence_cards": final_state.evidence_cards,
            "outline": final_state.outline,
            "sections": final_state.sections,
            "references": final_state.final_references,
            "abstract": final_state.abstract,
            "final_review": final_state.final_review,
            "peer_review": final_state.peer_review_report,
            "quality_score": final_state.quality_score,
            "warnings": final_state.warnings,
            "errors": final_state.errors,
        }


def create_orchestrator(
    model_name: str = "provider-default",
    quality_threshold: float = 75.0,
) -> OrchestratorAgent:
    """Create the graph facade."""

    return OrchestratorAgent(
        model_name=model_name,
        quality_threshold=quality_threshold,
    )
