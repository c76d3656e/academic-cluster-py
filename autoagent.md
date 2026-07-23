# Academic Cluster 多 Agent 系统改进方案

> 本文档定义了从当前固定 Pipeline 架构升级为自主多 Agent 系统的完整目标和实现路径。

---

## 一、现状分析

### 当前架构问题

```
当前：固定 Pipeline（函数式调用）
搜索 → 去重 → 筛选 → BM25 → 嵌入 → KNN → 重排序
  → 知识图谱 → 聚类 → 证据卡片 → 差距分析
  → 大纲 → 写作 → 审计 → 完成
```

**问题**：
- 20+ 个节点是普通函数，不是真正的 Agent
- 流程完全预定义，只有 2 个条件分支
- 无自主决策能力，无法根据中间结果调整策略
- 写作质量受限于固定 Prompt，无法自我改进

### 目标架构

```
目标：Hierarchical Supervisor + ReAct Workers

┌─────────────────────────────────────────────────────────────────┐
│                    Orchestrator Agent (顶层)                      │
│  职责：分析研究主题、制定策略、协调子 Agent、质量把关               │
│  模式：Plan-and-Execute + Reflexion                              │
└─────────────────────────┬───────────────────────────────────────┘
                          │ handoff
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  Research Team  │ │  Analysis Team  │ │  Writing Team   │
│  (检索团队)      │ │  (分析团队)      │ │  (写作团队)      │
├─────────────────┤ ├─────────────────┤ ├─────────────────┤
│ • Search Agent  │ │ • KG Agent      │ │ • Outline Agent │
│ • Filter Agent  │ │ • Cluster Agent │ │ • Writer Agent  │
│ • Ranker Agent  │ │ • Evidence Agent│ │ • Reviewer Agent│
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

---

## 二、核心架构模式

### 参考来源

| 项目/论文 | 架构模式 | 借鉴点 |
|-----------|----------|--------|
| Anthropic 多 Agent 系统 | Orchestrator-Workers | 并行子 Agent、动态任务分配 |
| Agent Laboratory | Plan-and-Execute + Reflexion | 迭代改进、质量把关 |
| SciAgents | Swarm Intelligence | 知识图谱导航、假设生成 |
| PaperDebugger | 多 Agent 协作 | Reviewer/Writer 分离 |
| ReAct (Yao et al., 2023) | 推理+行动交替 | 工具调用循环 |
| Reflexion (Shinn et al., 2023) | 自我批评+修正 | 质量迭代改进 |

### 模式选择

| 阶段 | 模式 | 原因 |
|------|------|------|
| 顶层编排 | **Supervisor** | 需要审计和可观测性 |
| 检索阶段 | **ReAct** | 短视距、探索性任务 |
| 分析阶段 | **ReAct** | 工具调用密集 |
| 写作阶段 | **Plan-and-Execute + Reflexion** | 长视距、需要质量保证 |

---

## 三、State 设计（四层状态架构）

### 文件位置

```
src/academic_cluster/agents/state.py
```

### 第一层：共享状态（Agent 间通信）

```python
class SharedResearchState(TypedDict):
    """所有 Agent 共享的全局状态"""

    # === 任务元数据 ===
    project_id: str
    research_topic: str
    current_phase: Annotated[str, lambda old, new: new]  # last-write-wins

    # === 消息流（Agent 间通信的核心）===
    messages: Annotated[list, add_messages]

    # === 检索结果（Research Team → Analysis Team）===
    paper_ids: Annotated[list[str], add]
    relevant_paper_ids: Annotated[list[str], add]

    # === 分析结果（Analysis Team → Writing Team）===
    kg_entity_ids: Annotated[list[str], add]
    kg_relation_ids: Annotated[list[str], add]
    evidence_card_ids: Annotated[list[str], add]
    cluster_ids: Annotated[list[str], add]

    # === 写作结果（Writing Team → Orchestrator）===
    outline: dict[str, Any] | None
    section_ids: Annotated[list[str], add]
    final_review: str | None

    # === 质量指标 ===
    quality_scores: Annotated[list[dict], add]
    revision_count: int

    # === 错误追踪 ===
    errors: Annotated[list[str], add]
```

### 第二层：Agent 隔离状态（内部记忆）

```python
class OrchestratorMemory(BaseModel):
    """Orchestrator 的内部记忆"""
    decisions_made: list[dict] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    team_performance: dict[str, float] = Field(default_factory=dict)
    current_strategy: str = "balanced"  # "broad" | "focused" | "balanced"
    quality_threshold: float = 7.0

class ResearcherMemory(BaseModel):
    """Research Agent 的内部记忆"""
    queries_used: list[str] = Field(default_factory=list)
    discovered_keywords: list[str] = Field(default_factory=list)
    strategy_effectiveness: dict[str, float] = Field(default_factory=dict)
    paper_summaries: dict[str, str] = Field(default_factory=dict)
    blind_spots: list[str] = Field(default_factory=list)

class WriterMemory(BaseModel):
    """Writer Agent 的内部记忆"""
    style_guide: dict[str, Any] = Field(default_factory=lambda: {
        "tone": "academic",
        "citation_format": "[N]",
        "paragraph_length": "medium",
    })
    written_sections: list[dict] = Field(default_factory=list)
    citation_usage: dict[str, list[str]] = Field(default_factory=dict)
    review_feedback: list[dict] = Field(default_factory=list)
    common_issues: list[str] = Field(default_factory=list)
```

### 第三层：持久化状态（存储到数据库）

```python
class AgentExecutionRecord(BaseModel):
    """Agent 执行记录（存储到 PostgreSQL）"""
    execution_id: str
    agent_name: str
    project_id: str
    input_state: dict[str, Any]
    output_state: dict[str, Any]
    duration_ms: int
    token_usage: dict[str, int]
    tool_calls: list[dict]
    decisions: list[dict]
    quality_score: float | None
```

### 第四层：上下文注入状态（运行时）

```python
class AgentContext(TypedDict):
    """Agent 运行时上下文（不持久化）"""
    agent_name: str
    available_tools: list[str]
    token_budget: int
    tokens_used: int
    time_budget_ms: int
    time_used_ms: int
    relevant_memories: list[str]
    task_description: str
```

---

## 四、Memory 设计（四层记忆架构）

### 文件位置

```
src/academic_cluster/agents/memory.py
```

### 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    Memory Manager                            │
├─────────────────────────────────────────────────────────────┤
│  Working Memory    │ 当前上下文窗口，消息压缩管理            │
│  Episodic Memory   │ 历史交互记录，向量存储+相似度检索        │
│  Semantic Memory   │ 提炼的知识，知识图谱存储                │
│  Procedural Memory │ 行为模式，成功/失败策略记录              │
└─────────────────────────────────────────────────────────────┘
```

### Working Memory（工作记忆）

```python
class WorkingMemory:
    """
    工作记忆 - 管理当前上下文窗口

    核心职责：
    1. 压缩历史消息，保留关键信息
    2. 注入相关记忆
    3. 管理 token 预算
    """

    def __init__(self, max_tokens: int = 128000):
        self.max_tokens = max_tokens
        self.messages: list = []
        self.summaries: list[str] = []

    def add_message(self, message: Any) -> None:
        """添加消息，必要时压缩"""
        self.messages.append(message)
        total_tokens = self._estimate_tokens()
        if total_tokens > self.max_tokens * 0.8:
            self._compress_messages()

    def get_context(self, query: str, max_items: int = 50) -> list:
        """获取当前上下文"""
        context = []
        if self.summaries:
            context.append(HumanMessage(content=f"历史摘要：{self.summaries[-1]}"))
        context.extend(self.messages[-max_items:])
        return context
```

### Episodic Memory（情景记忆）

```python
class EpisodicMemory:
    """
    情景记忆 - 存储和检索历史交互

    使用向量数据库存储，按相似度检索
    """

    def __init__(self, vector_store=None):
        self.vector_store = vector_store
        self.episodes: list[dict] = []

    async def store_episode(self, episode: dict) -> str:
        """存储一次交互记录"""
        episode_id = f"ep_{datetime.now().timestamp()}"
        episode_record = {
            "id": episode_id,
            "timestamp": datetime.now().isoformat(),
            "agent_name": episode["agent_name"],
            "task": episode["task"],
            "action": episode["action"],
            "result": episode["result"],
            "quality_score": episode.get("quality_score"),
        }
        self.episodes.append(episode_record)
        if self.vector_store:
            await self.vector_store.add_texts(
                texts=[f"{episode['task']} {episode['result']}"],
                metadatas=[episode_record],
                ids=[episode_id],
            )
        return episode_id

    async def recall_similar(self, query: str, k: int = 5) -> list[dict]:
        """检索相似的历史交互"""
        if not self.vector_store:
            return self._keyword_search(query, k)
        results = await self.vector_store.similarity_search(query=query, k=k)
        return [doc.metadata for doc in results]
```

### Semantic Memory（语义记忆）

```python
class SemanticMemory:
    """
    语义记忆 - 存储从经验中提炼的知识

    使用知识图谱存储实体和关系
    """

    def __init__(self, kg_service=None):
        self.kg_service = kg_service
        self.knowledge_base: dict[str, Any] = {
            "facts": [],
            "patterns": [],
            "preferences": {},
            "constraints": [],
        }

    async def store_fact(self, fact: str, source: str, confidence: float) -> None:
        """存储一个事实"""
        fact_record = {
            "fact": fact,
            "source": source,
            "confidence": confidence,
            "timestamp": datetime.now().isoformat(),
            "times_referenced": 0,
        }
        self.knowledge_base["facts"].append(fact_record)

    async def get_relevant_knowledge(self, query: str, max_items: int = 10) -> list[dict]:
        """获取相关知识"""
        relevant = []
        query_lower = query.lower()
        for fact in self.knowledge_base["facts"]:
            if any(word in fact["fact"].lower() for word in query_lower.split()):
                fact["times_referenced"] += 1
                relevant.append(fact)
        return relevant[:max_items]
```

