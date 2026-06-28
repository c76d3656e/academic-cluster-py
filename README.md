# Academic Cluster

**学术论文聚类与综述自动生成系统** — 基于 LangGraph 构建多阶段 Pipeline，自动完成论文检索、知识图谱抽取、聚类分析、证据卡片生成和综述撰写。

## 功能特点

- **智能论文检索** — 集成 Semantic Scholar、PubMed、arXiv 等学术数据源，支持多关键词组合搜索
- **知识图谱抽取** — 自动从论文中提取实体关系，构建领域知识图谱
- **聚类分析** — 基于社区检测算法对论文进行主题聚类，识别研究热点
- **证据卡片生成** — 为每个研究主题生成结构化的证据摘要
- **综述撰写** — 自动生成符合学术规范的综述文章，支持自定义字数和结构
- **全链路可观测** — 每个节点的执行状态、LLM 调用和 token 用量均持久化到数据库
- **多模型支持** — 支持 OpenAI、Anthropic、Gitee 等多种 LLM 提供商，支持负载均衡
- **现代 Web 界面** — Vue 3 + FastAPI 构建的响应式前端，支持实时进度跟踪

试用网页 : https://review.c76d3656e.sbs/

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
uvicorn academic_cluster.api.main:app --reload

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
| `ADMIN_PASSWORD` | `Admin123!` |
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

### Embedding & Rerank

同理支持单/多 provider，通过 `EMBEDDING_PROVIDERS_JSON` 和 `RERANK_PROVIDERS_JSON` 配置。

### 学术数据源

```env
# Semantic Scholar（多 key 逗号分隔，每个 key 独立 1 rps）
SEMANTIC_SCHOLAR_API_KEY=s2k-key1,s2k-key2,s2k-key3

# PubMed
PUBMED_EMAIL=your_email@example.com
PUBMED_API_KEY=your_pubmed_key
```

### Pipeline 参数

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `KG_BATCH_SIZE` | 1 | 每次 LLM 请求处理的论文数 |
| `KG_CONCURRENCY` | 10 | KG 抽取并发数 |
| `CLUSTERING_RESOLUTION` | 1.0 | 聚类分辨率 |
| `WRITING_TOTAL_TARGET_WORDS` | 12000 | 综述目标字数 |

## 架构

```
搜索 → 去重 → 筛选 → BM25 → 嵌入 → KNN → 重排序
  → 知识图谱 → 社区检测 → 证据卡片 → 差距分析
  → [定向补充] → 大纲 → 写作 → 覆盖审计 → [修订]
  → 产出注册 → 终结
```

### 技术栈

- **后端**: Python 3.12+, FastAPI, LangGraph, SQLAlchemy
- **前端**: Vue 3, TypeScript, Vite, Tailwind CSS
- **数据库**: PostgreSQL (pgvector), Redis
- **AI/ML**: OpenAI, Anthropic, LiteLLM, NetworkX
- **部署**: Docker, Docker Compose

## 生产部署

生产环境必须修改以下配置：

```env
APP_ENV=production
APP_DEBUG=false
APP_SECRET_KEY=<随机长字符串>
JWT_SECRET_KEY=<随机长字符串>
POSTGRES_PASSWORD=<强密码>
ADMIN_PASSWORD=<强密码>
```

启动时会自动校验：如果 `APP_ENV=production` 且上述配置仍为默认值，将拒绝启动。

## 开发

### 项目结构

```
academic-cluster-py/
├── src/academic_cluster/
│   ├── agents/          # AI Agent 实现
│   ├── api/             # FastAPI 路由和中间件
│   ├── config/          # 配置管理
│   ├── graphs/          # LangGraph 工作流
│   ├── models/          # 数据模型
│   ├── prompts/         # LLM Prompt 模板
│   ├── services/        # 业务逻辑服务
│   ├── tools/           # 工具函数
│   └── utils/           # 通用工具
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
