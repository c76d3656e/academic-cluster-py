# Academic Cluster

**学术论文聚类与综述自动生成系统** — 基于 LangGraph 的持久化多智能体流程，自动完成论文检索、覆盖度分析、知识图谱与证据卡片生成、综述撰写和同行评审。

## 功能特点

- **智能论文检索** — 集成 Semantic Scholar、PubMed、arXiv 等学术数据源，支持多关键词组合搜索
- **知识图谱抽取** — 自动从论文中提取实体关系，构建领域知识图谱
- **聚类分析** — 基于社区检测算法对论文进行主题聚类，识别研究热点
- **证据卡片生成** — 为每个研究主题生成结构化的证据摘要
- **综述撰写** — 自动生成符合学术规范的综述文章，支持自定义字数和结构
- **可恢复执行** — PostgreSQL checkpoint 按项目与执行隔离；可运行断点原地续跑，已完成断点自动协调，终态失败创建可追踪的新执行
- **流程可观测** — Supervisor 决策、Agent 工具调用和阶段进度均按项目记录
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

### 技术栈

- **后端**: Python 3.12+, FastAPI, LangGraph, SQLAlchemy
- **前端**: Vue 3, TypeScript, Vite, Tailwind CSS
- **数据库**: PostgreSQL (pgvector), Redis
- **AI/ML**: OpenAI-compatible APIs, LiteLLM, NetworkX, igraph
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
