"""
LangGraph 图定义

定义主 Pipeline 图、子图，以及节点间的边和条件路由。
"""

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from .state import PipelineState
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
# 条件路由函数
# =============================================================================

def should_continue_to_writing(state: PipelineState) -> str:
    """
    差距分析后决定路径

    如果社区存在明显证据差距，返回 targeted_refine 进行补充搜索
    否则返回 outline_generation 开始写作
    """
    # 检查是否还有 refinement 尝试次数
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
    """
    覆盖审计后决定路径

    如果覆盖率不足或存在无效引用，返回 section_revision 进行修订
    否则返回 artifact_registration 生成最终产出
    """
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
    """
    错误处理路由

    如果发生错误且未超过重试次数，返回重试节点
    否则返回 END
    """
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
    """
    创建主 Pipeline 图

    返回未编译的 StateGraph，可以添加自定义节点和边后编译。
    """
    # 创建图
    workflow = StateGraph(PipelineState)

    # =========================================================================
    # 添加节点
    # =========================================================================

    # 搜索阶段
    workflow.add_node("search", search_node)
    workflow.add_node("deduplicate", deduplicate_node)
    workflow.add_node("filter", filter_node)
    workflow.add_node("bm25", bm25_node)

    # 嵌入和检索阶段
    workflow.add_node("embedding", embedding_node)
    workflow.add_node("pgvector_knn", pgvector_knn_node)
    workflow.add_node("rerank", rerank_node)

    # 知识图谱阶段
    workflow.add_node("kg_extraction", kg_extraction_node)

    # 聚类阶段
    workflow.add_node("community_detection", community_detection_node)
    workflow.add_node("visualize_community", visualize_community_node)

    # 证据阶段
    workflow.add_node("evidence_cards", evidence_cards_node)
    workflow.add_node("gap_analysis", gap_analysis_node)
    workflow.add_node("targeted_refine", targeted_refine_node)

    # 写作阶段
    workflow.add_node("outline_generation", outline_generation_node)
    workflow.add_node("user_confirm", user_confirm_node)
    workflow.add_node("write_review", write_review_node)
    workflow.add_node("coverage_audit", coverage_audit_node)
    workflow.add_node("section_revision", section_revision_node)

    # 产出阶段
    workflow.add_node("artifact_registration", artifact_registration_node)
    workflow.add_node("finalize", finalize_node)

    # =========================================================================
    # 添加边
    # =========================================================================

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
    checkpointer=None,
    debug: bool = True,
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
):
    """
    编译图

    Args:
        checkpointer: 检查点存储，默认使用内存存储
        debug: 是否启用调试模式
        interrupt_before: 在哪些节点前中断（用于人工确认）
        interrupt_after: 在哪些节点后中断

    Returns:
        编译后的图
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    # 默认在 user_confirm 前中断
    if interrupt_before is None:
        interrupt_before = ["user_confirm"]

    workflow = create_pipeline_graph()

    compiled = workflow.compile(
        checkpointer=checkpointer,
        debug=debug,
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
    )

    logger.info(
        "Graph compiled",
        debug=debug,
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
    )

    return compiled


# =============================================================================
# 便捷函数
# =============================================================================

def get_default_graph():
    """获取默认配置的编译图"""
    return compile_graph(debug=True)


async def run_pipeline(
    query: str,
    project_id: str,
    config: dict | None = None,
    checkpointer=None,
):
    """
    运行 Pipeline

    Args:
        query: 研究主题查询
        project_id: 项目 ID
        config: 配置覆盖
        checkpointer: 检查点存储

    Returns:
        最终状态
    """
    graph = compile_graph(checkpointer=checkpointer, debug=True)

    initial_state = PipelineState(
        project_id=project_id,
        query=query,
        config=config or {},
    )

    # 使用 ainvoke 异步执行
    result = await graph.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": project_id}},
    )

    return result


async def stream_pipeline(
    query: str,
    project_id: str,
    config: dict | None = None,
    checkpointer=None,
):
    """
    流式运行 Pipeline

    Args:
        query: 研究主题查询
        project_id: 项目 ID
        config: 配置覆盖
        checkpointer: 检查点存储

    Yields:
        节点执行事件
    """
    graph = compile_graph(checkpointer=checkpointer, debug=True)

    initial_state = PipelineState(
        project_id=project_id,
        query=query,
        config=config or {},
    )

    # 使用 astream 流式执行
    async for event in graph.astream(
        initial_state,
        config={"configurable": {"thread_id": project_id}},
    ):
        yield event
