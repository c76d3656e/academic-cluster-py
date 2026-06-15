# 控制台与管理后台完整规划

## 一、设计理念

参考 sub2api 和 new-api 的双层导航架构：

- **用户控制台**（所有登录用户）：个人仪表盘、我的项目、我的用量、个人设置、充值（预留关闭）
- **管理后台**（admin 角色）：系统概览、用户管理、项目管理、Provider 管理、用量分析、审计日志

侧边栏统一为一个组件，admin 用户看到两个分区（"我的控制台" + "系统管理"），普通用户只看到一个分区。

### 业界参考

| 项目 | 用户控制台功能 | 管理后台功能 | 侧边栏结构 |
|------|---------------|-------------|-----------|
| **sub2api** | 仪表盘、API Key、用量、兑换码、订阅、订单、个人设置 | 用户管理、渠道管理、公告、系统设置 | admin: 管理菜单 + "我的账户"分区；user: 扁平列表 |
| **new-api** | 数据看板、令牌管理、用量日志、钱包充值、个人设置 | 渠道管理、用户管理、模型管理、兑换码、系统设置 | 分区渲染：聊天区 + 控制台区 + 个人中心区 + (admin)管理区 |
| **Rust 版** | Run 历史、计费、个人设置 | 监控、用户、Provider、Run、队列、审计、存储 | 按角色动态生成菜单 |

---

## 二、技术选型

| 项 | 选择 | 依据 |
|------|------|------|
| UI 组件库 | shadcn/vue + Tailwind（保持不变） | new-api、Langflow 均采用 shadcn 体系 |
| 图表库 | **ECharts** (via `vue-echarts`) | Dify、FastGPT 均用 ECharts；中文社区最强；按需引入 |
| 数据表格 | shadcn/vue Table | Dify 用原生 table；我们已有 shadcn Table，够用 |
| 状态管理 | **Pinia** | sub2api 用 Pinia；Vue 3 官方推荐 |
| API Key 加密 | **Fernet** (`cryptography`) | AES-128-CBC + HMAC-SHA256；API 简单；密钥通过 env 管理 |
| 实时更新 | **SSE**（已有实现） | Dashboard 只读推送；项目已有 SSE 基础设施 |
| 数据获取 | **@tanstack/vue-query** | Dify 用 SWR/TanStack Query；自动缓存、后台刷新 |
| 路由 | Vue Router 嵌套路由 | `/console/*` + `/admin/*` 两组子路由 |
| Admin 路由 | `APIRouter(prefix="/admin")` | 按资源分组、RESTful、`Depends(require_admin)` |
| 聚合查询 | `func.date_trunc()` + `generate_series` | PostgreSQL 最佳实践 |

---

## 三、前端路由架构

### 用户控制台（所有登录用户）

```
/console                        ← 重定向到 /console/overview
├── /console/overview           ← 个人仪表盘（我的统计 + 用量趋势 + 快捷入口）
├── /console/projects           ← 我的项目（已有功能，迁移到侧边栏布局）
├── /console/usage              ← 我的用量（Token 消耗、成本明细、调用记录）
├── /console/profile            ← 个人设置（修改密码、修改昵称）
└── /console/recharge           ← 充值（预留入口，显示"暂未开放"）
```

### 管理后台（admin 角色）

```
/admin                          ← 重定向到 /admin/overview
├── /admin/overview             ← 系统仪表盘（全局统计 + Provider 状态 + 活动时间线）
├── /admin/users                ← 用户管理（CRUD + 配额 + 使用详情）
├── /admin/projects             ← 项目管理（全量列表 + 删除）
├── /admin/providers            ← Provider 管理（CRUD + 多 Key + 健康测试 + 热重载）
├── /admin/usage                ← 用量分析（全局 Token/成本趋势 + provider 维度统计）
└── /admin/audit                ← 审计日志（操作记录 + 筛选 + 详情展开）
```

### 侧边栏结构

