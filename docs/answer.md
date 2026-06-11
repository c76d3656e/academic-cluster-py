# Academic Cluster 项目问答文档

基于实际代码实现回答面试问题。

---

## 1. LangChain/LangGraph 的区别

**LangChain** 是一个用于构建 LLM 应用的工具链框架，提供模型调用、提示词管理、链式调用等基础组件。

**LangGraph** 是 LangChain 生态中用于构建有状态、多步骤 Agent 工作流的框架，基于有向图（StateGraph）实现节点编排和条件路由。

本项目使用 LangGraph 构建 24 节点 DAG Pipeline：

```python
# src/academic_cluster/graphs/graph.py:107-217
def create_pipeline_graph() -> StateGraph:
    workflow = StateGraph(PipelineState)

    # 添加 21 个节点
    workflow.add_node("search", search_node)
    workflow.add_node("deduplicate", deduplicate_node)
    workflow.add_node("filter", filter_node)
    workflow.add_node("bm25", bm25_node)
    workflow.add_node("embedding", embedding_node)
    workflow.add_node("pgvector_knn", pgvector_knn_node)
    workflow.add_node("rerank", rerank_node)
    # ... 更多节点

    # 条件路由
    workflow.add_conditional_edges(
        "gap_analysis",
        should_continue_to_writing,
        {
            "targeted_refine": "targeted_refine",
            "outline_generation": "outline_generation",
        },
    )
```

**关键区别**：
- LangChain：线性链式调用（Chain），无状态
- LangGraph：图结构编排，支持条件路由、循环、状态管理、人工中断

---

## 2. LangGraph 踩坑

### 2.1 状态字段必须与节点返回值匹配

```python
# src/academic_cluster/graphs/state.py:15-80
class PipelineState(BaseModel):
    # 如果节点返回的 key 在 State 中不存在，会报 AttributeError
    coverage_score: float = 0.0  # 必须显式声明
    invalid_citation_count: int = 0
    needs_revision: bool = False
```

踩坑：`coverage_audit_node` 返回 `coverage_score` 但 `PipelineState` 中未定义，导致 `AttributeError: 'PipelineState' object has no attribute 'coverage_score'`。

### 2.2 Annotated[list, add] 的累加行为

```python
# src/academic_cluster/graphs/state.py:30-31
errors: Annotated[list[str], add] = Field(default_factory=list)
paper_ids: Annotated[list[str], add] = Field(default_factory=list)
```

使用 `Annotated[list, add]` 会让多次节点返回的列表自动拼接，而非覆盖。

### 2.3 条件路由必须覆盖所有可能的返回值

```python
# src/academic_cluster/graphs/graph.py:183-190
workflow.add_conditional_edges(
    "gap_analysis",
    should_continue_to_writing,
    {
        "targeted_refine": "targeted_refine",
        "outline_generation": "outline_generation",
    },
)
```

如果条件函数返回的 key 不在映射中，会抛出 `KeyError`。

### 2.4 循环必须有终止条件

```python
# src/academic_cluster/graphs/graph.py:62-78
def should_revise_sections(state: PipelineState) -> str:
    # 必须有退出条件，否则无限循环
    if state.coverage_score < 0.8 or state.invalid_citation_count > 0:
        return "section_revision"
    return "artifact_registration"
```

踩坑：`coverage_audit` 在无内容时返回 `coverage_score = 0.0`，导致无限循环。修复：无内容时返回 `1.0`。

---

## 3. RAG 原理，用的什么 Embedding 模型

### RAG 原理

RAG（Retrieval-Augmented Generation）= 检索 + 增强 + 生成：

1. **检索**：从知识库中检索与查询相关的文档
2. **增强**：将检索结果注入到 LLM 的上下文中
3. **生成**：LLM 基于增强上下文生成回答

本项目 RAG 流程：

```python
# src/academic_cluster/graphs/nodes/embedding.py:19-42
async def generate_embedding(text: str) -> list[float]:
    """调用 SiliconFlow 的 BAAI/bge-m3 生成嵌入向量"""
    settings = get_settings()
    url = f"{settings.embedding.api_url}/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.embedding.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.embedding.model,  # BAAI/bge-m3
        "input": text,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]
```

### Embedding 模型选择

使用 **BAAI/bge-m3**（1024 维），通过 SiliconFlow API 调用：

