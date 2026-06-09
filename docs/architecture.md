# Academic Cluster Python - LangGraph 架构设计

## 1. 系统概述

基于 LangGraph 复刻 Rust 版 Prism 系统，实现学术论文聚类、知识图谱构建、综述自动生成。

## 2. LangGraph 核心概念映射

### 2.1 与 Rust DAG 的对应关系

| Rust 概念 | LangGraph 概念 | 说明 |
|-----------|----------------|------|
| GraphNode | Node (Python function) | 执行具体任务的函数 |
| GraphState | State (TypedDict/Pydantic) | 节点间共享的状态 |
| GraphEdge | Edge (add_edge) | 节点间的固定连接 |
| ConditionalEdge | Conditional Edge (add_conditional_edges) | 根据状态动态路由 |
| GraphRunner | StateGraph.compile().invoke() | 图执行引擎 |

### 2.2 Agent vs Tool vs Function Calling

**Agent（智能体）**:
- 具有自主决策能力的 LLM 节点
- 可以决定调用哪些工具、何时停止
- 用于需要推理和判断的复杂任务
- 示例：查询规划 Agent、综述写作 Agent

**Tool（工具）**:
- 被 Agent 调用的确定性函数
- 执行具体操作（搜索、过滤、存储）
- 不涉及 LLM 推理
- 示例：学术搜索 Tool、BM25 检索 Tool

**Function Calling**:
- LLM 输出结构化数据的机制
- Agent 通过 function calling 调用 Tool
- LangChain 中通过 `bind_tools()` 实现

## 3. 图架构设计

### 3.1 主图 (Main Graph)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Academic Review Pipeline                            │
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │   START      │───▶│   search     │───▶│  deduplicate │                  │
│  └──────────────┘    └──────────────┘    └──────────────┘                  │
│                                                     │                      │
│                                                     ▼                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │   embedding  │◀───│    bm25      │◀───│    filter    │                  │
│  └──────────────┘    └──────────────┘    └──────────────┘                  │
│         │                                                                      │
│         ▼                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │  pgvector    │───▶│   rerank     │───▶│  kg_extract  │                  │
│  │    knn       │    └──────────────┘    └──────────────┘                  │
│  └──────────────┘           │                    │                          │
│                             ▼                    ▼                          │
│                    ┌──────────────────────────────────────┐                 │
│                    │      community_detection              │                 │
│                    │  (Hybrid Graph + Leiden)              │                 │
│                    └──────────────────────────────────────┘                 │
│                                    │                                        │
│                                    ▼                                        │
│  ┌──────────────┐    ┌──────────────────────────────────────┐               │
│  │  evidence    │◀───│         visualize_community           │──── 推送前端 │
│  │   cards      │    └──────────────────────────────────────┘               │
│  └──────────────┘           │                                               │
│         │                   ▼                                               │
│         │          ┌──────────────┐                                         │
│         └─────────▶│    gap       │──── 有差距 ───▶ targeted_refine ─┐     │
│                    │   analysis    │                                  │     │
│                    └──────────────┘◀─────────────────────────────────┘     │
│                           │ 无差距                                         │
│                           ▼                                                │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │   outline    │───▶│ user_confirm │───▶│    write     │                  │
│  │  generation  │    │   (interrupt)│    │   review     │                  │
│  └──────────────┘    └──────────────┘    └──────────────┘                  │
│                                                     │                      │
│                                                     ▼                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │   coverage   │───▶│   section    │───▶│   artifact   │                  │
│  │    audit     │◀──▶│   revision   │    │  registration│                  │
│  └──────────────┘    └──────────────┘    └──────────────┘                  │
│                                                     │                      │
│                                                     ▼                      │
│                                              ┌──────────────┐              │
│                                              │     END      │              │
│                                              └──────────────┘              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 State 定义