### Procedural Memory（程序性记忆）

```python
class ProceduralMemory:
    """
    程序性记忆 - Agent 的行为模式和策略

    存储：
    1. 成功的工作流模式
    2. 失败的模式（避免重复）
    3. 优化的参数配置
    """

    def __init__(self):
        self.strategies: dict[str, dict] = {}
        self.failure_patterns: list[dict] = []
        self.optimized_params: dict[str, Any] = {}

    def record_strategy(self, strategy_name: str, context: str,
                       steps: list[str], outcome: str) -> None:
        """记录一个策略"""
        if strategy_name not in self.strategies:
            self.strategies[strategy_name] = {
                "name": strategy_name,
                "context": context,
                "steps": steps,
                "success_count": 0,
                "failure_count": 0,
            }
        strategy = self.strategies[strategy_name]
        if outcome == "success":
            strategy["success_count"] += 1
        else:
            strategy["failure_count"] += 1

    def get_best_strategy(self, context: str) -> dict | None:
        """获取最佳策略"""
        sorted_strategies = sorted(
            self.strategies.values(),
            key=lambda s: s["success_count"] / max(s["success_count"] + s["failure_count"], 1),
            reverse=True,
        )
        for strategy in sorted_strategies:
            if any(word in context.lower() for word in strategy["context"].lower().split()):
                return strategy
        return sorted_strategies[0] if sorted_strategies else None
```

### Memory Manager（统一管理）

```python
class MemoryManager:
    """
    记忆管理器 - 统一管理四层记忆
    """

    def __init__(self, project_id: str, vector_store=None, kg_service=None):
        self.project_id = project_id
        self.working = WorkingMemory()
        self.episodic = EpisodicMemory(vector_store)
        self.semantic = SemanticMemory(kg_service)
        self.procedural = ProceduralMemory()

    async def inject_context(self, query: str) -> str:
        """注入相关记忆到上下文"""
        context_parts = []

        # 1. 检索相似的历史交互
        similar_episodes = await self.episodic.recall_similar(query, k=3)
        if similar_episodes:
            context_parts.append("相关历史经验：")
            for ep in similar_episodes:
                context_parts.append(f"- {ep['task']}: {ep['result'][:100]}")

        # 2. 检索相关知识
        relevant_knowledge = await self.semantic.get_relevant_knowledge(query, k=5)
        if relevant_knowledge:
            context_parts.append("\n相关知识：")
            for know in relevant_knowledge:
                context_parts.append(f"- {know['fact']}")

        # 3. 获取最佳策略
        best_strategy = self.procedural.get_best_strategy(query)
        if best_strategy:
            context_parts.append(f"\n推荐策略：{best_strategy['name']}")

        return "\n".join(context_parts) if context_parts else ""

    async def record_interaction(self, agent_name: str, task: str,
                                action: str, result: str, quality_score: float = None) -> None:
        """记录一次交互"""
        await self.episodic.store_episode({
            "agent_name": agent_name,
            "task": task,
            "action": action,
            "result": result,
            "quality_score": quality_score,
        })
```

---

## 五、Tool 设计（学术研究专用工具）

### 文件位置

```
src/academic_cluster/tools/agent_tools.py
```

### 工具分类

| 类别 | 工具 | 用途 |
|------|------|------|
| **检索工具** | search_academic_papers | 多源并行搜索 |
| | read_paper_details | 读取论文详情 |
| | refine_search_strategy | 优化搜索策略 |
| **分析工具** | extract_knowledge_graph | 知识图谱抽取 |
| | generate_evidence_card | 证据卡片生成 |
| | analyze_research_gaps | 研究差距分析 |
| **写作工具** | create_review_outline | 综述大纲生成 |
| | write_review_section | 章节撰写 |
| | review_and_critique | 自我评审 |
| | verify_citation_accuracy | 引用验证 |
| **协调工具** | delegate_to_team | 任务委派 |
| | check_progress | 进度检查 |
| | request_revision | 修改请求 |

### 检索工具实现

```python
@tool
def search_academic_papers(
    query: Annotated[str, "搜索查询，使用学术关键词"],
    sources: Annotated[list[str], "数据源列表"] = None,
    limit: Annotated[int, "每个数据源返回的最大数量"] = 20,
    year_from: Annotated[int, "起始年份"] = None,
    year_to: Annotated[int, "结束年份"] = None,
) -> str:
    """
    搜索学术论文

    使用多个学术数据源并行搜索，返回论文列表。
    自动处理去重和排序。

    返回格式：JSON 数组
    """
    from ..services.database import get_database
    from ..tools.academic_search import search_semantic_scholar, search_pubmed, search_arxiv

    if sources is None:
        sources = ["semantic_scholar", "pubmed", "arxiv"]

    all_results = []
    for source in sources:
        try:
            if source == "semantic_scholar":
                results = search_semantic_scholar(query, limit=limit)
            elif source == "pubmed":
                results = search_pubmed(query, limit=limit)
            elif source == "arxiv":
                results = search_arxiv(query, limit=limit)
            else:
                continue
            all_results.extend(results)
        except Exception as e:
            logger.warning(f"Search failed for {source}", error=str(e))

    unique_results = _deduplicate_papers(all_results)
    unique_results.sort(key=lambda x: x.get("citations", 0), reverse=True)
    return json.dumps(unique_results[:limit], ensure_ascii=False)
```

### 分析工具实现

```python
@tool
def extract_knowledge_graph(
    paper_id: Annotated[str, "论文 ID"],
    entity_types: Annotated[list[str], "要提取的实体类型"] = None,
    relation_types: Annotated[list[str], "要提取的关系类型"] = None,
) -> str:
    """
    从论文中提取知识图谱

    使用 LLM 提取实体和关系，构建知识图谱。
    返回提取的实体和关系列表。
    """
    from ..agents.kg_extraction import extract_entities_and_relations
    from ..services.database import get_database

    db = get_database()
    paper = db.get_paper(paper_id)

    if not paper:
        return json.dumps({"error": f"Paper {paper_id} not found"})

    if entity_types is None:
        entity_types = ["ResearchProblem", "Method", "Dataset", "Metric", "Material", "Concept"]
    if relation_types is None:
        relation_types = ["uses", "improves", "outperforms", "addresses", "evaluates_on"]

    result = extract_entities_and_relations(
        text=paper.get("abstract", "") + " " + paper.get("full_text", "")[:5000],
        entity_types=entity_types,
        relation_types=relation_types,
    )

    return json.dumps({
        "paper_id": paper_id,
        "entities": result.get("entities", []),
        "relations": result.get("relations", []),
    }, ensure_ascii=False)
```

### 写作工具实现

```python
@tool
def write_review_section(
    section_title: Annotated[str, "章节标题"],
    section_plan: Annotated[dict, "章节计划"],
    context: Annotated[str, "上下文信息"],
    style_guide: Annotated[dict, "写作风格指南"] = None,
) -> str:
    """
    撰写综述的一个章节

    使用 LLM 生成学术风格的章节内容。
    自动处理引用格式和逻辑连贯性。
    """
    from ..services.section_writer import write_section

    if style_guide is None:
        style_guide = {
            "tone": "academic",
            "citation_format": "[N]",
            "paragraph_length": "medium",
        }

    content = write_section(
        title=section_title,
        plan=section_plan,
        context=context,
        style_guide=style_guide,
    )

    return json.dumps({
        "section_title": section_title,
        "content": content,
        "word_count": len(content.split()),
        "citation_count": content.count("["),
    }, ensure_ascii=False)

@tool
def review_and_critique(
    text: Annotated[str, "要评审的文本"],
    criteria: Annotated[list[str], "评审标准"] = None,
) -> str:
    """
    评审和批评文本

    使用 AAAI 审稿标准，提供详细的评审意见。
    用于 Reflexion 模式的自我改进。
    """
    from ..services.reviewer import review_text

    if criteria is None:
        criteria = ["completeness", "accuracy", "coherence", "depth"]

    review = review_text(text, criteria)

    return json.dumps({
        "score": review.get("score", 0),
        "strengths": review.get("strengths", []),
        "weaknesses": review.get("weaknesses", []),
        "suggestions": review.get("suggestions", []),
    }, ensure_ascii=False)
```

### 工具注册表

```python
# 各团队可用工具
RESEARCH_TOOLS = [
    "search_academic_papers",
    "read_paper_details",
    "refine_search_strategy",
]

ANALYSIS_TOOLS = [
    "extract_knowledge_graph",
    "generate_evidence_card",
    "analyze_research_gaps",
    "read_paper_details",
]

WRITING_TOOLS = [
    "create_review_outline",
    "write_review_section",
    "review_and_critique",
    "verify_citation_accuracy",
    "generate_evidence_card",
]

ORCHESTRATOR_TOOLS = [
    "delegate_to_team",
    "check_progress",
    "request_revision",
    "search_academic_papers",
    "review_and_critique",
]
```

---

## 六、Agent 定义

### 文件位置

```
src/academic_cluster/agents/orchestrator.py
src/academic_cluster/agents/research_team.py
src/academic_cluster/agents/analysis_team.py
src/academic_cluster/agents/writing_team.py
```