```python
# src/academic_cluster/config/settings.py:24-30
class EmbeddingSettings(BaseModel):
    provider: str = "siliconflow"
    model: str = "BAAI/bge-m3"
    api_url: str = "https://api.siliconflow.cn/v1"
    api_key: Optional[str] = None
    dimensions: int = 1024
```

选择 bge-m3 的原因：
- 支持中英文双语
- 1024 维向量，精度与效率平衡
- 支持稠密、稀疏、多向量三种检索模式

---

## 4. 上下文压缩方式

本项目采用**分层压缩**策略：

### 4.1 论文级压缩

只存储论文 ID，详情存储在 PostgreSQL：

```python
# src/academic_cluster/graphs/state.py:34-36
# 论文 ID 列表（详情存储在 PostgreSQL）
paper_ids: Annotated[list[str], add] = Field(default_factory=list)
total_searched: int = 0
```

### 4.2 嵌入级压缩

嵌入向量存储在 pgvector，状态只保留 ID：

```python
# src/academic_cluster/graphs/state.py:44-46
embedding_ids: list[str] = Field(default_factory=list)
knn_graph_id: Optional[str] = None
```

### 4.3 写作时压缩

写作时只取前 50 篇论文的标题+摘要：

```python
# src/academic_cluster/graphs/nodes/write_review.py:48-51
papers_context = "\n\n".join([
    f"[{i+1}] {p.get('title', '')}\n{p.get('abstract', '')}"
    for i, p in enumerate(papers[:50])
])
```

---

## 5. Fallback 是怎么做的

### 5.1 Provider 级 Fallback

```python
# src/academic_cluster/services/provider_manager.py:157-204
async def execute_with_provider(self, provider_type, func, *args, **kwargs):
    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        provider = self.get_provider(provider_type)  # 自动选择健康 provider
        if not provider:
            raise ValueError(f"No provider available for {provider_type}")

        try:
            async with provider._semaphore:
                result = await func(provider, *args, **kwargs)
                provider.request_count += 1
                provider.is_healthy = True
                return result
        except Exception as e:
            last_error = e
            provider.error_count += 1
            # 连续失败 3 次标记为不健康
            if provider.error_count >= 3:
                provider.is_healthy = False

    raise last_error
```

### 5.2 健康检查与自动恢复

```python
# src/academic_cluster/services/provider_manager.py:206-229
async def _health_check_loop(self):
    while True:
        await asyncio.sleep(60)  # 每分钟检查一次
        for provider_type, providers in self._providers.items():
            for provider in providers:
                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            f"{provider.api_url}/models",
                            headers={"Authorization": f"Bearer {provider.api_key}"},
                            timeout=5.0,
                        )
                        if response.status_code == 200:
                            provider.is_healthy = True
                            provider.error_count = 0
                        else:
                            provider.is_healthy = False
                except Exception:
                    provider.is_healthy = False
```

### 5.3 无健康 Provider 时重置

```python
# src/academic_cluster/services/provider_manager.py:143-148
healthy_providers = [p for p in providers if p.is_healthy]
if not healthy_providers:
    # 如果没有健康的提供商，重置所有提供商状态
    for p in providers:
        p.is_healthy = True
    healthy_providers = providers
```

---

## 6. AgentState 的作用是什么，为什么不使用全局变量

### AgentState 的作用

`PipelineState` 是 LangGraph 图节点间传递的**唯一数据载体**：

```python
# src/academic_cluster/graphs/state.py:15-80
class PipelineState(BaseModel):
    # 元数据
    project_id: str
    query: str
    status: str = "created"
    errors: Annotated[list[str], add] = Field(default_factory=list)

    # 搜索阶段
    paper_ids: Annotated[list[str], add] = Field(default_factory=list)

    # 过滤阶段
    filtered_paper_ids: list[str] = Field(default_factory=list)
    core_paper_ids: list[str] = Field(default_factory=list)

    # 嵌入阶段
    embedding_ids: list[str] = Field(default_factory=list)

    # 聚类阶段
    cluster_ids: list[str] = Field(default_factory=list)

    # 写作阶段
    written_section_ids: list[str] = Field(default_factory=list)
```

### 为什么不使用全局变量