```python
from typing import TypedDict, Annotated
from langgraph.graph import add_messages

class PaperState(TypedDict):
    """论文相关状态"""
    papers: list[Paper]                    # 当前论文列表
    core_papers: list[Paper]               # 核心参考论文 (top 80)
    auxiliary_papers: list[Paper]           # 辅助参考论文 (next 160)
    embeddings: dict[str, list[float]]     # paper_id -> embedding vector
    kg_entities: list[KGEntity]            # 知识图谱实体
    kg_relations: list[KGRelation]         # 知识图谱关系

class ClusteringState(TypedDict):
    """聚类相关状态"""
    clusters: list[Cluster]                # 社区列表
    cluster_assignments: dict[str, str]    # paper_id -> cluster_id
    hybrid_graph: dict                      # 混合图数据
    community_visualization: dict          # 可视化数据 (推送给前端)

class WritingState(TypedDict):
    """写作相关状态"""
    outline: Outline                       # 综述大纲
    section_plans: list[SectionPlan]       # 各章节计划
    citation_plans: list[CitationPlan]     # 引用计划
    written_sections: list[WrittenSection] # 已写章节
    final_review: str                      # 最终综述文本
    bibtex: str                           # BibTeX 引用

class PipelineState(TypedDict):
    """主状态 - 整合所有子状态"""
    # 元数据
    project_id: str
    query: str
    status: str

    # 配置
    config: PipelineConfig

    # 论文状态
    papers: Annotated[list[Paper], add_messages]
    core_papers: list[Paper]
    auxiliary_papers: list[Paper]

    # 嵌入和向量
    embeddings: dict[str, list[float]]
    knn_graph: dict

    # 知识图谱
    kg_entities: list[KGEntity]
    kg_relations: list[KGRelation]

    # 聚类
    clusters: list[Cluster]
    cluster_assignments: dict[str, str]
    hybrid_graph: dict
    community_visualization: dict

    # 证据
    evidence_cards: list[EvidenceCard]
    gap_analysis: list[GapAnalysis]

    # 写作
    outline: Outline
    section_plans: list[SectionPlan]
    citation_plans: list[CitationPlan]
    written_sections: list[WrittenSection]
    final_review: str
    bibtex: str

    # 错误处理
    errors: list[str]
    retry_count: int
```

## 4. 节点详细设计

### 4.1 搜索节点 (Search Node)

```python
async def search_papers(state: PipelineState) -> dict:
    """搜索学术论文 - 使用多个数据源"""
    # 使用 Agent 进行查询规划
    query_plan = await query_planning_agent.ainvoke({
        "query": state["query"]
    })

    # 并行搜索多个源
    papers = await asyncio.gather(
        search_semantic_scholar(query_plan),
        search_pubmed(query_plan),
        search_arxiv(query_plan),
        search_openalex(query_plan),
    )

    # 合并结果
    all_papers = deduplicate_papers(papers)

    return {"papers": all_papers, "status": "searched"}
```

### 4.2 知识图谱提取节点 (KG Extraction Node)

```python
async def extract_knowledge_graph(state: PipelineState) -> dict:
    """从论文中提取知识图谱"""
    # 使用 Agent 批量提取实体和关系
    kg_results = await kg_extraction_agent.abatch([
        {"paper": paper}
        for paper in state["core_papers"]
    ])

    # 实体标准化和去重
    entities = normalize_entities(kg_results)
    relations = normalize_relations(kg_results)

    return {
        "kg_entities": entities,
        "kg_relations": relations
    }
```

### 4.3 社区检测节点 (Community Detection Node)

```python
async def detect_communities(state: PipelineState) -> dict:
    """构建混合图并进行社区检测"""
    # 构建混合图 (5种边信号融合)
    hybrid_graph = build_hybrid_graph(
        knn_graph=state["knn_graph"],
        kg_relations=state["kg_relations"],
        kg_entities=state["kg_entities"],
        evidence_cards=state["evidence_cards"],
        core_papers=state["core_papers"],
        weights={"knn": 0.45, "kg": 0.25, "entity": 0.15, "evidence": 0.10, "quality": 0.05}
    )

    # Leiden 社区检测
    clusters = leiden_clustering(
        graph=hybrid_graph,
        resolution=1.0,
        seed=42
    )

    # 生成可视化数据
    visualization = generate_community_visualization(
        graph=hybrid_graph,
        clusters=clusters,
        papers=state["papers"]
    )

    return {
        "clusters": clusters,
        "cluster_assignments": {p.id: c.id for c in clusters for p in c.papers},
        "hybrid_graph": hybrid_graph,
        "community_visualization": visualization  # 推送给前端
    }
```

### 4.4 综述写作节点 (Review Writing Node)

```python
async def write_review(state: PipelineState) -> dict:
    """生成综述大纲和内容"""
    # 生成大纲
    outline = await outline_generation_agent.ainvoke({
        "clusters": state["clusters"],
        "kg_summary": summarize_kg(state["kg_entities"], state["kg_relations"]),
        "query": state["query"]
    })

    # 中断等待用户确认 (Human-in-the-loop)
    # LangGraph 会在此处暂停，等待用户确认大纲

    # 生成各章节计划
    section_plans = await generate_section_plans(outline, state["clusters"])

    # 生成引用计划
    citation_plans = generate_citation_plans(section_plans, state["papers"])

    # 并行写入各章节
    written_sections = await asyncio.gather(*[
        write_section_agent.ainvoke({
            "plan": plan,
            "evidence": get_relevant_evidence(plan, state["evidence_cards"]),
            "citations": get_section_citations(plan, citation_plans)
        })
        for plan in section_plans
    ])

    # 组装综述
    final_review = assemble_review(written_sections, citation_plans)
    bibtex = generate_bibtex(citation_plans)

    return {
        "outline": outline,
        "section_plans": section_plans,
        "citation_plans": citation_plans,
        "written_sections": written_sections,
        "final_review": final_review,
        "bibtex": bibtex
    }
```