```
┌─────────────────────────┐
│  Academic Cluster       │  ← Logo / 系统名
├─────────────────────────┤
│  📊 仪表盘              │  ← /console/overview
│  📁 我的项目            │  ← /console/projects
│  📈 我的用量            │  ← /console/usage
│  👤 个人设置            │  ← /console/profile
│  💰 充值                │  ← /console/recharge (disabled)
├─────────────────────────┤  ← 仅 admin 可见
│  🖥️ 系统概览            │  ← /admin/overview
│  👥 用户管理            │  ← /admin/users
│  📂 项目管理            │  ← /admin/projects
│  🔌 Provider 管理       │  ← /admin/providers
│  📊 用量分析            │  ← /admin/usage
│  📋 审计日志            │  ← /admin/audit
├─────────────────────────┤
│  🚪 登出                │
└─────────────────────────┘
```

---

## 四、前端目录结构

```
frontend/src/
├── layouts/
│   └── AppLayout.vue             ← 统一布局：侧边栏 + 顶栏 + router-view
├── components/
│   ├── sidebar/
│   │   ├── AppSidebar.vue        ← 侧边导航（分区渲染，admin 判断）
│   │   ├── SidebarItem.vue       ← 单个导航项
│   │   └── SidebarSection.vue    ← 导航分区（标题 + items）
│   └── charts/
│       ├── UsageTrendChart.vue   ← ECharts 折线图（Token 趋势）
│       ├── CostPieChart.vue      ← ECharts 饼图（成本分布）
│       └── CostBarChart.vue      ← ECharts 柱状图（provider 维度）
├── views/
│   ├── console/                  ← 用户控制台
│   │   ├── ConsoleOverview.vue   ← 个人仪表盘
│   │   ├── ConsoleProjects.vue   ← 我的项目（从 DashboardView 迁移）
│   │   ├── ConsoleUsage.vue      ← 我的用量
│   │   ├── ConsoleProfile.vue    ← 个人设置
│   │   └── ConsoleRecharge.vue   ← 充值（预留）
│   ├── admin/                    ← 管理后台
│   │   ├── AdminOverview.vue     ← 系统仪表盘
│   │   ├── AdminUsers.vue        ← 用户管理
│   │   ├── AdminProjects.vue     ← 项目管理
│   │   ├── AdminProviders.vue    ← Provider 管理
│   │   ├── AdminUsage.vue        ← 用量分析
│   │   └── AdminAudit.vue        ← 审计日志
│   ├── LoginView.vue             ← （已有）
│   ├── RegisterView.vue          ← （已有）
│   ├── NewProjectView.vue        ← （已有）
│   └── ProjectDetailView.vue     ← （已有）
├── components/
│   └── admin/
│       ├── ProviderForm.vue      ← 新增/编辑 Provider 弹窗
│       ├── UserForm.vue          ← 新增用户弹窗
│       └── ProviderStatusCard.vue← Provider 状态卡片
├── api/
│   ├── admin.ts                  ← 新增：admin API 封装
│   ├── console.ts                ← 新增：用户控制台 API 封装
│   ├── projects.ts               ← （已有）
│   └── auth.ts                   ← （已有）
├── stores/
│   └── app.ts                    ← Pinia store（侧边栏状态、用户信息缓存）
└── router/
    └── index.ts                  ← 路由配置（/console/* + /admin/*）
```

---

## 五、后端目录结构