1. **并发安全**：多个 Pipeline 可能并行执行，全局变量会导致状态污染
2. **可检查点化**：LangGraph 支持将 State 序列化到数据库，实现断点续传
3. **可调试性**：State 是不可变的快照，每个节点的输入输出都可追溯
4. **人工干预**：通过 `interrupt_before` 可以在任意节点暂停，检查 State 后决定是否继续

```python
# src/academic_cluster/graphs/graph.py:220-261
def compile_graph(
    checkpointer=None,
    debug: bool = True,
    interrupt_before: list[str] | None = None,
):
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
    )
    return compiled
```

---

## 7. 整体的失败重试机制

### 7.1 Node 级重试

每个节点内部使用 try-except 捕获异常，记录到 `errors` 字段但不中断流程：

```python
# src/academic_cluster/graphs/nodes/search.py:48-56
for paper in unique_papers:
    paper_id = paper.get("id", str(uuid.uuid4()))
    paper["id"] = paper_id
    try:
        await db.save_paper(paper)
        paper_ids.append(paper_id)
    except Exception as e:
        logger.warning("Failed to save paper", paper_id=paper_id, error=str(e))
```

### 7.2 Provider 级重试

Provider Manager 自动重试 3 次，失败后切换 provider：

```python
# src/academic_cluster/services/provider_manager.py:169-172
max_retries = 3
last_error = None
for attempt in range(max_retries):
    provider = self.get_provider(provider_type)
```

### 7.3 Graph 级重试

通过条件路由实现图级别的错误处理：

```python
# src/academic_cluster/graphs/graph.py:81-100
def should_retry_on_error(state: PipelineState) -> str:
    if state.errors and state.retry_count < 3:
        return "retry"
    if state.errors:
        return END
    return "continue"
```

### 7.4 HTTP 级重试

使用 tenacity 或 httpx 内置重试：

```python
# src/academic_cluster/tools/academic_search.py:58-60
async with httpx.AsyncClient() as client:
    response = await client.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()
```

---

## 8. 讲一下你的实习项目

本项目（Academic Cluster）是一个**学术论文聚类和综述自动生成系统**：

**背景**：研究人员需要快速了解某个领域的研究现状，手动阅读和整理论文耗时巨大。

**技术栈**：
- LangGraph：24 节点 DAG Pipeline
- PostgreSQL + pgvector：向量存储和检索
- Redis：缓存嵌入向量和搜索结果
- 多数据源：arXiv、Semantic Scholar、PubMed、OpenAlex

**核心流程**：
1. 搜索 → 去重 → 过滤 → BM25
2. 嵌入 → KNN → Rerank
3. 知识图谱提取 → 社区检测
4. 证据卡片 → 差距分析 → 大纲生成
5. 综述写作 → 覆盖审计 → 产出物

---

## 9. 有什么难点亮点吗

### 亮点

1. **混合图构建**：5 种边信号（KNN 0.45、KG 关系 0.25、共享实体 0.15、证据 0.10、质量 0.05）
2. **Human-in-the-Loop**：通过 `interrupt_before` 实现人工确认大纲
3. **Provider 轮询**：支持多 LLM/Embedding/Rerank 提供商的优先级调度和故障转移
4. **SSE 实时推送**：向前端推送 Pipeline 执行进度和社区可视化数据

### 难点

1. **状态管理**：24 个节点间的状态传递和一致性
2. **向量检索性能**：pgvector HNSW 索引的调优
3. **错误恢复**：多层级重试机制的设计

---

## 10. AI 知识库用了啥向量数据库，为什么

使用 **pgvector**（PostgreSQL 扩展），而非独立向量数据库：

```sql
-- docker/postgres/init.sql:6
CREATE EXTENSION IF NOT EXISTS "vector";

-- docker/postgres/init.sql:31-39
CREATE TABLE IF NOT EXISTS embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id UUID REFERENCES papers(id) ON DELETE CASCADE,
    model_name VARCHAR(100) NOT NULL,
    vector vector(1024),
    dimensions INTEGER NOT NULL DEFAULT 1024,
    UNIQUE(paper_id, model_name)
);

-- HNSW 索引
CREATE INDEX IF NOT EXISTS idx_embeddings_vector
ON embeddings USING hnsw (vector vector_cosine_ops);
```

