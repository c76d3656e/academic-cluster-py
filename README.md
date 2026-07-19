# Academic Cluster

Academic Cluster 是一个处于开发阶段的学术文献工作流系统，基于 FastAPI、
LangGraph、PostgreSQL/pgvector、Redis 和 React/Vite 前端构建。系统围绕单个项目检索
论文、分析证据与覆盖度、生成综述、执行同行评审，并持久化最终结果。

生产流程是一个具有版本化节点契约的六节点 LangGraph 状态机，目标是提供可重复
执行、基于 PostgreSQL 的 checkpoint 恢复，以及可审计的节点级可观测性。

## 能力概览

- 按项目检索、归并与管理学术论文。
- 生成 embedding、覆盖度分析、知识图谱、证据卡片和研究缺口分析。
- 生成大纲、综述章节、引用、摘要和最终综述。
- 在终结前执行同行评审，并进行有界的修订或补充检索。
- 通过 API 提供契约元数据、决策记录、已审计工具调用和 LLM 用量记录。

## 多智能体流程

只有以下六个名称是 LangGraph 节点：<code>supervisor</code>、
<code>research</code>、<code>analysis</code>、<code>writing</code>、
<code>peer_review</code> 与 <code>finalize</code>。embedding、聚类、知识图谱、
证据和缺口分析均是 <code>analysis</code> 节点内部操作，而不是独立的图节点。

~~~mermaid
flowchart LR
    START["开始"] --> S["supervisor"]
    S --> R["research"]
    S --> A["analysis"]
    S --> W["writing"]
    S --> P["peer_review"]
    S --> F["finalize"]
    R --> S
    A --> S
    W --> S
    P --> S
    F --> END["结束"]
~~~

Supervisor 不调用 LLM 路由，而是根据 <code>AgentState</code>、重试预算、
覆盖度状态和评审状态决定下一阶段。所有非终结阶段都会返回 Supervisor。默认预算为
每阶段两次尝试、两轮补充检索和两次写作修订。

完整运行时设计见 [架构说明](docs/architecture.md)。

## 持久化与恢复

正式 API/应用启动路径使用 LangGraph 的 <code>AsyncPostgresSaver</code> 和
PostgreSQL 连接池。checkpoint 线程同时以 <code>project_id</code> 与
<code>execution_id</code> 隔离：

~~~text
academic-cluster:agent:v1:{project_id}:{execution_id}
~~~

应用启动要求 PostgreSQL checkpointer 健康可用，并持有 PostgreSQL advisory lock。
后端必须只运行一个进程和一个 Uvicorn worker。持久化 checkpointer 或其锁不可用时，
运行时会拒绝接受新的 Agent 任务。

### 并发与背压

当前部署模型是**单个 checkpoint owner 的有界并发服务**，不是多副本 worker
集群。API 在持久化 `pending` 执行后进入进程内 FIFO 调度器：

- `AGENT_MAX_CONCURRENT_RUNS` 控制实际执行中的项目数；
- `AGENT_MAX_QUEUED_RUNS` 控制等待项目数，满载时 `/agent/run` 与兼容的
  `/pipeline/{project_id}/start` 返回 HTTP `429`；
- `AGENT_MAX_ADMITTED_RUNS_PER_USER` 防止单一用户占满全局队列；
- 取消排队任务、尚未得到首次调度的 task，或关闭期间未注册的 task，都会写回
  `interrupted`，不会留下阻塞下一次运行的 `pending` 记录；
- LLM 与 embedding 分别经过显式容量、FIFO 队列与等待 deadline；这些容量不从
  Provider RPM 推导。LiteLLM 继续负责供应商级 RPM/TPM、cooldown 与 failover；
- 每个项目的 KG/证据/embedding fan-out 受每运行上限约束，NetworkX/Leiden
  聚类转入工作线程，SSE 每连接队列和每项目连接数均有限制。慢 SSE 客户端只会收到
  最新事件，过期事件被替换而不会无限占用内存。

默认值优先保护数据库和 Provider：2 个活动 Agent、32 个排队 Agent、每用户最多
2 个已准入任务、8 个 LLM in-flight、4 个 embedding in-flight。请在压测与
Provider 配额验证后，通过 `.env` 中的 `AGENT_*`、`LLM_*`、`EMBEDDING_*` 和
`SSE_*` 配置调整；不要仅因较高 RPM 就提高并发槽位。

PostgreSQL 仍是 checkpoint 与唯一活跃执行的事实来源，但目前不提供跨实例 claim、
lease 或自动重新调度。因此增加 Uvicorn worker、容器副本或滚动部署中的并行
Agent worker 都不受支持；需要水平扩展时，应先实现持久化 job queue、worker lease
和跨实例的 Provider 限额，而不是绕开 advisory lock。

