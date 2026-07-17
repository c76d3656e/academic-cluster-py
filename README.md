# Academic Cluster

**学术论文聚类与综述自动生成系统** — 基于 LangGraph 的持久化多智能体流程，自动完成论文检索、覆盖度分析、知识图谱与证据卡片生成、综述撰写和同行评审。

## 功能特点

- **智能论文检索** — 集成 Semantic Scholar、PubMed、arXiv 等学术数据源，支持多关键词组合搜索
- **知识图谱抽取** — 自动从论文中提取实体关系，构建领域知识图谱
- **聚类分析** — 基于社区检测算法对论文进行主题聚类，识别研究热点
- **证据卡片生成** — 为每个研究主题生成结构化的证据摘要
- **综述撰写** — 自动生成符合学术规范的综述文章，支持自定义字数和结构
- **可恢复执行** — PostgreSQL checkpoint 按项目与执行隔离；可运行断点原地续跑，已完成断点自动协调，终态失败创建可追踪的新执行
- **契约化与可观测** — 六节点具备版本化 Artifact Schema、ContextManifest、错误/回退语义、Langfuse trace 和 Promptfoo 验收
- **多模型支持** — 支持 OpenAI API 兼容的多种 LLM 提供商与端点，支持负载均衡
- **现代 Web 界面** — Vue 3 + FastAPI 构建的响应式前端，支持实时进度跟踪


## 快速开始

### 1. 环境配置

```bash
# 克隆项目
git clone https://github.com/c76d3656e/academic-cluster-py.git
cd academic-cluster-py

# 复制配置文件
cp .env.example .env

# 编辑 .env，填入你的 API Key 和数据库密码
```

### 2. Docker 部署（推荐）

```bash
docker compose up -d
```

服务启动后：
- **前端界面**: http://localhost:3000
- **后端 API**: http://localhost:8000
- **API 文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

### 3. 本地开发

```bash
# 安装依赖
pip install -e ".[dev]"

# 启动数据库
docker compose up -d postgres redis

# 启动后端
academic-cluster --reload

# 启动前端
cd frontend
npm install
npm run dev
```

### 4. 登录

默认管理员账户（可在 `.env` 中修改）：

| 配置项 | 默认值 |
|--------|--------|
| `ADMIN_EMAIL` | `admin@cluster.local` |
| `ADMIN_PASSWORD` | 空（必须自行设置） |
| `ADMIN_FULL_NAME` | `Administrator` |

首次启动时自动创建管理员账户。修改 `.env` 后重启容器，密码会自动同步。

## 配置说明

### LLM Provider

支持单 provider 和多 provider 负载均衡两种模式：

```env
# 单 provider（fallback）
LLM_PROVIDER=provider_name
LLM_MODEL=model_name
LLM_BASE_URL=https://api.provider.com/v1
LLM_API_KEY=your_key

# 多 provider pool（优先于单 provider）
LLM_PROVIDERS_JSON=[{"name":"provider_name","model":"model_name","api_url":"https://api.provider.com/v1","api_key":"key1","rpm_limit":10}]
```

### Embedding

同理支持单/多 provider，通过 `EMBEDDING_PROVIDERS_JSON` 配置。向量持久化固定使用 PostgreSQL pgvector 的 1024 维列，因此 Provider 必须返回恰好 1024 个有限数值；后台健康测试会在启用前验证该契约。

### 学术数据源

```env
# Semantic Scholar（多 key 逗号分隔，每个 key 独立 1 rps）
SEMANTIC_SCHOLAR_API_KEY=s2k-key1,s2k-key2,s2k-key3

# PubMed
PUBMED_EMAIL=your_email@example.com
PUBMED_API_KEY=your_pubmed_key
```

### 项目执行参数

项目创建接口的 `config` 支持以下实际消费参数：

| 参数 | 默认值 | 范围/说明 |
|------|--------|-----------|
| `target_papers` | 50 | 1–500，目标论文数 |
| `target_words` | 12000 | 1000–100000，目标综述字数 |
| `quality_threshold` | 75 | 同行评审质量阈值，范围 0–100 |

### Langfuse（可选）

Langfuse 默认关闭；未配置、SDK 或遥测网络异常不会中断 Agent。生产环境一旦显式启用，就必须提供有效密钥和 HTTPS endpoint。节点正文默认不上传。

```env
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=production
LANGFUSE_RELEASE=academic-cluster-0.1.0
LANGFUSE_SAMPLE_RATE=1.0
LANGFUSE_CAPTURE_NODE_IO=false
```

