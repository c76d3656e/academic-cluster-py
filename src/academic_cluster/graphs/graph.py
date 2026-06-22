"""
LangGraph 图定义
定义 Pipeline 图、子图，以及节点间的边和条件路由。
使用 AsyncPostgresSaver 实现持久化 checkpoint，支持断点恢复。
集成 PipelineTracker 实现可观测性。
"""

import contextlib

import structlog
from langgraph.graph import END, StateGraph

from ..services.observability import (
    LLMCallbackHandler,
    PipelineTracker,
    pop_current_project,
    pop_run_id,
    push_current_project,
    push_run_id,
    set_current_llm_callback,
    set_current_tracker,
)
from .checkpoint import with_audit
from .nodes import (
    artifact_registration_node,
    bm25_node,
    community_detection_node,
    community_memory_node,
    coverage_audit_node,
    deduplicate_node,
    embedding_node,
    evidence_cards_node,
    filter_node,
    finalize_node,
    gap_analysis_node,
    generate_abstract_node,
    kg_extraction_node,
    outline_generation_node,
    pgvector_knn_node,
    rerank_node,
    search_node,
    section_revision_node,
    targeted_refine_node,
    user_confirm_node,
    visualize_community_node,
    write_review_node,
)
from .state import PipelineState

logger = structlog.get_logger()


# =============================================================================
# Checkpointer 绠＄悊
# =============================================================================

_default_checkpointer = None


async def get_checkpointer():
    """Get or create the graph checkpointer."""
    global _default_checkpointer
    if _default_checkpointer is not None:
        return _default_checkpointer

    try:
        # Enable numpy serialization when ormsgpack is available. This is optional;
        # checkpoint persistence must not fall back to memory only because this patch fails.
        try:
            import ormsgpack
            from langgraph.checkpoint.serde import jsonplus as _serde_mod
            if hasattr(_serde_mod, '_option'):
                _serde_mod._option = _serde_mod._option | ormsgpack.OPT_SERIALIZE_NUMPY
                logger.info("Patched msgpack options: OPT_SERIALIZE_NUMPY enabled")
        except Exception as patch_error:
            logger.warning("Skipping msgpack numpy patch", error=str(patch_error))

        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        from ..config import get_settings

        settings = get_settings()
        conn_string = (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )

        conn = await AsyncConnection.connect(
            conn_string, autocommit=True, prepare_threshold=0, row_factory=dict_row
        )
        checkpointer = AsyncPostgresSaver(conn)
        await checkpointer.setup()
        _default_checkpointer = checkpointer

        logger.info("AsyncPostgresSaver initialized", host=settings.postgres_host, db=settings.postgres_db)
        return checkpointer
    except Exception as e:
        logger.warning("AsyncPostgresSaver unavailable, using MemorySaver fallback", error=str(e))
        from langgraph.checkpoint.memory import MemorySaver
        _default_checkpointer = MemorySaver()
        return _default_checkpointer


async def close_checkpointer():
    """Close the graph checkpointer."""
    global _default_checkpointer
    if _default_checkpointer is not None:
        try:
            conn = getattr(_default_checkpointer, 'conn', None)
            if conn is not None and hasattr(conn, 'close'):
                await conn.close()
        except Exception:  # nosec B110
            pass
        _default_checkpointer = None
        logger.info("Checkpointer closed")


# =============================================================================
# 鏉′欢璺敱鍑芥暟
# =============================================================================

def should_continue_to_writing(state: PipelineState) -> str:
    """Route from gap analysis."""
    if state.needs_targeted_refinement and state.refinement_attempt < state.max_refinement_attempts:
        logger.info(
            "Gaps detected, starting targeted refinement",
            attempt=state.refinement_attempt + 1,
            max_attempts=state.max_refinement_attempts,
        )
        return "targeted_refine"

    logger.info("No significant gaps, proceeding to outline generation")
    return "outline_generation"