### Orchestrator Agent

```python
def create_orchestrator(research_team, analysis_team, writing_team):
    """创建顶层编排 Agent"""

    tools = [
        delegate_to_research_team,
        delegate_to_analysis_team,
        delegate_to_writing_team,
        check_progress,
        request_revision,
        save_findings,
        recall_findings,
    ]

    return create_react_agent(
        llm=ChatOpenAI(model="gpt-4o"),
        tools=tools,
        prompt=ORCHESTRATOR_PROMPT,
        name="orchestrator",
    )

ORCHESTRATOR_PROMPT = """你是学术研究项目的总协调员。

你的职责：
1. 分析研究主题，制定整体策略
2. 协调 Research、Analysis、Writing 三个团队
3. 监控进度和质量
4. 做出关键决策

工作流程：
1. 先让 Research Team 检索文献
2. 让 Analysis Team 分析和提取知识
3. 让 Writing Team 撰写综述
4. 评审质量，必要时请求修改
5. 最终确认完成

决策原则：
- 质量优先于速度
- 发现问题及时纠正
- 合理分配资源
"""
```

### Research Agent

```python
search_agent = create_react_agent(
    llm=ChatOpenAI(model="gpt-4o-mini"),
    tools=[
        search_semantic_scholar,
        search_pubmed,
        search_arxiv,
        refine_query,
        expand_search_scope,
    ],
    prompt="""你是学术文献检索专家。

你的任务：
1. 分析研究主题，制定搜索策略
2. 使用多个数据源并行搜索
3. 根据初步结果调整查询词
4. 确保覆盖相关子领域

工具使用原则：
- 先用 broad search 了解领域概况
- 再用 specific queries 找关键论文
- 发现新关键词时自动扩展搜索
""",
    name="search_agent",
)

filter_agent = create_react_agent(
    llm=ChatOpenAI(model="gpt-4o-mini"),
    tools=[
        read_paper_abstract,
        check_citation_count,
        check_publication_date,
        check_journal_quality,
        mark_relevant,
        mark_irrelevant,
    ],
    prompt="""你是论文质量评估专家。

筛选标准：
1. 相关性：论文是否直接涉及研究主题
2. 质量：期刊/会议影响力、引用数
3. 时效性：优先近 5 年的论文
4. 代表性：覆盖不同研究方向

对每篇论文给出：relevant/marginal/irrelevant 评级
""",
    name="filter_agent",
)
```

### Analysis Agent

```python
kg_agent = create_react_agent(
    llm=ChatOpenAI(model="gpt-4o"),
    tools=[
        read_paper_full,
        extract_entities,
        extract_relations,
        validate_triple,
        merge_to_graph,
        resolve_coreference,
    ],
    prompt="""你是知识图谱构建专家。

实体类型：ResearchProblem, Method, Dataset, Metric, Material, Concept, Domain
关系类型：uses, improves, outperforms, addresses, evaluates_on, ...

工作流程：
1. 仔细阅读全文，理解研究内容
2. 提取实体和关系，注意上下文
3. 验证三元组的准确性
4. 与现有知识图谱合并，处理冲突

关键原则：
- 宁可漏提，不要错提
- 保留原文证据（句子 ID）
- 处理指代消解（"our method" → 具体方法名）
""",
    name="kg_agent",
)

evidence_agent = create_react_agent(
    llm=ChatOpenAI(model="gpt-4o"),
    tools=[
        query_knowledge_graph,
        read_paper_section,
        summarize_finding,
        extract_key_claim,
        find_supporting_evidence,
        find_contradicting_evidence,
    ],
    prompt="""你是科学证据综合专家。

为每个研究主题生成证据卡片：
1. 核心发现（Claim）
2. 支持证据（Supporting Evidence）
3. 局限性（Limitations）
4. 研究共识度（Consensus Level）

使用知识图谱辅助分析，确保引用准确。
""",
    name="evidence_agent",
)
```

### Writing Agent

```python
writer_agent = create_react_agent(
    llm=ChatOpenAI(model="gpt-4o"),
    tools=[
        create_outline,
        write_section,
        revise_section,
        add_citation,
        check_citation_format,
        ensure_coherence,
        adjust_tone,
    ],
    prompt="""你是学术综述写作专家。

写作流程（Plan-and-Execute + Reflexion）：
1. 先创建详细大纲（Plan）
2. 逐节撰写（Execute）
3. 自我审查，检查逻辑连贯性（Reflexion）
4. 修订完善

写作规范：
- 使用学术语言，避免口语化
- 每个论点必须有引用支持
- 保持客观中立的立场
- 使用 [N] 格式引用，N 对应参考文献列表
""",
    name="writer_agent",
)

reviewer_agent = create_react_agent(
    llm=ChatOpenAI(model="gpt-4o"),
    tools=[
        read_section,
        check_logical_flow,
        check_citation_accuracy,
        check_completeness,
        suggest_improvements,
        request_revision,
    ],
    prompt="""你是学术综述审稿专家，使用 AAAI 审稿标准。

评估维度：
1. 完整性（Completeness）：是否覆盖所有重要研究
2. 准确性（Accuracy）：引用是否正确，论述是否准确
3. 连贯性（Coherence）：逻辑是否清晰，过渡是否自然
4. 深度（Depth）：分析是否深入，是否有洞察

输出格式：
- Score: 1-10
- Strengths: 优点列表
- Weaknesses: 问题列表
- Suggestions: 具体修改建议
""",
    name="reviewer_agent",
)
```

---

## 七、编排逻辑

### 文件位置

```
src/academic_cluster/agents/graph.py（重构）
```

### 主图定义

```python
def create_academic_research_system():
    """创建完整的学术研究 Agent 系统"""

    # 1. 创建各个团队的 Agent
    research_team = create_research_team()
    analysis_team = create_analysis_team()
    writing_team = create_writing_team()

    # 2. 创建顶层编排器
    orchestrator = create_orchestrator(
        research_team, analysis_team, writing_team
    )

    # 3. 构建图
    workflow = StateGraph(SharedResearchState)

    # 添加节点
    workflow.add_node("orchestrator", orchestrator)
    workflow.add_node("research_team", research_team)
    workflow.add_node("analysis_team", analysis_team)
    workflow.add_node("writing_team", writing_team)
    workflow.add_node("quality_check", quality_check_node)

    # 定义边
    workflow.set_entry_point("orchestrator")

    # Orchestrator 自主决定调用哪个团队
    workflow.add_conditional_edges(
        "orchestrator",
        route_to_team,
        {
            "research": "research_team",
            "analysis": "analysis_team",
            "writing": "writing_team",
            "quality_check": "quality_check",
            "finish": END,
        }
    )

    # 团队完成后返回 orchestrator
    workflow.add_edge("research_team", "orchestrator")
    workflow.add_edge("analysis_team", "orchestrator")
    workflow.add_edge("writing_team", "orchestrator")
    workflow.add_edge("quality_check", "orchestrator")

    return workflow.compile()

def route_to_team(state: SharedResearchState) -> str:
    """根据 orchestrator 的输出决定路由"""
    last_message = state["messages"][-1]
    if "research" in last_message.content:
        return "research"
    elif "analysis" in last_message.content:
        return "analysis"
    elif "writing" in last_message.content:
        return "writing"
    elif "check" in last_message.content:
        return "quality_check"
    else:
        return "finish"
```

---

## 八、实现路径

### 分阶段实施

| 阶段 | 目标 | 工作量 | 收益 | 依赖 |
|------|------|--------|------|------|
| **Phase 1** | 写作阶段改为 Agent | 2-3 天 | 写作质量提升 50%+ | 无 |
| **Phase 2** | 检索阶段改为 Agent | 2-3 天 | 检索召回率提升 | 无 |
| **Phase 3** | 分析阶段改为 Agent | 3-5 天 | KG 质量提升 | 无 |
| **Phase 4** | 引入 Orchestrator | 3-5 天 | 全流程自主决策 | Phase 1-3 |
| **Phase 5** | Memory 系统集成 | 3-5 天 | 跨项目学习 | Phase 4 |
| **Phase 6** | 优化和调优 | 持续 | 成本和质量平衡 | Phase 5 |

### Phase 1：写作阶段改造（优先）

**目标**：将写作阶段从固定函数改为 ReAct Agent

**任务清单**：
- [ ] 创建 `src/academic_cluster/agents/writing_team.py`
- [ ] 实现 Writer Agent（Plan-and-Execute 模式）
- [ ] 实现 Reviewer Agent（Reflexion 模式）
- [ ] 创建写作相关工具（write_section, review_and_critique, verify_citation）
- [ ] 修改 `graph.py`，将写作节点替换为 Agent 调用
- [ ] 添加质量门控（评审分数 >= 7 才通过）
- [ ] 测试和调优

**预期效果**：
- 写作质量从 6/10 提升到 8/10
- 引用准确率从 80% 提升到 95%
- 支持自我修订，减少人工干预

### Phase 2：检索阶段改造

**目标**：将检索阶段改为自适应搜索 Agent

**任务清单**：
- [ ] 创建 `src/academic_cluster/agents/research_team.py`
- [ ] 实现 Search Agent（ReAct 模式）
- [ ] 实现 Filter Agent（质量评估）
- [ ] 创建检索相关工具（search_papers, refine_query, expand_scope）
- [ ] 实现搜索策略学习（记住有效的查询词）
- [ ] 修改 `graph.py`，将检索节点替换为 Agent 调用
- [ ] 测试和调优

**预期效果**：
- 检索召回率提升 30%
- 自动发现相关子领域
- 减少无效搜索