## 5. Agent 设计

### 5.1 查询规划 Agent

```python
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool

@tool
def refine_search_query(query: str) -> str:
    """优化搜索查询"""
    # 确定性逻辑，不涉及 LLM
    return query.strip().lower()

@tool
def evaluate_search_results(papers: list[dict]) -> dict:
    """评估搜索结果质量"""
    # 确定性评分逻辑
    return {"score": len(papers) / 100}

query_planning_agent = ChatOpenAI(model="gpt-4o-mini").bind_tools([
    refine_search_query,
    evaluate_search_results
])
```

### 5.2 综述写作 Agent

```python
@tool
def get_paper_context(paper_id: str) -> str:
    """获取论文上下文"""
    # 从数据库获取论文详情
    return get_paper_from_db(paper_id)

@tool
def format_citation(paper_id: str, style: str = "apa") -> str:
    """格式化引用"""
    paper = get_paper_from_db(paper_id)
    return format_apa_citation(paper)

writing_agent = ChatOpenAI(model="gpt-4o").bind_tools([
    get_paper_context,
    format_citation
])
```

## 6. 条件路由设计

```python
from langgraph.graph import END

def should_continue_to_writing(state: PipelineState) -> str:
    """判断是否可以进入写作阶段"""
    # 检查社区差距分析结果
    gaps = state["gap_analysis"]
    total_gap_score = sum(g.score for g in gaps)

    if total_gap_score > 0.3:
        return "targeted_refine"  # 差距过大，需要补充搜索
    else:
        return "outline_generation"  # 可以开始写作

def should_revise_sections(state: PipelineState) -> str:
    """判断是否需要修订章节"""
    coverage = calculate_coverage(state)
    invalid_citations = count_invalid_citations(state)

    if coverage < 0.8 or invalid_citations > 0:
        return "section_revision"
    else:
        return "artifact_registration"
```

## 7. 中断和人工确认

```python
from langgraph.checkpoint.memory import MemorySaver

# 使用 interrupt 实现人工确认
def outline_generation_with_confirm(state: PipelineState) -> dict:
    """生成大纲并等待用户确认"""
    outline = generate_outline(state)

    # 返回大纲，图会在此处暂停
    # 用户确认后继续执行
    return {"outline": outline}

# 编译图时添加中断点
graph = StateGraph(PipelineState)
graph.add_node("outline_generation", outline_generation_with_confirm)
graph.add_node("user_confirm", lambda s: s)  # 确认节点

# 添加 interrupt
graph.compile(
    checkpointer=MemorySaver(),
    interrupt_before=["user_confirm"]  # 在确认前中断
)
```

## 8. 外部存储集成

### 8.1 PostgreSQL 存储大型数据

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

class PaperRepository:
    """论文存储仓库 - 状态中只保留 ID"""

    def __init__(self, db_url: str):
        self.engine = create_async_engine(db_url)

    async def save_paper(self, paper: Paper) -> str:
        """保存论文，返回 ID"""
        async with AsyncSession(self.engine) as session:
            session.add(paper)
            await session.commit()
            return paper.id

    async def get_paper(self, paper_id: str) -> Paper:
        """获取论文详情"""
        async with AsyncSession(self.engine) as session:
            return await session.get(Paper, paper_id)

# 在状态中只保留引用
class PipelineState(TypedDict):
    paper_ids: list[str]  # 只保留 ID，不保留完整论文数据
```

### 8.2 Redis 缓存

```python
import redis.asyncio as redis

class CacheService:
    """缓存服务"""

    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url)

    async def get_embeddings(self, paper_id: str) -> Optional[list[float]]:
        """获取缓存的嵌入向量"""
        data = await self.redis.get(f"embedding:{paper_id}")
        return json.loads(data) if data else None

    async def set_embeddings(self, paper_id: str, embedding: list[float]):
        """缓存嵌入向量"""
        await self.redis.set(
            f"embedding:{paper_id}",
            json.dumps(embedding),
            ex=3600  # 1小时过期
        )
```

## 9. 异步执行

```python
# 所有节点都定义为异步函数
async def search_papers(state: PipelineState) -> dict:
    ...