同一次 `execution_id` 对应一条稳定 trace，六个图节点作为子 span。默认 span 只包含契约版本、Artifact 引用、schema digest、输出 variant 与耗时；将 `LANGFUSE_CAPTURE_NODE_IO` 设为 `true` 后，输入输出仍会先限长并脱敏。

## 架构

```text
Supervisor → Research → Embedding → Coverage
                          ├─ 覆盖不足且未到上限 → Research
                          └─ 通过 → KG → Evidence → Gap analysis
                                   → Writing → Peer review
                                      ├─ 低于阈值且未到上限 → Revision
                                      └─ 通过/达到上限 → Finalize
```

Supervisor 只做确定性路由。阶段失败最多尝试 2 次，补充检索最多 2 轮，同行评审修订最多 2 次。正式 API 使用 PostgreSQL checkpoint；线程标识同时包含 `project_id` 与 `execution_id`，不会跨项目复用状态。当前后端通过 PostgreSQL advisory lock 强制单实例运行，不支持多个 Uvicorn worker。详细设计见 [docs/architecture.md](docs/architecture.md)。

六个生产节点都通过 `NodeContract` 声明并在运行时强制校验：精确输入/输出 Artifact 版本与 JSON Schema、`ContextManifest`、服务参数绑定、错误/回退语义、fixtures 和验收准则。完整规范见 [docs/node-contracts.md](docs/node-contracts.md)，认证后的机器可读接口为 `GET /api/agent/contracts` 与 `GET /api/agent/contracts/{node_name}`。

### 技术栈

- **后端**: Python 3.12+, FastAPI, LangGraph, SQLAlchemy
- **前端**: Vue 3, TypeScript, Vite, Tailwind CSS
- **数据库**: PostgreSQL (pgvector), Redis
- **AI/ML**: OpenAI-compatible APIs, LiteLLM, NetworkX, igraph
- **可观测与评估**: Langfuse 4.x, Promptfoo 0.121.19
- **部署**: Docker, Docker Compose

## 生产部署

生产环境必须修改以下配置：

```env
APP_ENV=production
APP_DEBUG=false
JWT_SECRET_KEY=<随机长字符串>
POSTGRES_PASSWORD=<强密码>
REDIS_PASSWORD=<强密码>
ADMIN_PASSWORD=<强密码>
PROVIDER_ENCRYPTION_KEY=<固定的 Fernet key 或至少 32 字符的随机口令>
```

启动时会自动校验：如果 `APP_ENV=production` 且上述配置缺失、过短或仍是公开样例占位符，将拒绝启动。`PROVIDER_ENCRYPTION_KEY` 必须跨重启保持不变，否则数据库中保存的 Provider API Key 无法解密。可用 `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 生成。

## 开发

### 节点契约验收

```bash
# 检查机器可读 bundle 与生产图/契约是否一致
uv run python scripts/export_node_contracts.py --check

# 运行契约、fixture 和 Promptfoo 资产单测
uv run pytest tests/unit/test_node_contracts.py tests/unit/test_promptfoo_contract_assets.py

# Node.js 22；全局安装 promptfoo 后，显式使用项目 Python 3.12 虚拟环境
cd promptfoo
$env:PROMPTFOO_PYTHON=(Resolve-Path ..\.venv\Scripts\python.exe).Path
promptfoo eval --config promptfooconfig.yaml --no-cache --no-write
```

在 POSIX shell 中使用 `PROMPTFOO_PYTHON="$(cd .. && pwd)/.venv/bin/python" promptfoo eval --config promptfooconfig.yaml --no-cache --no-write`。Promptfoo provider 只调用本项目的 deterministic fixture acceptance API，不访问 LLM、论文源或 Provider 密钥。

### 项目结构

```
academic-cluster-py/
├── src/academic_cluster/
│   ├── agents/          # AI Agent 实现
│   ├── api/             # FastAPI 路由和中间件
│   ├── config/          # 配置管理
│   ├── models/          # 数据模型
│   ├── services/        # 业务逻辑服务
│   └── tools/           # Agent 工具与确定性算法
├── frontend/            # Vue 3 前端
├── tests/               # 测试用例
├── docker/              # Docker 配置
└── docs/                # 文档
```

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 致谢

感谢以下开源项目的支持：
- [LangGraph](https://github.com/langchain-ai/langgraph) - 工作流编排框架
- [FastAPI](https://github.com/tiangolo/fastapi) - 现代 Python Web 框架
- [Vue.js](https://github.com/vuejs/core) - 渐进式 JavaScript 框架
- [Semantic Scholar](https://www.semanticscholar.org/) - 学术论文搜索 API

## 友链
- [LinuxDo](https://linux.do/) - 新的理想型社区