**选择 pgvector 的原因**：
1. **资源有限**：不需要额外部署 Milvus/Qdrant 等独立服务
2. **事务一致性**：论文元数据和向量在同一数据库，保证 ACID
3. **运维简单**：一个 PostgreSQL 实例搞定，不需要维护多个服务
4. **性能够用**：HNSW 索引在 10 万级数据上表现良好

---

## 11. Chunk 你是怎么切分的

本项目**不做 chunk 切分**，因为学术论文的结构天然适合整篇处理：

```python
# src/academic_cluster/graphs/nodes/embedding.py:66-70
for paper in papers:
    paper_id = paper.get("id")
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    text = f"{title} {abstract}".strip()  # 标题 + 摘要作为整体
```

**策略**：
- 标题 + 摘要拼接（通常 300-500 tokens）
- 不超过模型最大长度（bge-m3 支持 8192 tokens）
- 摘要已经是论文的语义压缩，无需进一步切分

---

## 12. 召回策略

### 多路召回

```python
# src/academic_cluster/tools/academic_search.py
async def search_all_sources(
    query: str,
    limit_per_source: int = 50,
    sources: list[str] = ["semantic_scholar", "arxiv"],
) -> list[dict]:
    # 并行搜索多个数据源
    tasks = []
    if "semantic_scholar" in sources:
        tasks.append(search_semantic_scholar(query, limit_per_source))
    if "arxiv" in sources:
        tasks.append(search_arxiv(query, limit_per_source))
    # ...
    results = await asyncio.gather(*tasks, return_exceptions=True)
```

### 混合检索

1. **BM25 关键词检索**：精确匹配专有名词
2. **向量语义检索**：语义相似度匹配
3. **KNN 图检索**：基于嵌入向量的近邻检索

```python
# src/academic_cluster/services/vector_store.py:59-94
async def search_similar(
    self,
    query_embedding: list[float],
    limit: int = 10,
    threshold: float = 0.5,
) -> list[dict]:
    async with self.db.session() as session:
        result = await session.execute(
            text("""
                SELECT paper_id, similarity
                FROM search_similar_papers(:query_embedding, :limit, :threshold)
            """),
            {
                "query_embedding": str(query_embedding),
                "limit": limit,
                "threshold": threshold,
            }
        )
```

---

## 13. 提示词工程主要做了什么

### Agent 提示词

```python
# src/academic_cluster/agents/writing.py
# 使用 langchain_openai 调用 LLM
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model=settings.llm.model,
    base_url=settings.llm.base_url,
    api_key=settings.llm.api_key,
    temperature=settings.llm.temperature,
)
```

### 提示词策略

1. **角色设定**：指定 LLM 为学术写作专家
2. **上下文注入**：将论文摘要和证据卡片注入提示词
3. **格式约束**：要求输出 Markdown 格式
4. **引用规范**：要求使用 [N] 格式引用论文

---

## 14. Token 是什么

Token 是 LLM 处理文本的最小单位：

- 英文：约 1 token = 4 字符（"hello" = 1 token）
- 中文：约 1 token = 1-2 个汉字
- 代码：按语法单元切分

本项目中的 token 使用：

```python
# src/academic_cluster/config/settings.py:21
max_tokens: int = 4096  # LLM 最大输出 token 数
```

---

## 15. MCP 和 Skill 有什么区别

**MCP（Model Context Protocol）**：模型上下文协议，定义了模型与外部工具交互的标准接口。

**Skill**：Claude Code 中的可调用技能，是 MCP 的具体实现。

本项目使用 LangGraph 的 Tool Calling 机制：

```python
# src/academic_cluster/tools/academic_search.py
# 工具函数被 LangGraph 节点直接调用
async def search_arxiv(query: str, limit: int = 100) -> list[dict]:
    # 搜索 arXiv API
```

---

## 16. Agent 的本质是什么

Agent = LLM（推理） + Tools（执行） + Memory（记忆） + Planning（规划）

本项目中的 Agent 实现：

```python
# src/academic_cluster/agents/query_planning.py
# 使用 LLM 进行查询规划
async def plan_queries(query: str) -> list[str]:
    # LLM 分析查询，生成多个搜索子查询
```

LangGraph 中的 Agent 模式：

```python
# 节点 = Agent 的执行单元
workflow.add_node("search", search_node)  # 搜索 Agent
workflow.add_node("kg_extraction", kg_extraction_node)  # 知识图谱 Agent
workflow.add_node("write_review", write_review_node)  # 写作 Agent
```

