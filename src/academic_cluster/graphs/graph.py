"""
LangGraph 图定义

定义主 Pipeline 图、子图，以及节点间的边和条件路由。
使用 AsyncPostgresSaver 实现持久化 checkpoint，支持断点恢复。
集成 PipelineTracker 实现可观测性。
"""

import structlog
from langgraph.graph import END, StateGraph

from .state import PipelineState
from .checkpoint import with_audit
from ..services.observability import PipelineTracker, LLMCallbackHandler
from .nodes import (
    search_node,
    deduplicate_node,
    filter_node,
    bm25_node,
    embedding_node,
    pgvector_knn_node,
    rerank_node,
    kg_extraction_node,
    community_detection_node,
    visualize_community_node,
    evidence_cards_node,
    gap_analysis_node,
    targeted_refine_node,
    outline_generation_node,
    user_confirm_node,
    write_review_node,
    coverage_audit_node,
    section_revision_node,
    artifact_registration_node,
    finalize_node,
)

logger = structlog.get_logger()


# =============================================================================
# Checkpointer 管理
# =============================================================================

_default_checkpointer = None


async def get_checkpointer():
    """获取或创建 AsyncPostgresSaver 单例（fallback 到 MemorySaver）"""
    global _default_checkpointer
    if _default_checkpointer is not None:
        return _default_checkpointer

    try:
        # 让 msgpack 支持 numpy 类型序列化
        import ormsgpack
        from langgraph.checkpoint.serde import jsonplus as _serde_mod
        if hasattr(_serde_mod, '_option'):
            _serde_mod._option = _serde_mod._option | ormsgpack.OPT_SERIALIZE_NUMPY
            logger.info("Patched msgpack options: OPT_SERIALIZE_NUMPY enabled")

        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
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
    """关闭 checkpointer 连接"""
    global _default_checkpointer
    if _default_checkpointer is not None:
        try:
            conn = getattr(_default_checkpointer, 'conn', None)
            if conn is not None and hasattr(conn, 'close'):
                await conn.close()
        except Exception:
            pass
        _default_checkpointer = None
        logger.info("Checkpointer closed")


# =============================================================================
# 条件路由函数
# =============================================================================

def should_continue_to_writing(state: PipelineState) -> str:
    """差距分析后决定路径：补充搜索 or 开始写作"""
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
    """覆盖审计后决定路径：修订 or 生成产出"""
    if state.coverage_score < 0.8 or state.invalid_citation_count > 0:
        logger.info(
            "Coverage insufficient or invalid citations found",
            coverage=state.coverage_score,
            invalid_citations=state.invalid_citation_count,
        )
        return "section_revision"

    logger.info("Coverage sufficient, proceeding to artifact registration")
    return "artifact_registration"


def should_retry_on_error(state: PipelineState) -> str:
    """错误处理路由"""
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
# 图构建
# =============================================================================