```
src/academic_cluster/
├── api/
│   ├── main.py
│   ├── auth_routes.py               ← （已有，保留）
│   ├── routes.py                    ← （已有，保留）
│   ├── console/                     ← 新增：用户控制台端点
│   │   ├── __init__.py
│   │   ├── dashboard.py             ← /console/overview（个人统计）
│   │   ├── usage.py                 ← /console/usage（个人用量）
│   │   └── profile.py               ← /console/profile（个人设置）
│   └── admin/                       ← 新增：管理端点模块
│       ├── __init__.py
│       ├── dashboard.py             ← /admin/overview
│       ├── users.py                 ← /admin/users
│       ├── projects.py              ← /admin/projects
│       ├── providers.py             ← /admin/providers
│       ├── usage.py                 ← /admin/usage
│       └── audit.py                 ← /admin/audit
├── services/
│   ├── crypto.py                    ← 新增：Fernet 加密/解密
│   └── provider_pool.py             ← 修改：支持 DB 热重载
└── models/
    ├── admin.py                     ← 新增：admin Pydantic 模型
    └── console.py                   ← 新增：用户控制台 Pydantic 模型
```

---

## 六、用户控制台详细设计

### Module C1: 个人仪表盘 (`/console/overview`)

**参考**：new-api 数据看板 + sub2api Dashboard

**UI 布局**：

```
┌────────────────────────────────────────────────────────┐
│  欢迎回来，user@example.com                            │
├──────────┬──────────┬──────────┬────────────────────────┤
│ 我的项目 │ 运行中   │ 总论文数 │ 累计 Token 消耗        │
│    5     │    1     │   800    │    250,000             │
├──────────┴──────────┴──────────┴────────────────────────┤
│                                                         │
│  ECharts 折线图：我近 7 天的 Token 消耗趋势              │
│  （x轴=日期, y轴=token数, tooltip含cost）                │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  最近项目                                                │
│  ┌─────────────────────┬──────────┬──────────────────┐  │
│  │ LLM Survey          │ completed│ 2026-06-10       │  │
│  │ Transformer Analysis│ running  │ 2026-06-12       │  │
│  └─────────────────────┴──────────┴──────────────────┘  │
├─────────────────────────────────────────────────────────┤
│  快捷操作                                                │
│  [新建项目]  [查看用量]  [充值(暂未开放)]                 │
└─────────────────────────────────────────────────────────┘
```

**后端端点**：

```
GET /api/console/overview
```

响应：

```json
{
  "stats": {
    "project_count": 5,
    "running_projects": 1,
    "total_papers": 800,
    "total_tokens": 250000,
    "total_cost": 3.20
  },
  "daily_usage": [
    {"date": "2026-06-10", "tokens": 50000, "cost": 0.8},
    {"date": "2026-06-11", "tokens": 30000, "cost": 0.5}
  ],
  "recent_projects": [
    {"id": "uuid", "name": "LLM Survey", "status": "completed", "created_at": "..."}
  ]
}
```

---

### Module C2: 我的项目 (`/console/projects`)

**从现有 DashboardView.vue 迁移**，功能不变，套入 AppLayout 侧边栏布局。

- 项目卡片网格
- 新建项目按钮
- 点击进入项目详情

---

### Module C3: 我的用量 (`/console/usage`)

**参考**：new-api 使用日志 + sub2api UsageView

**UI 布局**：

```
┌─ 时间范围: [7天] [30天] ──────────────────────────────┐
│                                                        │
│  ┌──────────────────────────────────────────────┐      │
│  │ ECharts 折线图：我的 Token 消耗趋势           │      │
│  │ x轴=日期, y轴=token数                         │      │
│  └──────────────────────────────────────────────┘      │
│                                                        │
│  我的调用记录                                          │
│  ┌──────┬──────────┬───────────┬────────┬──────┬─────┐ │
│  │ 时间 │ 项目     │ Provider  │ Tokens │ Cost │ 延迟│ │
│  ├──────┼──────────┼───────────┼────────┼──────┼─────┤ │
│  │ 6/12 │ LLM Surv │ Silicon   │ 1,200  │ 0.02 │ 850 │ │
│  │ 6/12 │ LLM Surv │ OpenAI    │   800  │ 0.05 │ 1200│ │
│  └──────┴──────────┴───────────┴────────┴──────┴─────┘ │
└────────────────────────────────────────────────────────┘
```