---

## 17. Transformer 的原理

Transformer = Self-Attention + Feed-Forward + LayerNorm

在本项目中，Transformer 被用于：
1. **Embedding 模型**（bge-m3）：将文本编码为向量
2. **Rerank 模型**（bge-reranker-v2-m3）：计算 query-document 相关性
3. **LLM**（GPT-4o/GLM）：生成综述内容

```python
# src/academic_cluster/graphs/nodes/embedding.py:27-28
payload = {
    "model": settings.embedding.model,  # BAAI/bge-m3 (Transformer-based)
    "input": text,
}
```

---

## 18. 多注意力机制

多头注意力（Multi-Head Attention）将 Q、K、V 分成多个头并行计算：

- 每个头关注不同的语义子空间
- 最终拼接所有头的输出

本项目使用的 bge-m3 模型内部使用多头注意力机制进行文本编码。

---

## 19. RAG 流程描述

```python
# 完整 RAG 流程
# 1. 检索
papers = await search_all_sources(query, limit=2, sources=["arxiv"])

# 2. 嵌入
embedding = await generate_embedding(text)  # 1024 维向量

# 3. 存储
await vector_store.add_embeddings(paper_ids, embeddings)

# 4. 相似度检索
similar = await vector_store.search_similar(query_embedding, limit=10)

# 5. 重排序
reranked = await rerank_papers(query, papers)

# 6. 生成
content = await write_section(section_plan, papers_context)
```

---

## 20. SSE 和 WebSocket、单次调用区别

本项目使用 **SSE（Server-Sent Events）**：

```python
# src/academic_cluster/api/sse.py:119-150
async def sse_generator(project_id: str, request: Request) -> AsyncGenerator[str, None]:
    manager = get_sse_manager()
    queue = await manager.connect(project_id)

    try:
        yield f"event: connected\ndata: {json.dumps({'project_id': project_id})}\n\n"

        while True:
            if await request.is_disconnected():
                break

            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                event_type = event.get("type", "message")
                data = json.dumps(event.get("data", {}))
                yield f"event: {event_type}\ndata: {data}\n\n"
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
    finally:
        await manager.disconnect(project_id, queue)
```

**区别**：
- **单次调用**：请求-响应，无状态
- **SSE**：服务端单向推送，适合进度通知
- **WebSocket**：双向通信，适合实时交互

本项目选择 SSE 因为只需要服务端向客户端推送进度，无需双向通信。

---

## 21. Human-in-the-Loop 实现

```python
# src/academic_cluster/graphs/graph.py:242-244
# 默认在 user_confirm 前中断
if interrupt_before is None:
    interrupt_before = ["user_confirm"]
```

```python
# src/academic_cluster/graphs/nodes/user_confirm.py
async def user_confirm_node(state: PipelineState) -> dict:
    logger.info("Waiting for user confirmation", outline_id=state.outline_id)
    # LangGraph 会在此处暂停，等待用户确认
    logger.info("User confirmed outline")
    return {"status": "outline_confirmed"}
```

使用方式：

```python
# 运行时传入 interrupt_before=[] 可跳过人工确认
graph = compile_graph(debug=True, interrupt_before=[])
result = await graph.ainvoke(initial_state, config={"configurable": {"thread_id": project_id}})
```

---

## 22. 异步同步和并发并行的区别

本项目全面使用 **async/await**：

```python
# src/academic_cluster/tools/academic_search.py:340-360
async def search_all_sources(...) -> list[dict]:
    tasks = []
    if "semantic_scholar" in sources:
        tasks.append(search_semantic_scholar(query, limit_per_source))
    if "arxiv" in sources:
        tasks.append(search_arxiv(query, limit_per_source))

    # 并发执行多个搜索任务
    results = await asyncio.gather(*tasks, return_exceptions=True)
```

**区别**：
- **同步**：阻塞等待，一次只做一件事
- **异步**：非阻塞，遇到 IO 切换到其他任务
- **并行**：多核 CPU 同时执行多个任务
- **并发**：单核 CPU 通过时间片轮转模拟同时执行

Python asyncio 是**并发**（单线程），不是**并行**（多线程）。

---

## 23. 搜索的 ReAct 过程

ReAct = Reasoning + Acting