def should_revise_sections(state: PipelineState) -> str:
    """Route after coverage audit."""
    weighted_bp = getattr(state, "weighted_coverage_bp", 10000) or 10000
    weak_count = getattr(state, "weak_citation_support_count", 0) or 0
    invalid_count = getattr(state, "invalid_citation_count", 0) or 0
    repair_attempt = getattr(state, "retry_count", 0) or 0
    if repair_attempt >= 2:
        logger.warning(
            "Coverage repair attempts exhausted; proceeding with diagnostic output",
            repair_attempt=repair_attempt,
            invalid_citations=invalid_count,
            weighted_coverage_bp=weighted_bp,
            weak_support=weak_count,
        )
        return "artifact_registration"
    if invalid_count > 0:
        logger.info(
            "Invalid citations found, revising sections",
            invalid_citations=invalid_count,
            repair_attempt=repair_attempt + 1,
        )
        return "section_revision"
    if weighted_bp < 8000 or weak_count > 5:
        logger.info(
            "Coverage audit below threshold, revising sections",
            weighted_coverage_bp=weighted_bp,
            weak_support=weak_count,
            repair_attempt=repair_attempt + 1,
        )
        return "section_revision"

    logger.info(
        "Coverage audit passed",
        coverage=state.coverage_score,
        weighted_coverage_bp=weighted_bp,
        weak_support=weak_count,
    )
    return "artifact_registration"


def should_retry_on_error(state: PipelineState) -> str:
    """Route retry behavior after errors."""
    if state.errors and state.retry_count < 3:
        logger.warning(
            "Error occurred, retrying",
            errors=state.errors[-1],
            retry_count=state.retry_count,
        )
        return "retry"

    if state.errors:
        logger.error("Max retries exceeded", errors=state.errors)
        return END

    return "continue"


# =============================================================================
# 鍥炬瀯寤?# =============================================================================

def create_pipeline_graph() -> StateGraph:
    """Create the review-generation pipeline graph."""
    workflow = StateGraph(PipelineState)

    workflow.add_node("search", with_audit("search")(search_node))
    workflow.add_node("deduplicate", with_audit("deduplicate")(deduplicate_node))
    workflow.add_node("filter", with_audit("filter")(filter_node))
    workflow.add_node("bm25", with_audit("bm25")(bm25_node))
    workflow.add_node("embedding", with_audit("embedding")(embedding_node))
    workflow.add_node("pgvector_knn", with_audit("pgvector_knn")(pgvector_knn_node))
    workflow.add_node("rerank", with_audit("rerank")(rerank_node))
    workflow.add_node("community_detection", with_audit("community_detection")(community_detection_node))
    workflow.add_node("visualize_community", with_audit("visualize_community")(visualize_community_node))
    workflow.add_node("evidence_cards", with_audit("evidence_cards")(evidence_cards_node))
    workflow.add_node("kg_extraction", with_audit("kg_extraction")(kg_extraction_node))
    workflow.add_node("community_memory", with_audit("community_memory")(community_memory_node))
    workflow.add_node("gap_analysis", with_audit("gap_analysis")(gap_analysis_node))
    workflow.add_node("targeted_refine", with_audit("targeted_refine")(targeted_refine_node))
    workflow.add_node("outline_generation", with_audit("outline_generation")(outline_generation_node))
    workflow.add_node("user_confirm", with_audit("user_confirm")(user_confirm_node))
    workflow.add_node("write_review", with_audit("write_review")(write_review_node))
    workflow.add_node("coverage_audit", with_audit("coverage_audit")(coverage_audit_node))
    workflow.add_node("section_revision", with_audit("section_revision")(section_revision_node))
    workflow.add_node("abstract_generation", with_audit("abstract_generation")(generate_abstract_node))
    workflow.add_node("artifact_registration", with_audit("artifact_registration")(artifact_registration_node))
    workflow.add_node("finalize", with_audit("finalize")(finalize_node))

    workflow.set_entry_point("search")

    workflow.add_edge("search", "deduplicate")
    workflow.add_edge("deduplicate", "filter")
    workflow.add_edge("filter", "bm25")
    workflow.add_edge("bm25", "embedding")
    workflow.add_edge("embedding", "pgvector_knn")
    workflow.add_edge("pgvector_knn", "rerank")
    workflow.add_edge("rerank", "community_detection")
    workflow.add_edge("community_detection", "visualize_community")
    workflow.add_edge("visualize_community", "evidence_cards")
    workflow.add_edge("evidence_cards", "kg_extraction")
    workflow.add_edge("kg_extraction", "community_memory")
    workflow.add_edge("community_memory", "gap_analysis")

    workflow.add_conditional_edges(
        "gap_analysis",
        should_continue_to_writing,
        {
            "targeted_refine": "targeted_refine",
            "outline_generation": "outline_generation",
        },
    )
    workflow.add_edge("targeted_refine", "evidence_cards")
    workflow.add_edge("outline_generation", "write_review")
    workflow.add_edge("write_review", "coverage_audit")

    workflow.add_conditional_edges(
        "coverage_audit",
        should_revise_sections,
        {
            "section_revision": "section_revision",
            "artifact_registration": "abstract_generation",
        },
    )
    workflow.add_edge("section_revision", "coverage_audit")
    workflow.add_edge("abstract_generation", "artifact_registration")
    workflow.add_edge("artifact_registration", "finalize")
    workflow.add_edge("finalize", END)

    return workflow