### Phase 3：分析阶段改造

**目标**：将分析阶段改为智能分析 Agent

**任务清单**：
- [ ] 创建 `src/academic_cluster/agents/analysis_team.py`
- [ ] 实现 KG Agent（知识图谱抽取）
- [ ] 实现 Evidence Agent（证据卡片生成）
- [ ] 创建分析相关工具（extract_kg, generate_evidence, analyze_gaps）
- [ ] 实现增量知识图谱更新
- [ ] 修改 `graph.py`，将分析节点替换为 Agent 调用
- [ ] 测试和调优

**预期效果**：
- 知识图谱质量提升
- 证据卡片更准确
- 支持增量更新

### Phase 4：引入 Orchestrator

**目标**：实现顶层自主决策

**任务清单**：
- [ ] 创建 `src/academic_cluster/agents/orchestrator.py`
- [ ] 实现 Orchestrator Agent（Supervisor 模式）
- [ ] 实现 Handoff 工具（团队间委派）
- [ ] 实现进度监控和质量把关
- [ ] 重构 `graph.py`，使用 Orchestrator 编排
- [ ] 测试和调优

**预期效果**：
- 全流程自主决策
- 动态资源分配
- 智能质量控制

### Phase 5：Memory 系统集成

**目标**：实现跨项目学习

**任务清单**：
- [ ] 创建 `src/academic_cluster/agents/memory.py`
- [ ] 实现 Working Memory（上下文管理）
- [ ] 实现 Episodic Memory（历史交互存储）
- [ ] 实现 Semantic Memory（知识提炼）
- [ ] 实现 Procedural Memory（策略学习）
- [ ] 集成向量数据库（pgvector）
- [ ] 实现记忆注入机制
- [ ] 测试和调优

**预期效果**：
- 跨项目知识复用
- 搜索策略自动优化
- 写作风格持续改进

---

## 九、成本控制策略

| 策略 | 说明 | 实施方式 |
|------|------|----------|
| **分层模型** | Orchestrator 用 GPT-4o，Worker 用 GPT-4o-mini | 模型配置 |
| **Token 预算** | 每个 Agent 设置 max_tokens 上限 | AgentContext |
| **提前终止** | 质量达标时提前结束循环 | 质量门控 |
| **缓存** | 相同查询复用结果 | Redis 缓存 |
| **批量处理** | 多篇论文并行处理 | 并发工具调用 |
| **摘要压缩** | 旧消息压缩为摘要 | WorkingMemory |

### Token 预算分配

| Agent | 每次调用预算 | 每项目总预算 |
|-------|-------------|-------------|
| Orchestrator | 4K tokens | 50K tokens |
| Search Agent | 2K tokens | 30K tokens |
| Filter Agent | 1K tokens | 20K tokens |
| KG Agent | 4K tokens | 100K tokens |
| Evidence Agent | 3K tokens | 50K tokens |
| Writer Agent | 8K tokens | 200K tokens |
| Reviewer Agent | 4K tokens | 60K tokens |

---

## 十、文件结构

```
src/academic_cluster/
├── agents/
│   ├── __init__.py
│   ├── state.py              # 状态定义（四层）
│   ├── memory.py             # 记忆系统（四层）
│   ├── orchestrator.py       # 顶层编排器
│   ├── research_team.py      # 检索团队
│   ├── analysis_team.py      # 分析团队
│   ├── writing_team.py       # 写作团队
│   ├── graph.py              # 图定义（重构）
│   ├── query_planning.py     # 查询规划（保留）
│   ├── kg_extraction.py      # KG 抽取（保留）
│   ├── evidence_generation.py # 证据生成（保留）
│   ├── section_evaluator.py  # 章节评估（保留）
│   ├── section_outline.py    # 章节大纲（保留）
│   └── writing.py            # 写作（重构）
├── tools/
│   ├── __init__.py
│   ├── agent_tools.py        # Agent 专用工具（新增）
│   ├── academic_search.py    # 学术搜索（已有）
│   ├── clustering.py         # 聚类工具（已有）
│   ├── json_repair.py        # JSON 修复（已有）
│   ├── doi.py                # DOI 工具（已有）
│   └── text_processing.py    # 文本处理（已有）
├── services/
│   ├── ...                   # 现有服务
│   ├── evidence_generator.py # 证据生成（新增）
│   ├── gap_analyzer.py       # 差距分析（新增）
│   ├── reviewer.py           # 评审服务（新增）
│   └── memory_store.py       # 记忆存储（新增）
└── ...
```

---

## 十一、现有系统集成

### 现有可观测性系统

当前项目已有完整的可观测性基础设施，多 Agent 架构必须复用而非重建：

#### 1. structlog 日志系统

```python
# 已有配置：src/academic_cluster/services/observability.py
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(ensure_ascii=False),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(structlog, log_level.upper(), 20)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
```

**Agent 集成要求**：
- 每个 Agent 必须使用 `structlog.get_logger()` 获取 logger
- Agent 名称必须通过 ContextVar 注入日志上下文
- 工具调用必须记录 input/output 摘要

#### 2. PipelineTracker 审计追踪器

```python
# 已有实现：src/academic_cluster/services/observability.py
class PipelineTracker:
    """
    Pipeline 级别的审计追踪器。

    每次 Pipeline 执行创建一个实例，追踪所有节点和 LLM 调用。
    所有数据通过 callable 注入持久化到数据库。
    """

    async def start(self, db_create_run: Callable) -> str:
        """启动 pipeline run 记录"""

    async def begin_node(self, node_name: str, node_type: str = "llm") -> None:
        """开始节点执行"""

    async def end_node(self, node_name: str, status: str = "succeeded") -> None:
        """结束节点执行"""

    async def begin_llm_call(self, call_type: str, provider_name: str, model_name: str) -> str:
        """记录 LLM 调用开始"""

    async def end_llm_call(self, call_id: str, status: str = "success") -> None:
        """记录 LLM 调用完成"""

    async def finish(self, status: str = "succeeded") -> dict:
        """完成 pipeline run，返回 token 用量汇总"""
```

**Agent 集成要求**：
- 每个 Agent 调用必须调用 `tracker.begin_node()` 和 `tracker.end_node()`
- Agent 内部的 LLM 调用必须通过 `tracker.begin_llm_call()` 和 `tracker.end_llm_call()` 追踪
- Agent 的 token 用量必须聚合到 `TokenUsageTracker`

#### 3. LLMCallbackHandler 回调处理器

```python
# 已有实现：src/academic_cluster/services/observability.py
class LLMCallbackHandler(BaseCallbackHandler):
    """
    捕获所有 LangChain LLM 调用的回调处理器。

    自动记录:
    - 每次 LLM/Embedding/Rerank 调用的 token 用量
    - provider 信息（从 ContextVar 或 metadata 获取）
    - 调用耗时
    - 错误信息
    """
```

**Agent 集成要求**：
- Agent 的 LLM 调用必须传入 `callbacks=[llm_callback]`
- Agent 的工具调用必须记录到 `db_caller`

#### 4. PipelineStatusCallback 状态更新

```python
# 已有实现：src/academic_cluster/services/observability.py
class PipelineStatusCallback(BaseCallbackHandler):
    """
    在 LangGraph 节点开始执行时更新项目状态。

    解决 stream_mode="updates" 只在节点完成后才 emit 事件的问题。
    通过 on_chain_start 在节点实际开始前更新状态。
    """
```

**Agent 集成要求**：
- Agent 节点必须触发 `PipelineStatusCallback`
- 状态格式必须为 `running:{agent_name}`

---

### 现有审计系统

#### 1. 覆盖率审计 (Coverage Audit)

```python
# 已有实现：src/academic_cluster/services/coverage_audit.py
@dataclass
class CoverageAuditReport:
    """覆盖率审计报告"""

    # 高层指标（基点，10000 = 100%）
    cluster_coverage_bp: int = 0      # 簇覆盖率
    candidate_coverage_bp: int = 0    # 候选覆盖率
    weighted_coverage_bp: int = 0     # 加权覆盖率
    assembly_retention_bp: int = 0    # 组装保留率

    # 计数
    cited_core_count: int = 0         # 核心论文引用数
    cited_auxiliary_count: int = 0    # 辅助论文引用数
    total_candidates: int = 0         # 总候选数
    total_cited: int = 0              # 总引用数

    # 诊断
    orphan_clusters: list[str] = field(default_factory=list)      # 孤立簇
    uncovered_candidates: list[str] = field(default_factory=list)  # 未覆盖候选

    # 门控结果
    passes: bool = False

# 质量阈值
MIN_WEIGHTED_COVERAGE_BP: int = 8000  # 80%
MIN_ASSEMBLY_RETENTION_BP: int = 9000  # 90%
```

**Agent 集成要求**：
- Writing Agent 完成后必须调用覆盖率审计
- 覆盖率不达标时必须触发修订循环
- 审计结果必须记录到 `PipelineTracker`

#### 2. 章节评估器 (Section Evaluator)

```python
# 已有实现：src/academic_cluster/agents/section_evaluator.py
# 五维度评估体系
_DIMENSION_WEIGHTS = {
    "coverage": 0.25,     # 覆盖度
    "logic": 0.25,        # 逻辑链
    "citations": 0.20,    # 引用质量
    "transitions": 0.15,  # 过渡自然度
    "style": 0.15,        # 风格规范
}

# 修订阈值
_REVISION_THRESHOLD = 75  # 低于 75 分需要修订

# Blind 评估维度
_BLIND_DIMENSION_WEIGHTS = {
    "outline_coherence": 0.30,     # 大纲连贯性
    "reference_adequacy": 0.30,    # 引用充分性
    "task_coverage": 0.20,         # 任务覆盖度
    "scope_completeness": 0.20,    # 范围完整性
}

# 综合评估权重（blind vs visible）
_BLIND_WEIGHT = 0.3
_VISIBLE_WEIGHT = 0.7
```