async def extract_kg(state: PipelineState) -> dict:
    ...

# 使用 ainvoke 执行图
result = await graph.ainvoke(initial_state)

# 流式执行
async for event in graph.astream(initial_state):
    print(f"Node {event['node']} completed")
```

## 10. 调试配置

```python
# 启用调试模式
graph = StateGraph(PipelineState)
# ... 添加节点和边 ...
compiled_graph = graph.compile(debug=True)

# 配置 LangSmith
import os
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGSMITH_API_KEY"] = "your-key"
os.environ["LANGSMITH_PROJECT"] = "academic-cluster"

# 在每个节点添加日志
import structlog
logger = structlog.get_logger()

async def search_papers(state: PipelineState) -> dict:
    logger.info("Starting paper search", query=state["query"])
    # ... 执行逻辑 ...
    logger.info("Search completed", paper_count=len(papers))
    return {"papers": papers}
```

## 11. 完整图定义

```python
from langgraph.graph import StateGraph, END

# 创建图
workflow = StateGraph(PipelineState)

# 添加节点
workflow.add_node("search", search_papers)
workflow.add_node("deduplicate", deduplicate_papers)
workflow.add_node("filter", filter_papers)
workflow.add_node("bm25", bm25_selection)
workflow.add_node("embedding", generate_embeddings)
workflow.add_node("pgvector_knn", store_and_knn)
workflow.add_node("rerank", rerank_papers)
workflow.add_node("kg_extraction", extract_knowledge_graph)
workflow.add_node("community_detection", detect_communities)
workflow.add_node("visualize_community", visualize_and_push_frontend)
workflow.add_node("evidence_cards", generate_evidence_cards)
workflow.add_node("gap_analysis", analyze_gaps)
workflow.add_node("targeted_refine", targeted_refinement)
workflow.add_node("outline_generation", generate_outline)
workflow.add_node("user_confirm", confirm_outline)  # 中断点
workflow.add_node("write_review", write_review)
workflow.add_node("coverage_audit", audit_coverage)
workflow.add_node("section_revision", revise_sections)
workflow.add_node("artifact_registration", register_artifacts)
workflow.add_node("finalize", finalize_run)

# 添加边
workflow.set_entry_point("search")
workflow.add_edge("search", "deduplicate")
workflow.add_edge("deduplicate", "filter")
workflow.add_edge("filter", "bm25")
workflow.add_edge("bm25", "embedding")
workflow.add_edge("embedding", "pgvector_knn")
workflow.add_edge("pgvector_knn", "rerank")
workflow.add_edge("rerank", "kg_extraction")
workflow.add_edge("kg_extraction", "community_detection")
workflow.add_edge("community_detection", "visualize_community")
workflow.add_edge("visualize_community", "evidence_cards")
workflow.add_edge("evidence_cards", "gap_analysis")

# 条件边：差距分析后决定路径
workflow.add_conditional_edges(
    "gap_analysis",
    should_continue_to_writing,
    {
        "targeted_refine": "targeted_refine",
        "outline_generation": "outline_generation"
    }
)

workflow.add_edge("targeted_refine", "evidence_cards")  # 循环回去
workflow.add_edge("outline_generation", "user_confirm")
workflow.add_edge("user_confirm", "write_review")
workflow.add_edge("write_review", "coverage_audit")

# 条件边：覆盖审计后决定路径
workflow.add_conditional_edges(
    "coverage_audit",
    should_revise_sections,
    {
        "section_revision": "section_revision",
        "artifact_registration": "artifact_registration"
    }
)

workflow.add_edge("section_revision", "coverage_audit")  # 循环回去
workflow.add_edge("artifact_registration", "finalize")
workflow.add_edge("finalize", END)

# 编译图
app = workflow.compile(
    debug=True,
    checkpointer=MemorySaver()
)
```

## 12. 前端推送机制

```python
from fastapi import WebSocket

class FrontendPusher:
    """推送给前端的服务"""

    def __init__(self):
        self.connections: dict[str, WebSocket] = {}

    async def push_community_visualization(self, project_id: str, data: dict):
        """推送社区聚类可视化数据"""
        ws = self.connections.get(project_id)
        if ws:
            await ws.send_json({
                "type": "community_visualization",
                "data": data
            })

# 在节点中调用
async def visualize_and_push_frontend(state: PipelineState) -> dict:
    """生成可视化并推送给前端"""
    visualization = generate_visualization(state)

    # 推送给前端
    await frontend_pusher.push_community_visualization(
        state["project_id"],
        visualization
    )

    return {"community_visualization": visualization}
```
