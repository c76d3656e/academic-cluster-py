"""Cross-community conflict analysis node.

Compares research communities to identify conflicts, divergences,
consensus, and open debates between them.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from ...prompts import get_inter_community_conflict_prompt
from ...services.database import get_database
from ...services.llm_client import ainvoke_with_callbacks, create_llm
from ...services.observability import get_current_tracker
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()


def _json_text(value: Any, max_chars: int = 500) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_chars]


async def inter_community_conflict_node(
    state: PipelineState,
) -> dict[str, Any]:
    """Analyze conflicts and relationships between research communities."""
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("inter_community_conflict", "llm", index=6)

    logger.info("Starting inter-community conflict analysis")

    db = get_database()

    try:
        clusters = await db.get_clusters_by_ids(state.cluster_ids)
        memories = await db.get_community_memories_by_project(state.project_id)

        if len(clusters) < 2:
            logger.info("Less than 2 clusters, skipping conflict analysis")
            if tracker:
                await tracker.end_node(
                    "inter_community_conflict",
                    "succeeded",
                    output_summary={
                        "relationships": 0,
                        "reason": "less_than_2_clusters",
                    },
                )
            return {
                "inter_community_conflict": None,
                "status": "conflict_skipped",
            }

        # Build community summaries for the prompt
        memory_by_cluster: dict[str, dict[str, Any]] = {}
        for mem in memories:
            cid = str(mem.get("cluster_id", ""))
            if cid:
                memory_by_cluster[cid] = mem

        community_lines = []
        for cluster in clusters:
            cid = str(cluster.get("id"))
            mem = memory_by_cluster.get(cid, {})
            summary = mem.get("community_summary", "")
            method_families = mem.get("method_families", [])
            claims = mem.get("representative_claims", [])
            limitations = mem.get("limitations", [])

            # Extract key claims text
            claim_texts = []
            for c in claims[:6]:
                claim_text = c.get("claim", "")
                role = c.get("synthesis_role", "")
                if claim_text:
                    claim_texts.append(f"[{role}] {claim_text}")

            community_lines.append(
                {
                    "cluster_id": cid,
                    "name": cluster.get("name", ""),
                    "paper_count": len(cluster.get("paper_ids", [])),
                    "summary": _json_text(summary, 400),
                    "method_families": method_families[:5],
                    "key_claims": claim_texts,
                    "limitations": limitations[:5],
                }
            )

        prompt_template = get_inter_community_conflict_prompt()
        prompt = prompt_template.format(
            topic=state.query,
            communities=json.dumps(community_lines, ensure_ascii=False, indent=2),
        )

        llm = create_llm(temperature=0.2, max_tokens=2048)
        response = await ainvoke_with_callbacks(
            llm,
            [
                SystemMessage(
                    content="You are an expert academic meta-analyst. Return only strict JSON."
                ),
                HumanMessage(content=prompt),
            ],
            timeout=300,
        )

        # Parse response
        from ...tools.json_repair import try_parse_json

        raw = response.content
        if isinstance(raw, list):
            raw = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in raw
            )
        result = try_parse_json(raw)

        if not isinstance(result, dict):
            result = {"relationships": [], "synthesis": "", "research_gaps": []}

        relationships = result.get("relationships", [])
        synthesis = result.get("synthesis", "")
        research_gaps = result.get("research_gaps", [])

        conflict_result = {
            "relationships": relationships,
            "synthesis": synthesis,
            "research_gaps": research_gaps,
            "community_count": len(clusters),
        }

        logger.info(
            "Inter-community conflict analysis completed",
            relationships=len(relationships),
            community_count=len(clusters),
        )

        await send_progress(
            state.project_id,
            "inter_community_conflict",
            f"跨社区分析完成，发现 {len(relationships)} 组关系",
        )

        if tracker:
            await tracker.end_node(
                "inter_community_conflict",
                "succeeded",
                output_summary={
                    "relationships": len(relationships),
                    "community_count": len(clusters),
                },
            )

        return {
            "inter_community_conflict": conflict_result,
            "status": "conflict_analyzed",
        }

    except Exception as e:
        import traceback

        if tracker:
            await tracker.end_node(
                "inter_community_conflict",
                "failed",
                error_message=str(e),
                error_traceback=traceback.format_exc(),
            )
        logger.error("Inter-community conflict analysis failed", error=str(e))
        raise