**Agent 集成要求**：
- Reviewer Agent 必须复用现有评估维度和权重
- 评估结果必须与现有数据库 schema 兼容
- 修订阈值必须可配置

---

### 多 Agent 架构与现有系统的集成方案

#### 1. 日志集成

```python
# Agent 日志装饰器
def log_agent_execution(agent_name: str):
    """装饰器：自动记录 Agent 执行日志"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            logger = structlog.get_logger()
            logger.info("agent_started", agent=agent_name)

            start_time = time.monotonic()
            try:
                result = await func(*args, **kwargs)
                elapsed = time.monotonic() - start_time

                logger.info("agent_finished",
                           agent=agent_name,
                           elapsed_seconds=round(elapsed, 2),
                           status="success")
                return result
            except Exception as e:
                elapsed = time.monotonic() - start_time
                logger.error("agent_failed",
                            agent=agent_name,
                            elapsed_seconds=round(elapsed, 2),
                            error=str(e))
                raise
        return wrapper
    return decorator

# 使用示例
@log_agent_execution("research_agent")
async def run_research_agent(state: SharedResearchState) -> dict:
    """执行检索 Agent"""
    ...
```

#### 2. 审计集成

```python
# Agent 审计追踪器
class AgentTracker:
    """Agent 级别的审计追踪器，包装 PipelineTracker"""

    def __init__(self, pipeline_tracker: PipelineTracker, agent_name: str):
        self.tracker = pipeline_tracker
        self.agent_name = agent_name
        self.execution_id: str | None = None

    async def start(self) -> None:
        """开始 Agent 执行"""
        self.execution_id = await self.tracker.begin_node(
            node_name=self.agent_name,
            node_type="agent",
        )

    async def track_tool_call(self, tool_name: str, input_data: dict, output_data: dict) -> None:
        """追踪工具调用"""
        logger = structlog.get_logger()
        logger.info("tool_called",
                   agent=self.agent_name,
                   tool=tool_name,
                   input_summary=_summarize_output(input_data),
                   output_summary=_summarize_output(output_data))

    async def track_llm_call(self, provider: str, model: str,
                             prompt_tokens: int, completion_tokens: int,
                             latency_ms: int) -> None:
        """追踪 LLM 调用"""
        call_id = await self.tracker.begin_llm_call(
            call_type="agent_llm",
            provider_name=provider,
            model_name=model,
        )
        await self.tracker.end_llm_call(
            call_id=call_id,
            status="success",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )

    async def finish(self, status: str = "succeeded", quality_score: float = None) -> None:
        """完成 Agent 执行"""
        await self.tracker.end_node(
            node_name=self.agent_name,
            status=status,
            output_summary={"quality_score": quality_score} if quality_score else None,
        )
```

#### 3. 评估集成

```python
# Agent 评估包装器
class AgentEvaluator:
    """Agent 评估器，复用现有评估体系"""

    def __init__(self):
        self.section_evaluator = None  # 复用现有评估器
        self.coverage_auditor = None   # 复用现有审计器

    async def evaluate_agent_output(self, agent_name: str, output: dict) -> dict:
        """评估 Agent 输出质量"""

        if agent_name == "writing_agent":
            # 使用现有章节评估器
            return await self._evaluate_section(output)
        elif agent_name == "research_agent":
            # 评估检索质量
            return await self._evaluate_search_quality(output)
        elif agent_name == "analysis_agent":
            # 评估分析质量
            return await self._evaluate_analysis_quality(output)
        else:
            return {"score": 8.0, "passed": True}

    async def _evaluate_section(self, section: dict) -> dict:
        """评估章节质量（复用现有评估器）"""
        from .section_evaluator import evaluate_section

        evaluation = evaluate_section(
            content=section.get("content", ""),
            outline=section.get("plan", {}),
            references=section.get("citations", []),
        )

        # 计算加权分数
        weighted_score = sum(
            evaluation["dimensions"][dim]["score"] * weight
            for dim, weight in _DIMENSION_WEIGHTS.items()
        )

        return {
            "score": weighted_score,
            "passed": weighted_score >= _REVISION_THRESHOLD,
            "dimensions": evaluation["dimensions"],
            "revision_instructions": evaluation.get("revision_instructions"),
        }

    async def _evaluate_search_quality(self, search_result: dict) -> dict:
        """评估检索质量"""
        papers_found = search_result.get("papers_found", 0)
        relevant_count = search_result.get("relevant_count", 0)

        relevance_ratio = relevant_count / max(papers_found, 1)

        return {
            "score": relevance_ratio * 10,
            "passed": relevance_ratio >= 0.3,
            "metrics": {
                "papers_found": papers_found,
                "relevant_count": relevant_count,
                "relevance_ratio": relevance_ratio,
            },
        }

    async def _evaluate_analysis_quality(self, analysis_result: dict) -> dict:
        """评估分析质量"""
        entities = analysis_result.get("entities", 0)
        relations = analysis_result.get("relations", 0)
        evidence_cards = analysis_result.get("evidence_cards", 0)

        # 简单评分逻辑
        score = min(10, (entities + relations + evidence_cards) / 10)

        return {
            "score": score,
            "passed": score >= 6,
            "metrics": {
                "entities": entities,
                "relations": relations,
                "evidence_cards": evidence_cards,
            },
        }
```

#### 4. 状态同步

```python
# Agent 状态同步器
class AgentStateSync:
    """Agent 状态同步器，确保 Agent 状态与数据库一致"""

    def __init__(self, db, project_id: str):
        self.db = db
        self.project_id = project_id

    async def sync_agent_start(self, agent_name: str) -> None:
        """同步 Agent 开始状态"""
        await self.db.update_project_status(
            self.project_id,
            f"running:{agent_name}"
        )

    async def sync_agent_progress(self, agent_name: str, progress: dict) -> None:
        """同步 Agent 进度"""
        await self.db.update_agent_progress(
            self.project_id,
            agent_name,
            progress,
        )

    async def sync_agent_finish(self, agent_name: str, result: dict) -> None:
        """同步 Agent 完成状态"""
        await self.db.update_agent_result(
            self.project_id,
            agent_name,
            result,
        )
```

---

### 现有系统集成架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                    Multi-Agent System                            │
├─────────────────────────────────────────────────────────────────┤
│  Orchestrator Agent                                              │
│    ├── AgentTracker (包装 PipelineTracker)                       │
│    ├── AgentEvaluator (复用 section_evaluator)                   │
│    └── AgentStateSync (同步数据库状态)                            │
├─────────────────────────────────────────────────────────────────┤
│  Research Agent                                                  │
│    ├── AgentTracker                                              │
│    ├── LLMCallbackHandler (自动捕获 token 用量)                  │
│    └── structlog (结构化日志)                                     │
├─────────────────────────────────────────────────────────────────┤
│  Analysis Agent                                                  │
│    ├── AgentTracker                                              │
│    ├── LLMCallbackHandler                                        │
│    └── structlog                                                 │
├─────────────────────────────────────────────────────────────────┤
│  Writing Agent                                                   │
│    ├── AgentTracker                                              │
│    ├── AgentEvaluator (五维度评估)                                │
│    ├── CoverageAuditReport (覆盖率审计)                           │
│    └── structlog                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    现有基础设施                                    │
├─────────────────────────────────────────────────────────────────┤
│  PipelineTracker ──→ PostgreSQL (pipeline_runs, node_executions) │
│  TokenUsageTracker ──→ PostgreSQL (llm_calls)                    │
│  structlog ──→ JSON 日志文件                                      │
│  CoverageAuditReport ──→ PostgreSQL (coverage_audits)            │
│  SectionEvaluator ──→ PostgreSQL (section_evaluations)           │
└─────────────────────────────────────────────────────────────────┘
```

---

### 数据库 Schema 扩展

现有数据库表需要扩展以支持多 Agent：

```sql
-- 新增：Agent 执行记录表
CREATE TABLE agent_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_run_id UUID REFERENCES pipeline_runs(id),
    agent_name VARCHAR(100) NOT NULL,
    agent_type VARCHAR(50) NOT NULL,  -- 'orchestrator', 'research', 'analysis', 'writing'

    -- 输入输出
    input_state JSONB,
    output_state JSONB,

    -- 性能指标
    duration_ms INTEGER,
    token_usage JSONB,
    tool_calls JSONB,

    -- 决策记录
    decisions JSONB,

    -- 质量评估
    quality_score FLOAT,
    evaluation_details JSONB,

    -- 时间戳
    started_at TIMESTAMP DEFAULT NOW(),
    finished_at TIMESTAMP,

    -- 索引
    INDEX idx_agent_executions_pipeline (pipeline_run_id),
    INDEX idx_agent_executions_agent (agent_name)
);

-- 新增：Agent 决策记录表
CREATE TABLE agent_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_execution_id UUID REFERENCES agent_executions(id),
    decision_type VARCHAR(100) NOT NULL,
    decision_data JSONB,
    reason TEXT,
    confidence FLOAT,
    created_at TIMESTAMP DEFAULT NOW(),

    INDEX idx_agent_decisions_execution (agent_execution_id)
);