def compile_graph(
    checkpointer,
    debug: bool = True,
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
    callbacks: list | None = None,
):

    """Compile the pipeline graph."""
    if interrupt_before is None:
        interrupt_before = ["user_confirm"]

    workflow = create_pipeline_graph()

    compile_kwargs = {
        "checkpointer": checkpointer,
        "debug": debug,
        "interrupt_before": interrupt_before,
        "interrupt_after": interrupt_after,
    }

    compiled = workflow.compile(**compile_kwargs)

    logger.info(
        "Graph compiled",
        debug=debug,
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
    )

    return compiled


# =============================================================================
# 渚挎嵎鍑芥暟
# =============================================================================

def get_default_graph():
    """Get the default graph for tests."""
    from langgraph.checkpoint.memory import MemorySaver
    return compile_graph(checkpointer=MemorySaver(), debug=True)


async def run_pipeline(
    query: str,
    project_id: str,
    config: dict | None = None,
    sse_manager=None,
    auto_confirm: bool = True,
    resume: bool = False,
):

    """Run or resume a pipeline."""
    from ..services.database import get_database
    db = get_database()

    # 鑾峰彇鎸佷箙鍖?checkpointer
    checkpointer = await get_checkpointer()

    # 鍒涘缓 PipelineTracker 瀹炰緥锛屾敞鍏?db 鎸佷箙鍖?callable
    tracker = PipelineTracker(project_id, topic=query)

    # 鍒涘缓 llm_call DB 鎸佷箙鍖?wrapper
    async def _persist_llm_call(
        node_name: str, provider_name: str, model_name: str,
        call_type: str, prompt_tokens: int, completion_tokens: int,
        latency_ms: int,
    ):
        """Persist one LLM call record."""
        try:
            exec_id = tracker._node_ids.get(node_name)
            if not tracker.run_id:
                return
            if not exec_id:
                exec_id = await db.create_node_execution(
                    tracker.run_id,
                    node_name,
                    call_type,
                )
                tracker._node_ids[node_name] = exec_id
            input_price_per_m = 0.0
            output_price_per_m = 0.0
            cost = 0.0
            try:
                from ..api.admin.providers import get_provider_pricing
                input_price_per_m, output_price_per_m = await get_provider_pricing(db, provider_name, model_name)
                cost = (prompt_tokens * input_price_per_m + completion_tokens * output_price_per_m) / 1_000_000
            except Exception:  # nosec B110
                pass
            call_id = await db.create_llm_call(
                pipeline_run_id=tracker.run_id,
                node_execution_id=exec_id,
                project_id=tracker.project_id,
                node_name=node_name,
                call_type=call_type,
                provider_name=provider_name,
                model_name=model_name,
                requested_model=model_name,
                upstream_model=model_name,
                latency_ms=latency_ms,
                input_price_per_m=input_price_per_m,
                output_price_per_m=output_price_per_m,
            )
            await db.finish_llm_call(
                call_id=call_id,
                status="success",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
                latency_ms=latency_ms,
                input_price_per_m=input_price_per_m,
                output_price_per_m=output_price_per_m,
            )
        except Exception as e:
            logger.warning("Failed to persist llm_call", error=str(e))

    llm_callback = LLMCallbackHandler(tracker.token_tracker, db_caller=_persist_llm_call)

    from ..services.observability import PipelineStatusCallback
    status_callback = PipelineStatusCallback(project_id, db.update_project_status)

    interrupt_before = [] if auto_confirm else ["user_confirm"]
    graph = compile_graph(
        checkpointer=checkpointer,
        debug=True,
        interrupt_before=interrupt_before,
    )

    # LangGraph thread_id = project_id锛宑allbacks 閫氳繃 config 娉ㄥ叆
    thread_config = {
        "configurable": {"thread_id": project_id},
        "callbacks": [llm_callback, status_callback],
    }

    # 鏇存柊椤圭洰鐘舵€佷负 running
    await db.update_project_status(project_id, "running")

    # 鍚姩 tracker 骞舵寔涔呭寲 pipeline_run
    await tracker.start(db_create_run=db.create_pipeline_run)

    # 閫氳繃 ContextVar 娉ㄥ叆 tracker锛堥伩鍏嶄笉鍙簭鍒楀寲瀵硅薄杩涘叆 checkpoint锛?    set_current_tracker(tracker)
    set_current_llm_callback(llm_callback)
    push_current_project(project_id)
    push_run_id(tracker.run_id)

    if resume:
        # LangGraph 鍘熺敓鎭㈠锛氫紶 None 浣滀负 input锛岃嚜鍔ㄤ粠鏈€鍚?checkpoint 缁х画
        logger.info("Resuming pipeline from checkpoint", project_id=project_id)
        input_data = None
    else:
        # 鏂板缓杩愯
        input_data = PipelineState(
            project_id=project_id,
            query=query,
            config=config or {},
        )

    result = None
    try:
        async for event in graph.astream(
            input_data,
            config=thread_config,
            stream_mode="updates",
        ):
            for node_name, node_output in event.items():
                # 立项目状态为当前节点
                await db.update_project_status(project_id, f"running:{node_name}")

                # 安全处理 node_output
                if isinstance(node_output, dict):
                    result = {**(result or {}), **node_output}
                elif isinstance(node_output, tuple) and len(node_output) > 0 and isinstance(node_output[0], dict):
                    result = {**(result or {}), **node_output[0]}
                else:
                    logger.warning("Unexpected node output type", node=node_name, type=type(node_output).__name__)
                    continue

                # 发送 SSE 进度事件
                if sse_manager:
                    status = node_output.get("status", "processing") if isinstance(node_output, dict) else "processing"
                    detail_msg = _build_progress_message(node_name, result)
                    await sse_manager.send_progress(
                        project_id=project_id,
                        node=node_name,
                        status=status,
                        message=detail_msg,
                    )

        await tracker.finish(
            status="succeeded",
            db_finish_run=db.finish_pipeline_run,
        )

        await db.update_project_status(project_id, "completed")

        if sse_manager and result:
            await sse_manager.send_complete(project_id, {
                "paper_count": len(result.get("paper_ids", [])),
                "status": result.get("status", "completed"),
            })

    except Exception as e:
        with contextlib.suppress(Exception):
            await tracker.finish(
                status="failed",
                error_message=str(e),
                db_finish_run=db.finish_pipeline_run,
            )
        logger.error("Pipeline failed", error=str(e), project_id=project_id)
        await db.update_project_status(project_id, "failed")
        if sse_manager:
            await sse_manager.send_error(project_id, str(e))
        raise
    finally:
        pop_run_id()
        pop_current_project()
        set_current_tracker(None)
        set_current_llm_callback(None)

    return result



