# 管理后台实现说明

本文记录当前 React 管理后台的已实现结构与权限边界。它不是未来功能清单，界面能力必须与 FastAPI 契约和数据库授权保持一致。

## 技术结构

| 能力 | 实现 |
| --- | --- |
| 框架 | React 19、TypeScript、Vite |
| 路由 | React Router，`/console/*` 与 `/admin/*` 分区 |
| 服务端状态 | TanStack Query |
| HTTP 与认证 | Axios、Bearer access token、refresh rotation |
| 组件原语 | Radix UI |
| 图表 | Recharts |
| 动效与反馈 | Motion、Sonner、Lucide |
| 测试 | Vitest、Testing Library |

## 页面

用户控制台：

- `/console/overview`：个人项目、论文、Token 与成本摘要。
- `/console/projects`：当前用户拥有的项目。
- `/console/usage`：功能开关允许时显示个人模型调用与趋势。
- `/console/profile`：显示名称和密码维护。

管理员后台：

- `/admin/overview`：全局用户、项目、运行、Token、成本与 Provider 健康状态。
- `/admin/users`：创建用户、角色调整和启停。
- `/admin/providers`：Provider 创建、启停、健康检查与运行时重载。
- `/admin/projects`：跨用户项目清单。
- `/admin/usage`：全局 Token 趋势和 Provider 用量。
- `/admin/audit`：权限、用户、项目和 Provider 审计事件。
- `/admin/pipeline-config`：后端允许修改的运行配置。

## 授权边界

- 前端 `AdminRoute` 只控制导航体验，后端仍对每个 `/api/admin/*` 请求执行 admin 校验。
- 普通用户只能读取自己的项目、运行日志、模型调用和综述产物。
- 管理员可以读取全局资源，但不能通过新旧任一管理入口自降权或自停用。
- SSE 在建立连接前验证 Bearer token、账户状态和项目 owner/admin 权限。
- Provider 密钥只在创建请求中发送，列表仅显示后端掩码。

当前系统不是安全多租户产品。数据库没有 tenant、organization、membership 或 tenant-scoped JWT，资源隔离以 `user_id` owner 为单位，admin 拥有全局视图。前端因此只显示个人研究空间和系统管理空间，不提供虚假的组织切换器。

## 状态与错误

- Query 缓存按资源和项目 ID 分键。
- 修改后只失效对应 Query，不整页刷新。
- 401 由共享 refresh 流程恢复；轮换失败立即清理会话。
- 管理操作通过 Sonner 返回成功或后端错误详情。
- 空列表、加载中、无权限和 API 不可用都有独立界面状态。

## 验收

在 `frontend/` 执行：

```powershell
npm run type-check
npm run lint
npm run format:check
npm test
npm run build
```

测试至少覆盖管理员导航、创建用户、Chat 启动竞态、NodeContract manifest、鉴权失效和 SSE 终止/刷新/连接隔离。