-- 新增：Agent 工具调用记录表
CREATE TABLE agent_tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_execution_id UUID REFERENCES agent_executions(id),
    tool_name VARCHAR(100) NOT NULL,
    input_data JSONB,
    output_data JSONB,
    duration_ms INTEGER,
    status VARCHAR(20) DEFAULT 'success',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),

    INDEX idx_agent_tool_calls_execution (agent_execution_id)
);

-- 新增：Agent 记忆表（长期记忆）
CREATE TABLE agent_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    agent_name VARCHAR(100) NOT NULL,
    memory_type VARCHAR(50) NOT NULL,  -- 'episodic', 'semantic', 'procedural'
    content JSONB,
    embedding VECTOR(1536),  -- pgvector 向量
    relevance_score FLOAT,
    access_count INTEGER DEFAULT 0,
    last_accessed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    INDEX idx_agent_memories_project (project_id),
    INDEX idx_agent_memories_agent (agent_name),
    INDEX idx_agent_memories_type (memory_type)
);
```

---

## 十二、质量指标

### 现有质量指标（必须保持）

| 指标 | 定义 | 来源 | 目标值 |
|------|------|------|--------|
| **加权覆盖率** | weighted_coverage_bp | CoverageAuditReport | >= 8000 (80%) |
| **组装保留率** | assembly_retention_bp | CoverageAuditReport | >= 9000 (90%) |
| **章节评估分数** | 五维度加权分数 | SectionEvaluator | >= 75 |
| **LLM 调用次数** | 总 LLM 调用数 | TokenUsageTracker | 记录 |
| **Token 用量** | 总 token 消耗 | TokenUsageTracker | 记录 |
| **成本** | 总 API 成本 | TokenUsageTracker | 记录 |

### 新增 Agent 指标

| 指标 | 定义 | 来源 | 目标值 |
|------|------|------|--------|
| **Agent 任务完成率** | 成功完成的任务比例 | agent_executions | >= 95% |
| **Agent 质量分数** | Agent 输出的评估分数 | agent_executions.quality_score | >= 7/10 |
| **Agent Token 效率** | 每千字消耗的 Token 数 | agent_executions.token_usage | <= 5K |
| **Agent 响应时间** | 单个 Agent 调用耗时 | agent_executions.duration_ms | <= 30s |
| **Agent 修订次数** | 平均每章节修订次数 | agent_executions | <= 2 |
| **工具调用成功率** | 工具调用成功比例 | agent_tool_calls | >= 98% |
| **决策准确率** | Agent 决策的正确比例 | agent_decisions | >= 90% |

### 系统整体指标

| 指标 | 定义 | 来源 | 目标值 |
|------|------|------|--------|
| **综述质量** | 人工评审分数 | 人工评估 | >= 8/10 |
| **引用准确率** | 正确引用比例 | CoverageAuditReport | >= 95% |
| **覆盖完整性** | 重要研究覆盖比例 | CoverageAuditReport | >= 90% |
| **端到端耗时** | 从输入到输出总时间 | pipeline_runs | <= 30min |
| **成本** | 每篇综述的 API 成本 | TokenUsageTracker | <= $5 |

---

## 十三、Prompt 复用策略

### 现有 Prompt 清单

当前项目已有 **22 个 Prompt 模板**，存储在 `src/academic_cluster/prompts/` 目录：

| 类别 | 文件名 | 用途 | 复用方式 |
|------|--------|------|----------|
| **搜索** | parse_topic.md | 主题解析和搜索 query 生成 | Orchestrator Agent |
| | refine_query.md | 基于缺口的 query 补充 | Research Agent |
| | evaluate_search.md | 搜索结果评估 | Research Agent |
| | paper_filter.md | 论文筛选 | Filter Agent |
| | cluster_targeted_refine.md | 聚类定向补充搜索 | Research Agent |
| | decide_refinement.md | 是否需要补充搜索的判断 | Orchestrator Agent |
| **写作** | generate_outline.md | 大纲生成 | Writer Agent |
| | generate_outline_system.md | 大纲生成 system prompt | Writer Agent |
| | write_section.md | 章节写作 | Writer Agent |
| | write_system.md | 章节写作 system prompt | Writer Agent |
| | assemble_review.md | 综述拼装（过渡语句、统一风格） | Writer Agent |
| | generate_abstract.md | 全文后置摘要生成 | Writer Agent |
| | section_outline.md | 章节段落级写作规划 | Writer Agent |
| | review_structure.md | 综述结构指南 | Writer Agent |
| | review_style.md | 写作风格规范 | Writer Agent |
| | review_style-cn.md | 中文写作风格规范 | Writer Agent |
| **评估** | section_evaluator.md | 章节质量评估 | Reviewer Agent |
| **分析** | community_memory.md | 社区记忆综合 | Analysis Agent |
| | gap_analysis_judge.md | 差距分析 LLM judge | Analysis Agent |
| | inter_community_conflict.md | 跨社区冲突分析 | Analysis Agent |
| | topic_relevance_filter.md | Topic 相关性过滤评估 | Filter Agent |
| **修复** | kg_json_repair.md | KG JSON 修复 | KG Agent |

### Prompt 加载系统

```python
# 已有实现：src/academic_cluster/prompts/__init__.py
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent

def _load_prompt(name: str) -> str:
    """加载提示模板文件"""
    path = _PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""

# 便捷函数
def get_write_section_prompt() -> str:
    """获取章节写作提示"""
    return _load_prompt("write_section.md")

def get_section_evaluator_prompt() -> str:
    """获取章节质量评估提示"""
    return _load_prompt("section_evaluator.md")
```

### Agent Prompt 复用方案

#### 1. Writer Agent Prompt 复用

```python
# 复用现有 prompt，不重写
from ..prompts import (
    get_write_section_prompt,
    get_write_system_prompt,
    get_assemble_review_prompt,
    get_generate_outline_prompt,
    get_generate_outline_system_prompt,
    get_review_style_prompt,
)

WRITER_AGENT_PROMPT = f"""
你是学术综述写作专家。

## 写作风格规范
{get_review_style_prompt()}

## 工作流程
1. 使用 create_review_outline 创建大纲（参考 generate_outline prompt）
2. 使用 write_review_section 逐节撰写（参考 write_section prompt）
3. 使用 review_and_critique 自我评审
4. 使用 verify_citation_accuracy 验证引用
5. 根据评审意见修订（Reflexion 循环）

## 关键原则
- 使用学术语言，避免口语化
- 每个论点必须有引用支持
- 使用 [N] 格式引用
- 保持客观中立的立场
"""
```

#### 2. Reviewer Agent Prompt 复用

```python
# 复用现有 section_evaluator prompt
from ..prompts import get_section_evaluator_prompt

REVIEWER_AGENT_PROMPT = f"""
你是学术综述审稿专家。

## 评估标准
{get_section_evaluator_prompt()}

## 评估维度与权重
1. coverage（25%）：是否覆盖段落规划中的核心论点
2. logic（25%）：段落之间是否有清晰的逻辑链
3. citations（20%）：引用是否准确支撑论点
4. transitions（15%）：过渡是否自然
5. style（15%）：风格是否规范

## 输出格式
- Score: 0-100
- dimensions: 各维度分数和评语
- revision_instructions: 具体修改建议
- needs_revision: 是否需要修订（< 75 分需要修订）
"""
```

#### 3. Research Agent Prompt 复用

```python
# 复用现有搜索相关 prompt
from ..prompts import (
    get_parse_topic_prompt,
    get_refine_query_prompt,
    get_evaluate_search_prompt,
    get_paper_filter_prompt,
)

RESEARCH_AGENT_PROMPT = f"""
你是学术文献检索专家。

## 主题解析
{get_parse_topic_prompt()}

## 搜索策略优化
{get_refine_query_prompt()}

## 搜索结果评估
{get_evaluate_search_prompt()}

## 论文筛选标准
{get_paper_filter_prompt()}

## 工作流程
1. 分析研究主题，制定搜索策略
2. 使用 search_academic_papers 搜索论文
3. 评估搜索结果质量
4. 优化查询词，扩大搜索范围
5. 筛选高质量论文
"""
```

#### 4. Analysis Agent Prompt 复用

```python
# 复用现有分析相关 prompt
from ..prompts import (
    get_community_memory_prompt,
    get_gap_analysis_judge_prompt,
    get_inter_community_conflict_prompt,
    get_topic_relevance_filter_prompt,
)

ANALYSIS_AGENT_PROMPT = f"""
你是知识图谱和证据分析专家。

## 社区记忆综合
{get_community_memory_prompt()}

## 差距分析
{get_gap_analysis_judge_prompt()}

## 跨社区冲突分析
{get_inter_community_conflict_prompt()}

## Topic 相关性评估
{get_topic_relevance_filter_prompt()}

## 工作流程
1. 从论文中提取知识图谱
2. 生成证据卡片
3. 分析研究差距
4. 识别跨社区冲突
"""
```

### Prompt 模板变量注入

现有 prompt 使用 `{variable}` 占位符，Agent 需要动态注入：

```python
from ..prompts import get_write_section_prompt

def build_write_section_prompt(section_plan: dict, context: str) -> str:
    """构建章节写作 prompt，注入变量"""
    template = get_write_section_prompt()

    # 注入变量
    prompt = template.format(
        topic=section_plan.get("topic", ""),
        review_title=section_plan.get("review_title", ""),
        section_title=section_plan.get("title", ""),
        section_description=section_plan.get("description", ""),
        target_words=section_plan.get("target_words", 1000),
        cluster_data=context.get("cluster_data", ""),
        sample_papers=context.get("sample_papers", ""),
        references=context.get("references", ""),
        evidence_cards=context.get("evidence_cards", ""),
        section_outline=section_plan.get("outline", ""),
        prev_summary=context.get("prev_summary", ""),
        next_outline=context.get("next_outline", ""),
    )

    return prompt