def create_pipeline_graph() -> StateGraph:
    """创建主 Pipeline 图（未编译）"""
    workflow = StateGraph(PipelineState)

    # 搜索阶段
    workflow.add_node("search", with_audit("search")(search_node))
    workflow.add_node("deduplicate", with_audit("deduplicate")(deduplicate_node))
    workflow.add_node("filter", with_audit("filter")(filter_node))
    workflow.add_node("bm25", with_audit("bm25")(bm25_node))

    # 嵌入和检索阶段
    workflow.add_node("embedding", with_audit("embedding")(embedding_node))
    workflow.add_node("pgvector_knn", with_audit("pgvector_knn")(pgvector_knn_node))
    workflow.add_node("rerank", with_audit("rerank")(rerank_node))

    # 知识图谱阶段
    workflow.add_node("kg_extraction", with_audit("kg_extraction")(kg_extraction_node))

    # 聚类阶段
    workflow.add_node("community_detection", with_audit("community_detection")(community_detection_node))
    workflow.add_node("visualize_community", with_audit("visualize_community")(visualize_community_node))

    # 证据阶段
    workflow.add_node("evidence_cards", with_audit("evidence_cards")(evidence_cards_node))
    workflow.add_node("gap_analysis", with_audit("gap_analysis")(gap_analysis_node))
    workflow.add_node("targeted_refine", with_audit("targeted_refine")(targeted_refine_node))

    # 写作阶段
    workflow.add_node("outline_generation", with_audit("outline_generation")(outline_generation_node))
    workflow.add_node("user_confirm", with_audit("user_confirm")(user_confirm_node))
    workflow.add_node("write_review", with_audit("write_review")(write_review_node))
    workflow.add_node("coverage_audit", with_audit("coverage_audit")(coverage_audit_node))
    workflow.add_node("section_revision", with_audit("section_revision")(section_revision_node))

    # 产出阶段
    workflow.add_node("artifact_registration", with_audit("artifact_registration")(artifact_registration_node))
    workflow.add_node("finalize", with_audit("finalize")(finalize_node))

    # 设置入口
    workflow.set_entry_point("search")

    # 搜索阶段边
    workflow.add_edge("search", "deduplicate")
    workflow.add_edge("deduplicate", "filter")
    workflow.add_edge("filter", "bm25")

    # 嵌入和检索阶段边
    workflow.add_edge("bm25", "embedding")
    workflow.add_edge("embedding", "pgvector_knn")
    workflow.add_edge("pgvector_knn", "rerank")

    # 知识图谱阶段边
    workflow.add_edge("rerank", "kg_extraction")

    # 聚类阶段边
    workflow.add_edge("kg_extraction", "community_detection")
    workflow.add_edge("community_detection", "visualize_community")
    workflow.add_edge("visualize_community", "evidence_cards")

    # 证据阶段边
    workflow.add_edge("evidence_cards", "gap_analysis")

    # 条件边：差距分析后决定路径
    workflow.add_conditional_edges(
        "gap_analysis",
        should_continue_to_writing,
        {
            "targeted_refine": "targeted_refine",
            "outline_generation": "outline_generation",
        },
    )

    # targeted_refine 循环回 evidence_cards
    workflow.add_edge("targeted_refine", "evidence_cards")

    # 写作阶段边
    workflow.add_edge("outline_generation", "user_confirm")
    workflow.add_edge("user_confirm", "write_review")
    workflow.add_edge("write_review", "coverage_audit")

    # 条件边：覆盖审计后决定路径
    workflow.add_conditional_edges(
        "coverage_audit",
        should_revise_sections,
        {
            "section_revision": "section_revision",
            "artifact_registration": "artifact_registration",
        },
    )

    # section_revision 循环回 coverage_audit
    workflow.add_edge("section_revision", "coverage_audit")

    # 产出阶段边
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
    """
    编译图

    Args:
        checkpointer: 检查点存储（必须传入，通常是 AsyncPostgresSaver）
        debug: 是否启用调试模式
        interrupt_before: 在哪些节点前中断（用于人工确认）
        interrupt_after: 在哪些节点后中断
        callbacks: LangChain 回调列表（可选，用于 LLM 追踪）

    Returns:
        编译后的图
    """
    if interrupt_before is None:
        interrupt_before = ["user_confirm"]

    workflow = create_pipeline_graph()

    compile_kwargs = {
        "checkpointer": checkpointer,
        "debug": debug,
        "interrupt_before": interrupt_before,
        "interrupt_after": interrupt_after,
    }
    if callbacks:
        compile_kwargs["callbacks"] = callbacks

    compiled = workflow.compile(**compile_kwargs)

    logger.info(
        "Graph compiled",
        debug=debug,
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
        has_callbacks=callbacks is not None and len(callbacks) > 0,
    )

    return compiled


# =============================================================================
# 便捷函数
# =============================================================================