**后端端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/console/usage/trend?days=7` | 我的按天 token/cost 趋势 |
| `GET` | `/api/console/usage/calls?limit=50&project_id=` | 我的 LLM 调用记录（按项目过滤） |

**趋势查询 SQL**（限定当前用户）：

```sql
SELECT d::date AS date,
       COALESCE(SUM(lc.total_tokens), 0) AS tokens,
       COALESCE(SUM(lc.cost), 0) AS cost,
       COUNT(lc.id) AS calls
FROM generate_series(
    CURRENT_DATE - INTERVAL '7 days', CURRENT_DATE, '1 day'
) d
LEFT JOIN llm_calls lc ON DATE(lc.created_at) = d::date
  AND lc.pipeline_run_id IN (
    SELECT pr.id FROM pipeline_runs pr
    JOIN projects p ON pr.project_id = p.id
    WHERE p.user_id = :user_id
  )
GROUP BY d::date
ORDER BY d::date;
```

---

### Module C4: 个人设置 (`/console/profile`)

**参考**：new-api PersonalSetting + sub2api ProfileView

**UI 功能**：

```
┌─────────────────────────────────────────┐
│  账户信息                                │
│  邮箱: user@example.com (不可修改)       │
│  昵称: [张三] [保存]                     │
│  角色: user                              │
│  注册时间: 2026-06-01                    │
├─────────────────────────────────────────┤
│  修改密码                                │
│  当前密码: [********]                    │
│  新密码:   [********]                    │
│  确认密码: [********]                    │
│  [保存]                                  │
├─────────────────────────────────────────┤
│  充值                                    │
│  当前余额: --                            │
│  兑换码: [____________] [兑换]           │
│  ⚠️ 在线充值暂未开放                     │
└─────────────────────────────────────────┘
```

**后端端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/console/profile` | 获取个人信息 |
| `PATCH` | `/api/console/profile` | 更新昵称 |
| `POST` | `/api/console/profile/password` | 修改密码 |

---

### Module C5: 充值 (`/console/recharge`) — 预留关闭

**参考**：sub2api 兑换码 + 支付网关；new-api 钱包管理

**当前状态**：显示"暂未开放"占位页面，预留接口。

**未来扩展**（接口预留，UI 灰色不可点击）：

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/console/recharge/redeem` | 兑换码充值（预留） |
| `GET` | `/api/console/recharge/orders` | 充值记录（预留） |

---

## 七、管理后台详细设计

### Module A1: 系统仪表盘 (`/admin/overview`)

**参考**：new-api 数据控制台 + Dify 仪表盘

**UI 布局**：

```
┌──────────┬──────────┬──────────┬──────────┐
│ 总用户   │ 总项目   │ 总论文   │ 总运行   │
├──────────┼──────────┼──────────┼──────────┤
│ 活跃用户 │ 运行中   │ LLM调用  │ 总花费   │
└──────────┴──────────┴──────────┴──────────┘