```

### Prompt 版本管理

```python
# Prompt 版本追踪
PROMPT_VERSIONS = {
    "write_section.md": "2.1",  # 当前版本
    "section_evaluator.md": "1.5",
    "generate_outline.md": "1.8",
    # ...
}

def get_prompt_version(prompt_name: str) -> str:
    """获取 prompt 版本"""
    return PROMPT_VERSIONS.get(prompt_name, "unknown")

def log_prompt_usage(prompt_name: str, agent_name: str) -> None:
    """记录 prompt 使用情况"""
    version = get_prompt_version(prompt_name)
    logger.info("prompt_used",
               prompt=prompt_name,
               version=version,
               agent=agent_name)
```

---

## 十四、接口兼容性设计

### 现有接口清单

#### 1. API 接口（FastAPI）

```python
# 现有接口：src/academic_cluster/api/
POST /api/projects                    # 创建项目
GET  /api/projects/{id}               # 获取项目详情
POST /api/projects/{id}/run           # 启动 Pipeline
POST /api/projects/{id}/resume        # 恢复 Pipeline
GET  /api/projects/{id}/status        # 获取状态
GET  /api/projects/{id}/progress      # 获取进度（SSE）
GET  /api/projects/{id}/result        # 获取结果
POST /api/projects/{id}/confirm       # 用户确认
```

#### 2. 内部接口（Python 函数）

```python
# 现有接口：src/academic_cluster/graphs/graph.py
async def run_pipeline(
    query: str,
    project_id: str,
    config: dict[str, Any] | None = None,
    sse_manager: Any = None,
    auto_confirm: bool = True,
    resume: bool = False,
) -> dict[str, Any] | None

# 现有接口：src/academic_cluster/services/database.py
class Database:
    async def create_project(self, ...) -> str
    async def get_project(self, project_id: str) -> dict
    async def update_project_status(self, project_id: str, status: str) -> None
    async def create_pipeline_run(self, ...) -> str
    async def finish_pipeline_run(self, ...) -> None
    async def create_node_execution(self, ...) -> str
    async def finish_node_execution(self, ...) -> None
    async def create_llm_call(self, ...) -> str
    async def finish_llm_call(self, ...) -> None
```

### 接口兼容策略

#### 1. API 层兼容（不改变现有接口）

```python
# 新增接口（不影响现有接口）
POST /api/projects/{id}/run-agent     # 启动 Agent Pipeline（新增）
GET  /api/projects/{id}/agent-status  # 获取 Agent 状态（新增）
GET  /api/projects/{id}/agent-logs    # 获取 Agent 日志（新增）

# 现有接口保持不变
POST /api/projects/{id}/run           # 继续支持旧 Pipeline
```

#### 2. 内部接口兼容（适配器模式）

```python
# 适配器：将 Agent 输出转换为现有格式
class AgentOutputAdapter:
    """将 Agent 输出转换为现有 Pipeline 输出格式"""

    @staticmethod
    def adapt_result(agent_result: dict) -> dict:
        """适配 Agent 结果为 Pipeline 结果格式"""
        return {
            "paper_ids": agent_result.get("paper_ids", []),
            "kg_entity_ids": agent_result.get("kg_entity_ids", []),
            "kg_relation_ids": agent_result.get("kg_relation_ids", []),
            "evidence_card_ids": agent_result.get("evidence_card_ids", []),
            "cluster_ids": agent_result.get("cluster_ids", []),
            "final_review": agent_result.get("final_review", ""),
            "abstract": agent_result.get("abstract", ""),
            "bibtex": agent_result.get("bibtex", ""),
            "status": "completed",
        }

    @staticmethod
    def adapt_state(shared_state: SharedResearchState) -> PipelineState:
        """将 SharedResearchState 转换为现有 PipelineState"""
        return PipelineState(
            project_id=shared_state["project_id"],
            query=shared_state["research_topic"],
            paper_ids=shared_state.get("paper_ids", []),
            kg_entity_ids=shared_state.get("kg_entity_ids", []),
            kg_relation_ids=shared_state.get("kg_relation_ids", []),
            evidence_card_ids=shared_state.get("evidence_card_ids", []),
            cluster_ids=shared_state.get("cluster_ids", []),
            final_review=shared_state.get("final_review", ""),
            status="completed",
        )
```

#### 3. 数据库 Schema 兼容（增量迁移）

```sql
-- 新增表（不影响现有表）
CREATE TABLE agent_executions (...);
CREATE TABLE agent_decisions (...);
CREATE TABLE agent_tool_calls (...);
CREATE TABLE agent_memories (...);

-- 现有表添加字段（向后兼容）
ALTER TABLE pipeline_runs ADD COLUMN agent_mode BOOLEAN DEFAULT FALSE;
ALTER TABLE pipeline_runs ADD COLUMN agent_config JSONB;
```

#### 4. 配置兼容

```python
# 配置文件扩展（向后兼容）
# .env 新增配置
AGENT_MODE=false                    # 是否使用 Agent 模式（默认 false）
AGENT_MAX_STEPS=50                  # Agent 最大步数
AGENT_TOKEN_BUDGET=500000           # Agent token 预算
AGENT_QUALITY_THRESHOLD=7.0         # Agent 质量阈值

# 现有配置保持不变
LLM_PROVIDER=gitee
LLM_MODEL=internlm3-8b-instruct
```

### 接口迁移路径

```
Phase 1: 新增 Agent 接口，现有接口不变
    ↓
Phase 2: Agent 模式可选启用（AGENT_MODE=true）
    ↓
Phase 3: Agent 模式成为默认（但仍可回退）
    ↓
Phase 4: 移除旧 Pipeline 代码（可选）
```

---

## 十五、Checkpoint 机制

### 现有 Checkpoint 实现

```python
# 已有实现：src/academic_cluster/graphs/graph.py
async def get_checkpointer() -> BaseCheckpointSaver[Any]:
    """Get or create the graph checkpointer."""
    global _default_checkpointer
    if _default_checkpointer is not None:
        return _default_checkpointer

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg import AsyncConnection

        conn = await AsyncConnection.connect(
            conn_string, autocommit=True, prepare_threshold=0, row_factory=dict_row
        )
        asyncpg_checkpointer = AsyncPostgresSaver(conn)
        await asyncpg_checkpointer.setup()
        checkpointer: BaseCheckpointSaver[Any] = asyncpg_checkpointer
        _default_checkpointer = checkpointer
        return checkpointer
    except Exception as e:
        logger.warning("AsyncPostgresSaver unavailable, using MemorySaver fallback")
        from langgraph.checkpoint.memory import MemorySaver
        _default_checkpointer = MemorySaver()
        return _default_checkpointer
```

### Agent Checkpoint 设计

#### 1. 共享状态 Checkpoint

```python
# Agent 系统复用现有 Checkpoint 机制
def create_agent_graph():
    """创建 Agent 图，使用现有 Checkpoint"""

    workflow = StateGraph(SharedResearchState)

    # 添加节点
    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("research_team", research_team_node)
    workflow.add_node("analysis_team", analysis_team_node)
    workflow.add_node("writing_team", writing_team_node)

    # 编译图，使用现有 Checkpoint
    checkpointer = await get_checkpointer()
    compiled = workflow.compile(
        checkpointer=checkpointer,
        debug=True,
        interrupt_before=["user_confirm"],
    )

    return compiled
```

#### 2. Agent 内部状态 Checkpoint

```python
# Agent 内部状态需要单独 Checkpoint
class AgentCheckpoint:
    """Agent 内部状态 Checkpoint"""

    def __init__(self, agent_name: str, project_id: str):
        self.agent_name = agent_name
        self.project_id = project_id
        self.checkpoint_key = f"agent:{agent_name}:{project_id}"

    async def save(self, state: dict) -> None:
        """保存 Agent 状态"""
        from ..services.database import get_database
        db = get_database()

        await db.save_agent_checkpoint(
            key=self.checkpoint_key,
            state=state,
            agent_name=self.agent_name,
            project_id=self.project_id,
        )

    async def load(self) -> dict | None:
        """加载 Agent 状态"""
        from ..services.database import get_database
        db = get_database()

        checkpoint = await db.load_agent_checkpoint(self.checkpoint_key)
        return checkpoint

    async def clear(self) -> None:
        """清除 Agent 状态"""
        from ..services.database import get_database
        db = get_database()

        await db.clear_agent_checkpoint(self.checkpoint_key)
```

#### 3. 恢复机制

```python
# Agent 恢复逻辑
async def resume_agent_pipeline(
    project_id: str,
    agent_name: str = None,
) -> dict[str, Any] | None:
    """恢复 Agent Pipeline"""

    # 1. 加载共享状态
    checkpointer = await get_checkpointer()
    thread_config = {"configurable": {"thread_id": project_id}}

    # 2. 如果指定了 Agent，恢复该 Agent 的内部状态
    if agent_name:
        agent_checkpoint = AgentCheckpoint(agent_name, project_id)
        agent_state = await agent_checkpoint.load()
        if agent_state:
            logger.info("Resuming agent from checkpoint",
                       agent=agent_name,
                       project_id=project_id)

    # 3. 恢复 Pipeline
    graph = create_agent_graph()
    result = await graph.ainvoke(None, config=thread_config)

    return result
