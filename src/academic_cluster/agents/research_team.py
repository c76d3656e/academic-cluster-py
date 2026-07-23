"""
Research Agent — 真正的 ReAct Agent，负责论文检索

使用 create_react_agent + 真实搜索工具。
Agent 自主决定：搜索什么、搜多少轮、何时停止。

没有 Coordinator 类。没有 deterministic fallback。
Agent 的 messages 历史就是它的"记忆"。
"""

from __future__ import annotations

import json
from typing import Annotated, Any

import structlog
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import create_react_agent

from ..services.llm_client import AuditedChatModel, create_llm
from ..tools.agent_tools import finalize_research, search_papers

logger = structlog.get_logger()

MAX_SEARCH_CALLS = 6


def _safe_nonnegative_int(value: Any, default: int = 0) -> int:
    """Parse untrusted tool metadata without accepting booleans or negatives."""

    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0, parsed)


RESEARCH_SYSTEM_PROMPT = """你是学术文献检索专家（Research Agent）。

# 你的目标
为给定的研究主题找到足够数量、高质量的学术论文，确保覆盖主题的主要研究方向。

# 可用工具
- **search_papers(query, limit_per_source)**：在多个学术数据源（Semantic Scholar, arXiv, PubMed, Crossref, OpenAlex）上并发搜索。返回搜索结果统计和 top-5 论文标题。论文自动存入数据库。
- **finalize_research(summary_json, total_papers, queries_used)**：提交最终搜索结果，结束研究阶段。

# 如何工作
1. 生成 3-5 个不同角度的搜索查询，覆盖研究主题的不同子方向、同义词和上下位术语
2. 分批执行搜索（每次一个查询），论文自动存入数据库
3. 检查每次搜索返回的新增论文数，避免重复查询
4. 达到目标数量或连续两次没有新增论文后，调用 finalize_research

# 自主决策指南
- 每次只能调用一个工具，等待结果后再决定下一步
- 查询之间应该有实质性差异，不要变着花样搜同一个东西
- 如果连续搜索 2-3 轮没有新论文出现，就该停止了
- 不要追求完美——有剩余缺口是正常的，在 summary_json 中记录下来即可
- 最多搜索 6 次，避免无界工具循环

# 注意
- 必须调用 finalize_research 来结束任务
- 优先选择近 5 年、高引用的论文
"""


def create_research_agent(
    model_name: str = "gpt-4o-mini",
    temperature: float = 0.3,
    max_search_calls: int = MAX_SEARCH_CALLS,
) -> Any:
    """创建 Research Agent（ReAct 模式）

    返回已编译的 LangGraph StateGraph，
    通过 agent.invoke({"messages": [...]}) 运行。
    """
    del model_name
    search_count = 0

    @tool("search_papers")
    async def bounded_search_papers(
        query: Annotated[str, "搜索查询字符串"],
        limit_per_source: Annotated[int, "每个数据源最大返回论文数"] = 100,
    ) -> str:
        """Search papers with a hard per-execution tool-call limit."""

        nonlocal search_count
        if search_count >= max_search_calls:
            return json.dumps(
                {
                    "error": "search_limit_reached",
                    "max_search_calls": max_search_calls,
                    "instruction": "Call finalize_research now.",
                },
                ensure_ascii=False,
            )
        search_count += 1
        return str(
            await search_papers.ainvoke(
                {"query": query, "limit_per_source": limit_per_source}
            )
        )

    tools: list[BaseTool] = [bounded_search_papers, finalize_research]
    llm = AuditedChatModel(inner=create_llm(temperature=temperature))
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=RESEARCH_SYSTEM_PROMPT,
        name="research_agent",
    )


async def run_research(
    topic: str,
    project_id: str,
    target_papers: int = 50,
    model_name: str = "gpt-4o-mini",
    supplemental_queries: list[str] | None = None,
) -> dict[str, Any]:
    """运行 Research Agent 进行论文检索。

    构建初始消息，调用 Agent 的 ReAct 循环，
    从工具调用历史中提取结构化的最终结果。

    Args:
        topic: 研究主题
        target_papers: 目标论文数量
    Returns:
        {papers: list[dict], total_found: int, relevant_count: int, coverage_assessment: str}
    """
    del model_name  # Backward-compatible argument; Provider Pool owns routing.
    from ..services.runtime_policy import get_runtime_policy

    policy = await get_runtime_policy()
    agent = create_research_agent(
        temperature=0.3,
        max_search_calls=policy.max_search_calls,
    )

    supplemental = supplemental_queries or []
    supplemental_block = (
        "\n优先补充查询：\n- " + "\n- ".join(supplemental) if supplemental else ""
    )
    user_message = f"""研究主题：{topic}
目标论文数量：{target_papers}
{supplemental_block}

请使用不同角度的查询检索论文。最多调用 search_papers 6 次。
达到目标或连续两次没有新增论文后调用 finalize_research。"""

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=user_message)]},
        config={"recursion_limit": 18},
    )

    # —— 从 Agent 的工具调用历史中提取结构化结果 ——
    messages: list[Any] = result.get("messages", [])

    # 1. 从 finalize_research 提取元数据
    total_found = 0
    coverage = ""
    queries_used = ""
    finalized = False
    successful_tool_call_ids = {
        msg.tool_call_id
        for msg in messages
        if isinstance(msg, ToolMessage) and msg.status == "success"
    }
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if (
                    tc.get("name") == "finalize_research"
                    and tc.get("id") in successful_tool_call_ids
                ):
                    finalized = True
                    args = tc.get("args", {})
                    if not isinstance(args, dict):
                        args = {}
                    total_found = _safe_nonnegative_int(args.get("total_papers"))
                    queries_used = str(args.get("queries_used", ""))
                    try:
                        summary = (
                            json.loads(args.get("summary_json", "{}"))
                            if isinstance(args.get("summary_json"), str)
                            else args.get("summary_json", {})
                        )
                        if isinstance(summary, dict):
                            total_found = _safe_nonnegative_int(
                                summary.get("total"), total_found
                            )
                            coverage = str(summary.get("coverage_assessment", ""))
                    except (json.JSONDecodeError, TypeError):
                        pass
                    break
        if finalized:
            break

    if not finalized:
        raise RuntimeError("research agent stopped without finalizing its search")

    # 2. Load only papers explicitly linked to this project.
    from ..services.database import get_database

    papers = await get_database().get_project_papers(
        project_id,
        limit=min(max(target_papers, 1), 500),
    )
    unique_papers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for paper in papers:
        paper_id = str(paper.get("id") or paper.get("paper_id") or "")
        if not paper_id or paper_id in seen:
            continue
        seen.add(paper_id)
        paper["id"] = paper_id
        paper["paper_id"] = paper_id
        unique_papers.append(paper)

    logger.info(
        "Research agent completed",
        topic=topic,
        total=len(unique_papers),
        total_found=total_found,
    )

    return {
        "papers": unique_papers,
        "total_found": len(unique_papers),
        "relevant_count": len(unique_papers),
        "coverage_assessment": coverage,
        "queries_used": queries_used,
    }