┌────────────────────────────────────────────┐
│ ECharts 折线图：近 7 天全系统 Token 消耗趋势│
│ （按 provider 分系列，tooltip 显示 cost）   │
├────────────────────────────────────────────┤
│ ECharts 饼图：成本按 provider 分布          │
├────────────────────────────────────────────┤
│ Provider 状态卡片列表                       │
│ [SiliconFlow] 🟢 healthy · enabled · LLM   │
│ [OpenAI]      🟡 unknown · disabled · LLM  │
├────────────────────────────────────────────┤
│ 最近活动时间线（user_activities 最新 10 条）│
└────────────────────────────────────────────┘
```

**后端端点**：

```
GET /api/admin/overview
```

响应：

```json
{
  "stats": {
    "total_users": 10, "active_users": 8,
    "total_projects": 25, "running_projects": 2,
    "total_papers": 1500, "total_runs": 50,
    "total_llm_calls": 3200, "total_cost": 12.50
  },
  "providers": [
    {"id": "uuid", "kind": "llm", "display_name": "SiliconFlow",
     "model": "deepseek-v3", "health_status": "healthy", "is_enabled": true}
  ],
  "recent_activities": [
    {"time": "...", "user_email": "...", "action": "admin.provider_created", "details": {}}
  ],
  "daily_usage": [
    {"date": "2026-06-10", "tokens": 120000, "cost": 2.5}
  ]
}
```

---

### Module A2: 用户管理 (`/admin/users`)

**参考**：new-api 用户管理 + 配额分配

**UI 功能**：

- 用户表格：邮箱、姓名、角色、状态、注册时间、项目数、累计花费
- 操作：创建用户（弹窗）、修改角色、启用/禁用、删除（二次确认）
- 搜索：email 关键词过滤
- 分页

**后端端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/admin/users?skip=&limit=&search=` | 列表 |
| `POST` | `/api/admin/users` | 创建用户 |
| `DELETE` | `/api/admin/users/{id}` | 删除用户（级联） |
| `PATCH` | `/api/admin/users/{id}/role` | 修改角色 |
| `PATCH` | `/api/admin/users/{id}/active` | 启用/禁用 |
| `GET` | `/api/admin/users/{id}/usage` | 使用详情 |

---

### Module A3: 项目管理 (`/admin/projects`)