```

#### 4. Checkpoint 清理策略

```python
# Checkpoint 清理
class CheckpointCleanup:
    """Checkpoint 清理策略"""

    @staticmethod
    async def cleanup_old_checkpoints(days: int = 30) -> int:
        """清理超过 N 天的 Checkpoint"""
        from ..services.database import get_database
        db = get_database()

        count = await db.cleanup_checkpoints older_than(days)
        logger.info("Cleaned up old checkpoints", count=count, days=days)
        return count

    @staticmethod
    async def cleanup_project_checkpoints(project_id: str) -> None:
        """清理项目的 Checkpoint"""
        from ..services.database import get_database
        db = get_database()

        await db.cleanup_project_checkpoints(project_id)
        logger.info("Cleaned up project checkpoints", project_id=project_id)
```

---

## 十六、鲁棒性设计

### 1. Agent 超时控制

```python
import asyncio
from functools import wraps

def agent_timeout(seconds: int = 300):
    """Agent 超时装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=seconds,
                )
            except asyncio.TimeoutError:
                logger.error("Agent timeout",
                           agent=func.__name__,
                           timeout_seconds=seconds)
                raise AgentTimeoutError(f"Agent {func.__name__} timed out after {seconds}s")
        return wrapper
    return decorator

# 使用示例
@agent_timeout(seconds=300)
async def research_agent_node(state: SharedResearchState) -> dict:
    """Research Agent 节点"""
    ...
```

### 2. Agent 重试机制

```python
from tenacity import retry, stop_after_attempt, wait_exponential

# Agent 级别重试
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((LLMTimeoutError, LLMRateLimitError)),
)
async def call_llm_with_retry(llm, messages, **kwargs):
    """带重试的 LLM 调用"""
    return await llm.ainvoke(messages, **kwargs)

# 工具级别重试
@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=2, max=5),
)
async def call_tool_with_retry(tool, **kwargs):
    """带重试的工具调用"""
    return await tool.ainvoke(**kwargs)
```

### 3. 降级策略

```python
class AgentFallback:
    """Agent 降级策略"""

    @staticmethod
    async def fallback_to_pipeline(state: dict) -> dict:
        """降级到旧 Pipeline"""
        logger.warning("Falling back to legacy pipeline")

        from ..graphs.graph import run_pipeline
        result = await run_pipeline(
            query=state["research_topic"],
            project_id=state["project_id"],
            config=state.get("config"),
        )

        return AgentOutputAdapter.adapt_result(result)

    @staticmethod
    async def fallback_to_simple_agent(state: dict) -> dict:
        """降级到简化 Agent"""
        logger.warning("Falling back to simple agent mode")

        # 使用更简单的 Agent 配置
        simple_agent = create_simple_agent()
        result = await simple_agent.ainvoke(state)

        return result

    @staticmethod
    async def fallback_with_partial_results(state: dict, partial_results: dict) -> dict:
        """使用部分结果降级"""
        logger.warning("Using partial results",
                      completed_agents=list(partial_results.keys()))

        # 合并部分结果
        merged = {**state, **partial_results}
        merged["status"] = "partial"
        merged["warnings"] = ["部分 Agent 执行失败，使用已有结果"]

        return merged
```

### 4. 错误分类和处理

```python
class AgentError(Exception):
    """Agent 基础异常"""
    pass

class AgentTimeoutError(AgentError):
    """Agent 超时"""
    pass

class AgentTokenLimitError(AgentError):
    """Token 超限"""
    pass

class AgentQualityError(AgentError):
    """质量不达标"""
    pass

class AgentToolError(AgentError):
    """工具调用失败"""
    pass

class ErrorHandler:
    """错误处理器"""

    @staticmethod
    async def handle_error(error: Exception, state: dict, agent_name: str) -> dict:
        """统一错误处理"""

        if isinstance(error, AgentTimeoutError):
            # 超时：降级到简化模式
            return await AgentFallback.fallback_to_simple_agent(state)

        elif isinstance(error, AgentTokenLimitError):
            # Token 超限：压缩上下文后重试
            compressed_state = await compress_state(state)
            return await retry_agent(agent_name, compressed_state)

        elif isinstance(error, AgentQualityError):
            # 质量不达标：使用部分结果
            return await AgentFallback.fallback_with_partial_results(
                state, get_partial_results(state)
            )

        elif isinstance(error, AgentToolError):
            # 工具失败：重试或降级
            return await AgentFallback.fallback_to_pipeline(state)

        else:
            # 未知错误：记录并降级
            logger.error("Unknown agent error",
                        agent=agent_name,
                        error=str(error),
                        error_type=type(error).__name__)
            return await AgentFallback.fallback_to_pipeline(state)
```

### 5. 无进展检测器

```python
class ProgressDetector:
    """无进展检测器"""

    def __init__(self, max_no_progress: int = 5):
        self.max_no_progress = max_no_progress
        self.no_progress_count = 0
        self.last_state_hash = None

    def check_progress(self, state: dict) -> bool:
        """检查是否有进展，返回 True 表示有进展"""
        import hashlib

        # 计算状态哈希
        state_hash = hashlib.md5(
            str(sorted(state.items())).encode()
        ).hexdigest()

        if state_hash == self.last_state_hash:
            self.no_progress_count += 1
            if self.no_progress_count >= self.max_no_progress:
                return False  # 无进展
        else:
            self.no_progress_count = 0
            self.last_state_hash = state_hash

        return True  # 有进展

    def reset(self):
        """重置检测器"""
        self.no_progress_count = 0
        self.last_state_hash = None
```

### 6. Token 预算管理

```python
class TokenBudgetManager:
    """Token 预算管理器"""

    def __init__(self, total_budget: int = 500000):
        self.total_budget = total_budget
        self.used_tokens = 0
        self.agent_budgets = {}

    def allocate_budget(self, agent_name: str, budget: int) -> None:
        """为 Agent 分配预算"""
        self.agent_budgets[agent_name] = {
            "budget": budget,
            "used": 0,
        }

    def check_budget(self, agent_name: str, estimated_tokens: int) -> bool:
        """检查是否有足够预算"""
        agent_budget = self.agent_budgets.get(agent_name, {})
        remaining = agent_budget.get("budget", 0) - agent_budget.get("used", 0)

        if estimated_tokens > remaining:
            logger.warning("Token budget exceeded",
                          agent=agent_name,
                          estimated=estimated_tokens,
                          remaining=remaining)
            return False

        return True

    def record_usage(self, agent_name: str, tokens: int) -> None:
        """记录 token 使用"""
        if agent_name in self.agent_budgets:
            self.agent_budgets[agent_name]["used"] += tokens
        self.used_tokens += tokens

    def get_remaining(self, agent_name: str) -> int:
        """获取剩余预算"""
        agent_budget = self.agent_budgets.get(agent_name, {})
        return agent_budget.get("budget", 0) - agent_budget.get("used", 0)
```

### 7. 鲁棒性配置

```python
# 鲁棒性配置
ROBUSTNESS_CONFIG = {
    # 超时配置
    "timeouts": {
        "orchestrator": 600,      # 10 分钟
        "research_agent": 300,    # 5 分钟
        "analysis_agent": 300,    # 5 分钟
        "writing_agent": 600,     # 10 分钟
        "tool_call": 30,          # 30 秒
    },

    # 重试配置
    "retry": {
        "max_attempts": 3,
        "min_wait": 2,
        "max_wait": 10,
        "retryable_errors": [
            "LLMTimeoutError",
            "LLMRateLimitError",
            "NetworkError",
        ],
    },

    # Token 预算
    "token_budgets": {
        "total": 500000,
        "orchestrator": 50000,
        "research_agent": 100000,
        "analysis_agent": 150000,
        "writing_agent": 200000,
    },

    # 质量阈值
    "quality_thresholds": {
        "min_score": 70,
        "max_revision_attempts": 3,
    },

    # 进度检测
    "progress_detection": {
        "max_no_progress": 5,
        "check_interval": 10,  # 每 10 步检查一次
    },
}
```

---

## 十七、风险和缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| **Agent 无限循环** | 成本失控 | 设置 max_steps 硬上限 + 无进展检测器 |
| **质量不稳定** | 输出不可靠 | Reflexion 机制 + 质量门控 |
| **Token 超支** | 成本超预算 | Token 预算管理 + 提前终止 |
| **工具调用失败** | 流程中断 | 重试机制 + 降级策略 |
| **记忆污染** | 学习到错误模式 | 记忆验证 + 定期清理 |

---

## 十八、参考资料

### 论文

- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
- [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366)
- [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)
- [SciAgents: Multi-agent systems for scientific discovery](https://arxiv.org/abs/2409.05556)

### 框架

- [LangGraph Supervisor](https://github.com/langchain-ai/langgraph-supervisor-py)
- [LangGraph Swarm](https://github.com/langchain-ai/langgraph-swarm-py)
- [Agent Laboratory](https://github.com/SamuelSchmidgall/AgentLaboratory)

### 工具

- [Semantic Scholar API](https://api.semanticscholar.org/)
- [PubMed API](https://www.ncbi.nlm.nih.gov/books/NBK25501/)
- [arXiv API](https://info.arxiv.org/help/api/index.html)

---

## 十九、更新日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-29 | v1.2 | 补充 Prompt 复用、接口兼容、Checkpoint、鲁棒性设计 |
| 2026-06-29 | v1.1 | 补充现有系统集成方案（日志、审计、评估体系） |
| 2026-06-29 | v1.0 | 初始版本，定义完整架构和实现路径 |

---

> **下一步行动**：从 Phase 1 开始，先改造写作阶段，验证多 Agent 架构的可行性。