<code>InMemorySaver</code> 仍用于直接图测试和隔离的确定性 E2E 测试。它不是正式
API 的 checkpoint 路径，进程退出后也无法恢复状态。

## 前置条件

- Python 3.12 或更高版本。
- 使用 [uv](https://docs.astral.sh/uv/) 创建锁定的开发环境。
- Docker Engine 与 Docker Compose，用于 PostgreSQL、Redis 和全栈部署。
- Node.js 与 npm，用于前端。Promptfoo 需要 Node
  <code>^20.20.0 || >=22.22.0</code>。
- 可用的 LLM Provider 与 embedding Provider。embedding 模型必须返回恰好
  1024 个有限数值维度。

## 配置

创建本地环境文件：

~~~powershell
Copy-Item .env.example .env
~~~

~~~bash
cp .env.example .env
~~~

启动完整工作流前，至少应替换以下占位值：

| 范围 | 必需配置 |
| --- | --- |
| LLM | <code>LLM_MODEL</code>、<code>LLM_BASE_URL</code>、<code>LLM_API_KEY</code> |
| Embedding | <code>EMBEDDING_MODEL</code>、<code>EMBEDDING_API_URL</code>、<code>EMBEDDING_API_KEY</code> |
| PostgreSQL | <code>POSTGRES_HOST</code>、<code>POSTGRES_PORT</code>、<code>POSTGRES_DB</code>、<code>POSTGRES_USER</code>、<code>POSTGRES_PASSWORD</code> |
| Redis | <code>REDIS_HOST</code>、<code>REDIS_PORT</code>、<code>REDIS_PASSWORD</code> |
| 安全配置 | <code>JWT_SECRET_KEY</code>、<code>PROVIDER_ENCRYPTION_KEY</code> |

<code>LLM_PROVIDERS_JSON</code> 与 <code>EMBEDDING_PROVIDERS_JSON</code> 可通过
LiteLLM 配置多个 OpenAI-compatible endpoint，也可接入本地的
OpenAI-compatible 模型服务。设置 <code>ADMIN_PASSWORD</code> 后才会初始化管理员；
在开发环境中留空会跳过管理员创建。

生产环境请设置 <code>APP_ENV=production</code>，使用非占位的强密钥，并在重启之间
保持 <code>PROVIDER_ENCRYPTION_KEY</code> 不变。

## Docker 启动

~~~powershell
Copy-Item .env.example .env
# 编辑 .env：至少设置 POSTGRES_PASSWORD、REDIS_PASSWORD、Provider 凭据；
# 当 APP_ENV=production 时，还需要生产级安全配置。
docker compose up -d --build
Invoke-WebRequest http://localhost:8000/health
~~~

~~~bash
cp .env.example .env
# 按上文编辑 .env。
docker compose up -d --build
curl http://localhost:8000/health
~~~

默认地址：

| 服务 | 地址 |
| --- | --- |
| 前端 | <code>http://localhost:3000</code> |
| 后端 API | <code>http://localhost:8000</code> |
| OpenAPI | <code>http://localhost:8000/docs</code> |
| 健康检查 | <code>http://localhost:8000/health</code> |

Docker Compose 会向后端容器注入 <code>POSTGRES_HOST=postgres</code> 和
<code>POSTGRES_PORT=5432</code>。本地宿主进程使用 <code>.env</code> 中的
PostgreSQL 外部端口，默认是 <code>5433</code>。

## 本地开发

安装锁定的开发环境并启动 PostgreSQL/Redis：

~~~powershell
uv sync --frozen --all-extras
docker compose up -d postgres redis
uv run academic-cluster --reload
~~~

~~~bash
uv sync --frozen --all-extras
docker compose up -d postgres redis
uv run academic-cluster --reload
~~~

在第二个终端启动前端：

~~~powershell
Set-Location frontend
npm ci
npm run dev
~~~

~~~bash
cd frontend
npm ci
npm run dev
~~~

CLI 有意固定为单 worker。不要增加 Uvicorn worker 数量，因为 Agent 运行时依赖
单一 PostgreSQL advisory-lock owner。

## 节点契约

每个生产图节点都有一个 <code>NodeContract</code>，声明：

- 精确的、带版本的输入和输出 Artifact 字段。
- 自动生成的 Draft 2020-12 JSON Schema。
- 依赖操作与参数绑定。
- 由 <code>status</code> 选择的输出 variant。
- 已声明的错误、重试规则、回退规则、fixture 和验收准则。

以下契约接口需要普通 API 认证：

~~~text
GET /api/agent/contracts
GET /api/agent/contracts/{node_name}
~~~

机器可读 bundle 位于 <code>promptfoo/contracts/node-contracts.json</code>。它只能从
生产契约生成；请使用下文检查命令检测漂移。

字段级规范见 [节点契约说明](docs/node-contracts.md)。

### 当前契约边界

当前契约会校验已声明的 Artifact 字段、版本、JSON-compatible 类型和输出 variant。
它尚未实现审批状态、N08 引用批准、G07 实验批准、显式
<code>context_hash</code> 或 append-only 历史 Artifact 存储等策略门。只有将这些
要求实现到运行时后，才能将其声明为已验收行为。

## 可观测与评估

### Langfuse

Langfuse 是可选且 fail-open 的旁路观测层。启用后，同一个
<code>execution_id</code> 会产生一个 execution trace，并包含实际执行节点的子 span。
默认记录 Artifact 引用、schema digest、输出 variant、状态和耗时等元数据，不捕获
节点 payload。

~~~env
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_CAPTURE_NODE_IO=false
~~~

只有在隐私审查允许时才设置 <code>LANGFUSE_CAPTURE_NODE_IO=true</code>。即便启用，
捕获值也会经历脱敏、截断和嵌套深度限制。Langfuse 是观测层，不是正确性门禁或
benchmark runner。

### Promptfoo

Promptfoo 当前执行离线、确定性的 **NodeContract 验收**。它校验六个
fixture/contract 组合，不调用 LLM、论文源、Provider 密钥或数据库。它不是
prompt 质量 benchmark，也不是实时端到端测试。

~~~powershell
uv run python scripts/export_node_contracts.py --check
Set-Location promptfoo
$env:PROMPTFOO_PYTHON = (Resolve-Path ..\.venv\Scripts\python.exe).Path
promptfoo eval --config promptfooconfig.yaml --no-cache --no-write
~~~

~~~bash
uv run python scripts/export_node_contracts.py --check
cd promptfoo
PROMPTFOO_PYTHON="$(cd .. && pwd)/.venv/bin/python" \
  promptfoo eval --config promptfooconfig.yaml --no-cache --no-write
~~~

### Benchmark 状态

项目尚未提供一等的“逐节点 + 全图” benchmark harness、版本化 benchmark 数据集、
评分器或报告 CLI。目前已有的是确定性契约 fixture 和使用 mock 的全图 E2E 测试。

规划中的 benchmark 分为三层：

1. <code>offline-replay</code>：脚本化 LLM/tool 响应、真实图路由和确定性 CI 断言。
2. <code>local-llm</code>：固定 fixture、mock 外部工具与本地
   OpenAI-compatible 模型。
3. <code>live</code>：显式启用的 Provider 评测，使用隔离的持久化和 trace 数据。

Promptfoo 可以在该架构中评估 prompt 回归；Langfuse 可以记录 benchmark trace；
二者都不能取代 benchmark harness。

## 测试与质量命令

运行确定性 Python 测试：

~~~powershell
uv run pytest tests/unit/ -m "not integration and not live" -v --tb=short
~~~

只有在通过 <code>ACADEMIC_CLUSTER_TEST_DATABASE_URL</code> 配置了明确可丢弃的
测试数据库后，才运行 PostgreSQL 集成测试：

~~~powershell
uv run pytest tests/integration/ -m "integration and not live" -v --tb=short
~~~

运行静态检查并构建 wheel：

~~~powershell
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/academic_cluster/
uv run bandit -r src/ -c pyproject.toml
uv run pip-audit
uv build --wheel
~~~

在 <code>frontend/</code> 目录运行前端校验：

~~~powershell
npm run lint
npm run type-check
npm run format:check
npm test
npm run build
~~~

确定性图 E2E 测试使用 <code>InMemorySaver</code> 和 fake provider。它可以验证图行为，
且不会消耗 Provider 配额或依赖外部服务；它不能证明真实模型或 PostgreSQL 部署。

## 项目结构

~~~text
src/academic_cluster/
  agents/        LangGraph 节点、契约和 checkpoint 生命周期
  api/           FastAPI 路由、SSE 与应用生命周期
  config/        配置与安全校验
  services/      Provider、持久化、观测与运行时管理
  tools/         已审计 Agent 工具和确定性分析操作
frontend/         React 19 + Vite 应用
tests/            单元测试与 PostgreSQL 集成测试
promptfoo/        离线 NodeContract fixture 与断言
docs/             架构和契约规范
~~~

## 安全说明

- 不要提交 <code>.env</code>、Provider 密钥、token 或生成的 benchmark 密钥。
- 集成测试必须使用可丢弃数据库。
- 本地 LLM benchmark 是本地计算，不是确定性 replay；比较时应保留模型、prompt、
  fixture 和输出元数据。
- 不要将当前 Promptfoo 契约验收结果视作实时 LLM 质量或完整 E2E 正确性的证据。

## 许可证

仓库当前未包含许可证文件。在对外发布项目或接受外部贡献前，请补充明确的许可证。