**后端端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/admin/projects?skip=&limit=&status=&user_id=` | 全量列表 |
| `DELETE` | `/api/admin/projects/{id}` | 删除项目 |

---

### Module A4: Provider 管理 (`/admin/providers`) — 核心

**参考**：new-api 渠道管理 + Rust 版 provider_registry

#### DB 表 `provider_registry`

```sql
CREATE TABLE provider_registry (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kind            VARCHAR(20) NOT NULL,           -- llm / embedding / rerank
    display_name    VARCHAR(100) NOT NULL,
    base_url        TEXT NOT NULL,
    model           VARCHAR(200),
    api_key_enc     TEXT,                            -- Fernet 加密
    is_enabled      BOOLEAN DEFAULT true,
    priority        INTEGER DEFAULT 100,
    rpm_limit       INTEGER DEFAULT 10,
    weight          INTEGER DEFAULT 1,
    extra_keys      JSONB DEFAULT '[]',              -- 多 Key
    key_strategy    VARCHAR(20) DEFAULT 'round_robin',
    health_status   VARCHAR(20) DEFAULT 'unknown',
    last_health_check TIMESTAMPTZ,
    last_error      TEXT,
    failure_count   INTEGER DEFAULT 0,
    auto_ban        BOOLEAN DEFAULT true,
    cooldown_until  TIMESTAMPTZ,
    test_model      VARCHAR(200),
    metadata        JSONB DEFAULT '{}',
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

#### API Key 加密

```python
# services/crypto.py
from cryptography.fernet import Fernet

def encrypt_key(plain: str) -> str: ...
def decrypt_key(encrypted: str) -> str: ...
def mask_key(plain: str) -> str:  # sk-abc...xyz
```

#### UI

```
┌─ LLM ─┬─ Embedding ─┬─ Rerank ─┐  ← Tab 切换
│                                      │ [+ 新增]  [热重载]
├──────────────────────────────────────┤
│ 名称   │ 模型     │ URL  │ 状态 │ 健康 │ 优先级 │ 操作      │
│ Silicon│ deepseek │ http │ ✅   │ 🟢  │  100   │ 编辑 测试 │
│ OpenAI │ gpt-4o   │ http │ ❌   │ 🟡  │  200   │ 编辑 测试 │
└──────────────────────────────────────┘
```

#### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/admin/providers?kind=` | 列表 |
| `POST` | `/api/admin/providers` | 创建 |
| `PATCH` | `/api/admin/providers/{id}` | 更新 |
| `DELETE` | `/api/admin/providers/{id}` | 删除 |
| `POST` | `/api/admin/providers/{id}/test` | 健康测试 |
| `POST` | `/api/admin/providers/reload` | 热重载 |
| `PATCH` | `/api/admin/providers/{id}/toggle` | 启用/禁用 |

#### 热重载

```python
async def reload_providers():
    """从 DB 读取 → 按 kind 分组 → 重建 LiteLLMPool/RerankPool → 替换全局单例"""
    # DB 有记录用 DB，否则 fallback env-var
```

#### 健康测试

```python
async def test_provider(provider_id: str):
    """解密 key → 发最小请求(max_tokens=1) → 记录 latency/http_status → 更新 health_status"""
```

#### 自动熔断（参考 new-api AutoBan）

- `failure_count >= 3` → 标记 unhealthy + 设置 `cooldown_until`
- 健康测试成功 → 重置 `failure_count = 0`
- `auto_ban` 字段控制开关

---

### Module A5: 用量分析 (`/admin/usage`)

**与用户用量的区别**：管理员看到全系统数据，可按 user/project/provider 维度筛选。

**UI 布局**：

```
┌─ 时间范围: [7天] [30天] ──────────────────────────────┐
│                                                        │
│  ECharts 折线图：全系统 Token 消耗趋势（按 provider）  │
│  ECharts 柱状图：成本分布（按 provider × model）        │
│                                                        │
│  Provider × Model 汇总表                               │
│  ┌──────────┬───────────┬──────────┬─────────┬───────┐ │
│  │ Provider │ Model     │ Tokens   │ Cost($) │ Calls │ │
│  └──────────┴───────────┴──────────┴─────────┴───────┘ │
│                                                        │
│  近期 LLM 调用列表（可按 provider/model 筛选）          │
└────────────────────────────────────────────────────────┘
```

**端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/admin/usage/trend?days=7` | 全系统趋势 |
| `GET` | `/api/admin/usage/by-provider?days=30` | provider×model 维度 |
| `GET` | `/api/admin/usage/recent-calls?limit=50&provider=&model=` | 近期调用 |

---

### Module A6: 审计日志 (`/admin/audit`)

**操作记录**：

| action | 触发时机 |
|--------|----------|
| `admin.user_created/deleted/role_changed/toggled` | 用户管理操作 |
| `admin.project_deleted` | 删除项目 |
| `admin.provider_created/updated/deleted/tested/reloaded/toggled` | Provider 操作 |
| `auth.login/register/logout` | 认证操作 |

**端点**：`GET /api/admin/audit/logs?action=&user_id=&days=&skip=&limit=`

---

## 八、实施阶段

### Phase 0: 基础设施

- [ ] 新建 `provider_registry` 表（init.sql + migration）
- [ ] 新建 `services/crypto.py`
- [ ] 新建 `models/admin.py` + `models/console.py`
- [ ] 新建 `api/admin/` + `api/console/` 路由骨架
- [ ] 安装前端依赖：`echarts` + `vue-echarts` + `@tanstack/vue-query` + `pinia`
- [ ] `.env.example` 添加 `PROVIDER_ENCRYPTION_KEY`

### Phase 1: 统一布局 + 侧边导航

- [ ] `AppLayout.vue`：侧边栏 + 顶栏 + router-view（替代当前无布局结构）
- [ ] `AppSidebar.vue`：双分区导航（"我的控制台" + "系统管理"）
- [ ] 路由重构：`/console/*` + `/admin/*` 嵌套路由
- [ ] 现有 DashboardView 迁移到 `ConsoleProjects.vue`
- [ ] 现有 AdminView 迁移到 `AdminUsers.vue`

### Phase 2: 用户控制台

- [ ] 后端：`GET /api/console/overview`（个人统计）
- [ ] 后端：`GET /api/console/usage/trend`（个人趋势）
- [ ] 后端：`GET /api/console/usage/calls`（个人调用记录）
- [ ] 后端：`GET/PATCH /api/console/profile` + `POST .../password`
- [ ] 前端：`ConsoleOverview.vue`（个人仪表盘 + ECharts 图表）
- [ ] 前端：`ConsoleUsage.vue`（用量页面）
- [ ] 前端：`ConsoleProfile.vue`（个人设置）
- [ ] 前端：`ConsoleRecharge.vue`（充值占位页）

### Phase 3: Provider 管理（最高优先级）

- [ ] 后端：Provider CRUD 端点
- [ ] 后端：Fernet 加密/解密
- [ ] 后端：健康测试 + 热重载 + 启用/禁用
- [ ] 前端：`AdminProviders.vue` + `ProviderForm.vue`
- [ ] `provider_pool.py` 修改：DB 优先，fallback env-var

### Phase 4: 管理仪表盘

- [ ] 后端：`GET /api/admin/overview`
- [ ] 前端：`AdminOverview.vue`（ECharts 图表 + Provider 状态 + 活动时间线）

### Phase 5: 管理用户/项目增强

- [ ] 后端：创建/删除用户 + 使用详情
- [ ] 后端：全量项目列表 + 删除
- [ ] 前端：`AdminUsers.vue` 增强（创建弹窗、搜索、删除确认）
- [ ] 前端：`AdminProjects.vue`（新页面）

### Phase 6: 管理用量分析

- [ ] 后端：全系统趋势 + provider 维度统计 + 近期调用
- [ ] 前端：`AdminUsage.vue`（ECharts 全系统图表）

### Phase 7: 审计日志

- [ ] 统一 admin 操作日志记录
- [ ] 后端：审计日志查询端点
- [ ] 前端：`AdminAudit.vue`

---

## 九、依赖关系

```
Phase 0 (基础设施)
    ↓
Phase 1 (统一布局 + 侧边导航)  ← 最先做，所有页面依赖此布局
    ↓
    ├── Phase 2 (用户控制台)    ← 所有用户可用
    ├── Phase 3 (Provider)      ← 最高优先级 admin 功能
    ├── Phase 4 (管理仪表盘)
    ├── Phase 5 (用户/项目管理)
    ├── Phase 6 (用量分析)
    └── Phase 7 (审计日志)
```

Phase 1 完成后，Phase 2-7 可按优先级灵活排序。

---

## 十、环境变量新增

```env
# Provider 加密密钥（Fernet generate_key() 生成）
PROVIDER_ENCRYPTION_KEY=your-fernet-key-here
```

---

## 十一、DB Migration

```sql
-- provider_registry 表
CREATE TABLE IF NOT EXISTS provider_registry (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kind            VARCHAR(20) NOT NULL,
    display_name    VARCHAR(100) NOT NULL,
    base_url        TEXT NOT NULL,
    model           VARCHAR(200),
    api_key_enc     TEXT,
    is_enabled      BOOLEAN DEFAULT true,
    priority        INTEGER DEFAULT 100,
    rpm_limit       INTEGER DEFAULT 10,
    weight          INTEGER DEFAULT 1,
    extra_keys      JSONB DEFAULT '[]',
    key_strategy    VARCHAR(20) DEFAULT 'round_robin',
    health_status   VARCHAR(20) DEFAULT 'unknown',
    last_health_check TIMESTAMPTZ,
    last_error      TEXT,
    failure_count   INTEGER DEFAULT 0,
    auto_ban        BOOLEAN DEFAULT true,
    cooldown_until  TIMESTAMPTZ,
    test_model      VARCHAR(200),
    metadata        JSONB DEFAULT '{}',
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_provider_registry_kind ON provider_registry(kind);
CREATE INDEX IF NOT EXISTS idx_provider_registry_enabled ON provider_registry(is_enabled);
CREATE INDEX IF NOT EXISTS idx_provider_registry_health ON provider_registry(health_status);

CREATE TRIGGER update_provider_registry_updated_at
    BEFORE UPDATE ON provider_registry
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```
