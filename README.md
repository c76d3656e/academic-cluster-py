# Academic Cluster

学术论文聚类与综述自动生成系统。基于 LangGraph 构建多阶段 Pipeline，自动完成论文检索、知识图谱抽取、聚类分析、证据卡片生成和综述撰写。

## 快速开始

### 1. 环境配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key 和数据库密码
```

### 2. Docker 部署

```bash
docker compose up -d
```

服务启动后：
- 后端 API: http://localhost:8000
- 前端界面: http://localhost:3000
- 健康检查: http://localhost:8000/health

### 3. 登录

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
LLM_PROVIDER=gitee
LLM_MODEL=internlm3-8b-instruct
LLM_BASE_URL=https://ai.gitee.com/v1
LLM_API_KEY=your_key

# 多 provider pool（优先于单 provider）
LLM_PROVIDERS_JSON=[{"name":"gitee","model":"internlm3-8b-instruct","api_url":"https://ai.gitee.com/v1","api_key":"key1","rpm_limit":10}]
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

## 架构

```
搜索 → 去重 → 筛选 → BM25 → 嵌入 → KNN → 重排序
  → 知识图谱 → 社区检测 → 证据卡片 → 差距分析
  → [定向补充] → 大纲 → 写作 → 覆盖审计 → [修订]
  → 产出注册 → 终结
```

每个节点的执行状态、LLM 调用和 token 用量均持久化到数据库，支持全链路可观测。