def _build_progress_message(node_name: str, state: dict) -> str:
    """Build a concise progress message for SSE clients."""
    if node_name == "search":
        return f"搜索完成，共 {len(state.get('paper_ids', []))} 篇论文"
    if node_name == "deduplicate":
        return f"去重完成，保留 {len(state.get('paper_ids', []))} 篇"
    if node_name == "filter":
        return f"筛选完成，保留 {len(state.get('paper_ids', []))} 篇高质量论文"
    if node_name == "bm25":
        return "BM25 评分中..."
    if node_name == "embedding":
        return f"正在向量化 {len(state.get('embedding_ids', []))} 篇论文..."
    if node_name == "pgvector_knn":
        return "pgvector KNN 检索中"
    if node_name == "rerank":
        return f"重排序 {len(state.get('reranked_paper_ids', []))} 篇论文完成"
    if node_name == "community_detection":
        return f"社区检测中，发现 {len(state.get('cluster_ids', []))} 个簇"
    if node_name == "visualize_community":
        return "社区可视化中"
    if node_name == "evidence_cards":
        return f"正在生成 {len(state.get('evidence_card_ids', []))} 个证据卡片"
    if node_name == "kg_extraction":
        return f"知识图谱抽取中，提取 {len(state.get('kg_entity_ids', []))} 个实体、{len(state.get('kg_relation_ids', []))} 条关系"
    if node_name == "community_memory":
        return f"社区记忆中，已生成 {len(state.get('community_memory_ids', []))} 条"
    if node_name == "gap_analysis":
        return "差距分析中"
    if node_name == "targeted_refine":
        return "定向改进中"
    if node_name == "outline_generation":
        return "大纲生成中"
    if node_name == "write_review":
        return "综述撰写中"
    if node_name == "coverage_audit":
        return "覆盖率审计中"
    if node_name == "artifact_registration":
        return "成果注册中"
    if node_name == "finalize":
        return "定稿中"
    return f"{node_name} 运行中"