本项目中的 ReAct 模式：

```python
# src/academic_cluster/agents/query_planning.py
# 1. Reasoning：LLM 分析查询，生成搜索策略
queries = await plan_queries(query)

# 2. Acting：执行搜索
for q in queries:
    papers = await search_all_sources(q)

# 3. 观察结果，决定是否继续
if len(papers) < threshold:
    # 生成新的搜索策略
    refined_queries = await refine_queries(query, papers)
```

---

## 24. 如何提升搜索的速度

1. **并发搜索**：多个数据源并行搜索
2. **缓存机制**：Redis 缓存搜索结果和嵌入向量
3. **HNSW 索引**：pgvector 的 HNSW 索引加速向量检索
4. **批量处理**：批量生成嵌入向量

```python
# src/academic_cluster/services/cache.py:82-96
async def get_embedding(self, paper_id: str, model_name: str) -> Optional[list[float]]:
    key = f"embedding:{model_name}:{paper_id}"
    return await self.get(key)

async def set_embedding(self, paper_id: str, model_name: str, embedding: list[float], expire: int = 86400):
    key = f"embedding:{model_name}:{paper_id}"
    return await self.set(key, embedding, expire=expire)
```

---

## 25. 知识图谱

本项目构建学术论文知识图谱：

```python
# src/academic_cluster/graphs/nodes/kg_extraction.py
# 提取实体（论文、作者、方法、数据集）
# 提取关系（引用、使用、改进）

# src/academic_cluster/services/database.py:203-260
async def save_kg_entities(self, entities: list[dict]) -> list[str]:
    # 保存实体到 kg_entities 表

async def save_kg_relations(self, relations: list[dict]) -> list[str]:
    # 保存关系到 kg_relations 表
```

---

## 26. Agent 编排范式

本项目使用 **LangGraph 的 DAG 编排范式**：

```python
# src/academic_cluster/graphs/graph.py
# 线性流程
search → deduplicate → filter → bm25 → embedding → pgvector_knn → rerank

# 条件分支
gap_analysis → (targeted_refine | outline_generation)

# 循环
section_revision → coverage_audit → (section_revision | artifact_registration)
```

**编排范式分类**：
1. **中心化编排**：一个调度器控制所有 Agent（本项目采用）
2. **去中心化协作**：Agent 之间直接通信
3. **分层编排**：多层级 Agent 管理
4. **事件驱动**：基于事件触发 Agent 执行

---

## 27. 大模型幻觉怎么解决

1. **RAG**：基于检索结果生成，不凭空捏造
2. **引用规范**：要求 LLM 引用具体论文编号
3. **覆盖审计**：检查生成内容是否基于检索结果

```python
# src/academic_cluster/graphs/nodes/coverage_audit.py
# 检查引用覆盖率
coverage_score = 1.0 - (invalid_citations / total_citations)
needs_revision = coverage_score < 0.8 or invalid_citations > 0
```

---

## 28. 如何选择 Embedding 模型

**选择标准**：
1. **维度**：1024 维（bge-m3）在精度和效率间平衡
2. **多语言**：支持中英文
3. **最大长度**：支持 8192 tokens
4. **API 可用性**：SiliconFlow 提供稳定 API

```python
# src/academic_cluster/config/settings.py:24-30
class EmbeddingSettings(BaseModel):
    provider: str = "siliconflow"
    model: str = "BAAI/bge-m3"
    dimensions: int = 1024
```

---

## 29. 多轮对话是如何实现的

本项目**不涉及多轮对话**，是单次 Pipeline 执行。但 LangGraph 的 State 机制天然支持多轮：

```python
# 通过 checkpointer 保存对话历史
checkpointer = MemorySaver()
graph = workflow.compile(checkpointer=checkpointer)

# 每次调用传入 thread_id
config = {"configurable": {"thread_id": project_id}}
result = await graph.ainvoke(initial_state, config=config)
```

---

## 30. 如何解决 Lost in Middle 问题

**Lost in Middle**：LLM 对上下文中间部分的关注度低于首尾。

**解决方案**：
1. **重要信息前置**：将最相关的论文放在上下文开头
2. **分段处理**：将长上下文分成多段，分别处理后合并
3. **Rerank**：重排序确保最相关内容在前

