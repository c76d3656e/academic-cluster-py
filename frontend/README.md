# Academic Cluster Frontend

Academic Cluster 的生产前端，使用 React 19、TypeScript 和 Vite。界面面向研究人员与系统管理员，提供研究对话、六节点执行轨迹、搜索来源、成果与引用、个人控制台和权限受控的管理后台。

## 技术栈

- React Router：受保护路由、用户路由和管理员路由。
- TanStack Query + Axios：服务端状态、缓存、错误处理和单次 Token 轮换。
- Radix UI：Dialog、Dropdown、Tabs、Tooltip、Progress 等无障碍交互原语。
- Motion、Lucide、Sonner：状态动画、统一图标和通知。
- React Markdown + remark-gfm：综述成果渲染。
- remark-math + rehype-katex：支持 `$...$`、`$$...$$`、`\(...\)` 和 `\[...\]`，包括 `gathered`、`array`、`frac`、`sqrt` 和显式公式编号，公式在移动端内部滚动。
- 文献引用使用 AST 转换：`[1][2]`、`[14,15]` 和 `[12-17]` 会链接到对应条目，参考文献可回跳到首次引用。
- 成果页使用响应式目录：宽屏使用 sticky 右轨，窄屏改为正文前的 Sections 折叠控件；容器宽度通过 ResizeObserver 同步。
- 表格在正文区内横向滚动，图片使用 lazy loading，外部链接使用安全的新标签打开。
- Recharts：用户与管理员用量趋势。
- Vitest + Testing Library：组件、权限、SSE 和契约回归测试。

## 本地运行

要求 Node.js `^20.19.0` 或 `>=22.12.0`。后端默认运行在 `http://localhost:8000`。

```powershell
npm ci
npm run dev
```

Vite 地址默认为 `http://localhost:3000`。可从 `.env.example` 创建本地环境文件：

```dotenv
VITE_API_URL=/api
VITE_DEV_PROXY_TARGET=http://localhost:8000
```

`VITE_*` 会进入浏览器产物，禁止在这些变量中保存密钥。

## 校验命令

```powershell
npm run type-check
npm run lint
npm run format:check
npm test
npm run build
```

## Academic article rendering

The article renderer keeps the raw Markdown as the source of truth. Math is
rendered with KaTeX and keeps MathML for assistive technology. Citation
rewriting runs on the Markdown AST, so code blocks and math expressions such
as `$A[1,2]$` are not mistaken for bibliography references. The same protected
range rules are applied by the backend before citation validation and final
numbering.

Display equations receive stable `equation-N` anchors. Structured references
receive `reference-N` anchors, while each in-text occurrence receives a
`citation-N-M` anchor. This makes browser history, citation back-links and
deep links deterministic without exposing model-private reasoning.

The reading surface follows the responsive pattern used by established journal
readers: a sticky section companion on wide screens, an accessible collapsible
directory on narrow screens, readable measure for the article column, and
horizontal overflow only inside data tables or wide equations. Currency-like
text such as `$1,000,000 [1]` and `$5m [2]` is escaped before `remark-math`
parses the document, so adjacent citations remain visible while real `$x$`
math stays rendered by KaTeX.

## 路由与权限

| 路由            | 能力                                           | 权限           |
| --------------- | ---------------------------------------------- | -------------- |
| `/`             | 新建研究、实时状态、执行轨迹、搜索源           | 登录用户       |
| `/projects/:id` | 成果、来源、模型调用、NodeContract             | owner 或 admin |
| `/console/*`    | 项目、用量、个人资料                           | 登录用户       |
| `/admin/*`      | 用户、角色、Provider、全局项目、审计、运行配置 | admin          |

前端权限门只负责用户体验，安全边界由后端 owner/admin 校验执行。当前后端没有 tenant、organization、membership 或 tenant-scoped JWT，因此产品只呈现“个人研究空间”和“系统管理空间”，不伪造租户切换能力。

## 实时与认证

- HTTP 请求通过 Bearer access token 调用 `/api`。
- Axios 与 SSE 共享 refresh-token rotation；同标签页复用单一 Promise，跨标签页通过 Web Locks 串行化。
- SSE 使用 Fetch Stream 发送 Bearer Header，支持 CRLF、多行数据、流尾 flush、401 刷新、指数退避重连和旧连接中止。
- “执行思路”只展示持久化的节点状态、Supervisor 决策摘要和工具调用，不显示模型私有思维链。

## 目录

```text
src/
  components/   应用壳、Radix 原语、轨迹、来源与图表
  lib/          API DTO、鉴权、SSE、流程元数据
  pages/        Auth、Chat、Project、Console、Admin
  test/         Vitest 全局设置
  styles.css    设计 Token、组件状态和响应式规则
```

生产镜像由 `frontend/Dockerfile` 构建，Nginx 提供 SPA fallback、静态缓存和 `/api`/SSE 反向代理。