def get_default_graph():
    """获取默认配置的编译图（同步版本，仅用于测试）"""
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
    """
    运行 Pipeline

    Args:
        query: 研究主题查询
        project_id: 项目 ID（同时用作 LangGraph thread_id）
        config: 配置覆盖
        sse_manager: SSE 管理器（可选，用于实时推送）
        auto_confirm: 是否自动确认大纲（跳过人工审核）
        resume: 是否从上次失败的检查点恢复（LangGraph 原生恢复）

    Returns:
        最终状态
    """
    from ..services.database import get_database
    db = get_database()

    # 获取持久化 checkpointer
    checkpointer = await get_checkpointer()

    # 创建 PipelineTracker 实例，注入 db 持久化 callable
    tracker = PipelineTracker(project_id, topic=query)
    llm_callback = LLMCallbackHandler(tracker.token_tracker)

    # 如果自动确认，则不中断
    interrupt_before = [] if auto_confirm else ["user_confirm"]
    graph = compile_graph(
        checkpointer=checkpointer,
        debug=True,
        interrupt_before=interrupt_before,
        callbacks=[llm_callback],
    )

    # LangGraph thread_id = project_id
    thread_config = {"configurable": {"thread_id": project_id}}

    # 更新项目状态为 running
    await db.update_project_status(project_id, "running")

    # 启动 tracker 并持久化 pipeline_run
    await tracker.start(db_create_run=db.create_pipeline_run)

    if resume:
        # LangGraph 原生恢复：传 None 作为 input，自动从最后 checkpoint 继续
        logger.info("Resuming pipeline from checkpoint", project_id=project_id)
        input_data = None
    else:
        # 新建运行（注入 tracker）
        input_data = PipelineState(
            project_id=project_id,
            query=query,
            config=config or {},
            tracker=tracker,
        )

    result = None
    try:
        async for event in graph.astream(
            input_data,
            config=thread_config,
            stream_mode="updates",
        ):
            for node_name, node_output in event.items():
                # 立即更新项目状态为当前节点
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

        # 追踪器结束并记录汇总
        tracker_summary = await tracker.finish(
            status="succeeded",
            db_finish_run=db.finish_pipeline_run,
        )

        # 更新项目状态为 completed
        await db.update_project_status(project_id, "completed")

        # 发送完成事件
        if sse_manager and result:
            await sse_manager.send_complete(project_id, {
                "paper_count": len(result.get("paper_ids", [])),
                "status": result.get("status", "completed"),
            })

    except Exception as e:
        # 追踪器记录失败状态
        try:
            await tracker.finish(
                status="failed",
                error_message=str(e),
                db_finish_run=db.finish_pipeline_run,
            )
        except Exception:
            pass
        logger.error("Pipeline failed", error=str(e), project_id=project_id)
        await db.update_project_status(project_id, "failed")
        if sse_manager:
            await sse_manager.send_error(project_id, str(e))
        raise

    return result


def _build_progress_message(node_name: str, state: dict) -> str:
    """构建详细的进度消息"""
    if node_name == "search":
        count = len(state.get("paper_ids", []))
        return f"搜索完成，找到 {count} 篇论文"
    elif node_name == "deduplicate":
        count = len(state.get("paper_ids", []))
        return f"去重完成，保留 {count} 篇论文"
    elif node_name == "filter":
        count = len(state.get("paper_ids", []))
        return f"筛选完成，保留 {count} 篇高质量论文"
    elif node_name == "bm25":
        return "BM25 关键词索引构建完成"
    elif node_name == "embedding":
        count = len(state.get("embedding_ids", []))
        return f"向量化完成，生成 {count} 个嵌入向量"
    elif node_name == "pgvector_knn":
        return "pgvector KNN 图构建完成"
    elif node_name == "rerank":
        count = len(state.get("core_paper_ids", []))
        return f"重排序完成，筛选出 {count} 篇核心论文"
    elif node_name == "kg_extraction":
        entities = len(state.get("kg_entity_ids", []))
        relations = len(state.get("kg_relation_ids", []))
        return f"知识图谱提取完成，{entities} 个实体，{relations} 个关系"
    elif node_name == "community_detection":
        count = len(state.get("cluster_ids", []))
        return f"社区检测完成，发现 {count} 个主题聚类"
    elif node_name == "visualize_community":
        return "社区可视化生成完成"
    elif node_name == "evidence_cards":
        count = len(state.get("evidence_card_ids", []))
        return f"证据卡片生成完成，共 {count} 张"
    elif node_name == "gap_analysis":
        return "研究空白分析完成"
    elif node_name == "targeted_refine":
        return "定向补充搜索完成"
    elif node_name == "outline_generation":
        return "大纲生成完成"
    elif node_name == "write_review":
        return "综述撰写完成"
    elif node_name == "coverage_audit":
        return "覆盖度审计完成"
    elif node_name == "artifact_registration":
        return "产出物注册完成"
    elif node_name == "finalize":
        return "流程完成"
    else:
        return f"{node_name} 完成"