```python
# src/academic_cluster/graphs/nodes/rerank.py
async def rerank_papers(query: str, papers: list[dict]) -> list[dict]:
    # 使用 Rerank 模型重新排序，确保最相关内容在前
```

---

## 31. SSE 实时推送实现

```python
# src/academic_cluster/api/sse.py:20-105
class SSEManager:
    def __init__(self):
        self._connections: dict[str, list[asyncio.Queue]] = {}

    async def connect(self, project_id: str) -> asyncio.Queue:
        queue = asyncio.Queue()
        if project_id not in self._connections:
            self._connections[project_id] = []
        self._connections[project_id].append(queue)
        return queue

    async def send_progress(self, project_id: str, node: str, status: str, progress: float, message: str):
        await self.send_event(project_id, "progress", {
            "node": node,
            "status": status,
            "progress": progress,
            "message": message,
        })

    async def send_community_visualization(self, project_id: str, visualization: dict):
        await self.send_event(project_id, "community_visualization", visualization)
```

---

## 32. Hot Reload 支持

```python
# src/academic_cluster/services/provider_manager.py:104-118
def add_provider(self, provider_type: str, provider: Provider):
    """动态添加提供商"""
    if provider_type not in self._providers:
        raise ValueError(f"Unknown provider type: {provider_type}")

    self._providers[provider_type].append(provider)
    # 按优先级排序
    self._providers[provider_type].sort(key=lambda p: p.priority)

def remove_provider(self, provider_type: str, name: str):
    """动态移除提供商"""
    self._providers[provider_type] = [
        p for p in self._providers[provider_type]
        if p.name != name
    ]
```

---

## 33. Docker Compose 部署

```yaml
# docker-compose.yml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-academic_cluster}
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}
    ports:
      - "${POSTGRES_PORT:-5433}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./docker/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD:-redis}
    ports:
      - "${REDIS_PORT:-6379}:6379"
```

---

## 34. E2E 测试

```python
# tests/e2e/test_pipeline.py:17-64
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_pipeline():
    project_id = str(uuid.uuid4())
    query = "transformer attention mechanism"

    initial_state = PipelineState(
        project_id=project_id,
        query=query,
        config={
            "limit_per_source": 2,  # 每个数据源 2 篇
            "sources": ["arxiv"],
            "max_embedding_papers": 5,
            "core_reference_count": 3,
            "auxiliary_reference_count": 2,
        },
    )

    graph = compile_graph(debug=True, interrupt_before=[])
    result = await graph.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": project_id}},
    )

    assert result is not None
    assert result.get("paper_ids") is not None
    assert len(result.get("paper_ids", [])) > 0
```

---

## 35. 向量化过程

```python
# 1. 文本准备
text = f"{title} {abstract}".strip()

# 2. 调用 Embedding API
payload = {
    "model": "BAAI/bge-m3",
    "input": text,
}
response = await client.post(url, json=payload, headers=headers)
embedding = response.json()["data"][0]["embedding"]  # 1024 维浮点数组

# 3. 存储到 pgvector
await session.execute(
    text("""
        INSERT INTO embeddings (paper_id, model_name, vector, dimensions)
        VALUES (:paper_id, :model_name, :vector, :dimensions)
    """),
    {
        "paper_id": paper_id,
        "model_name": "bge-m3",
        "vector": str(embedding),  # pgvector 接受字符串格式
        "dimensions": len(embedding),
    }
)
```

---

## 36. 项目架构总结

```
academic_cluster/
├── api/
│   └── sse.py              # SSE 实时推送
├── agents/
│   ├── query_planning.py   # 查询规划 Agent
│   ├── kg_extraction.py    # 知识图谱提取 Agent
│   ├── evidence_generation.py  # 证据生成 Agent
│   └── writing.py          # 写作 Agent
├── config/
│   └── settings.py         # 配置管理
├── graphs/
│   ├── state.py            # 状态定义
│   ├── graph.py            # 图定义和编译
│   └── nodes/              # 21 个节点实现
├── services/
│   ├── database.py         # PostgreSQL 服务
│   ├── vector_store.py     # pgvector 向量存储
│   ├── cache.py            # Redis 缓存
│   └── provider_manager.py # Provider 管理
└── tools/
    ├── academic_search.py  # 学术搜索（arXiv/S2/PubMed/OpenAlex）
    └── clustering.py       # 聚类算法
```
