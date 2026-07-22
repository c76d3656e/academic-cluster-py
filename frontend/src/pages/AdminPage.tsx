import {
  Activity,
  AlertTriangle,
  BookOpen,
  Database,
  Gauge,
  ListChecks,
  ListFilter,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Server,
  Trash2,
  ToggleLeft,
  Users,
} from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import {
  adminApi,
  apiErrorMessage,
  type LlmCall,
  type ProviderInfo,
  type SourceConfigInfo,
  type User,
} from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatCost, formatDate, formatDuration, formatNumber, statusTone } from '../lib/pipeline'
import {
  Badge,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  EmptyState,
  Input,
  Label,
  MetricCard,
  SectionHeader,
  Skeleton,
} from '../components/ui'
import { UsageTrendChart } from '../components/UsageTrendChart'

export function AdminPage() {
  const { section = 'overview' } = useParams()
  if (section === 'users') return <AdminUsers />
  if (section === 'providers') return <AdminProviders />
  if (section === 'sources') return <AdminSources />
  if (section === 'projects') return <AdminProjects />
  if (section === 'usage') return <AdminUsage />
  if (section === 'audit') return <AdminAudit />
  if (section === 'pipeline-config') return <AdminConfig />
  return <AdminOverview />
}

function AdminOverview() {
  const query = useQuery({ queryKey: ['admin-overview'], queryFn: adminApi.overview })
  const data = query.data
  if (query.isLoading)
    return (
      <div className="page-loading">
        <Skeleton className="skeleton-title" />
        <Skeleton className="skeleton-panel" />
      </div>
    )
  if (!data)
    return (
      <EmptyState
        icon={<AlertTriangle size={24} />}
        title="管理概览暂时不可用"
        detail="请确认当前账户拥有管理员权限。"
      />
    )
  return (
    <div className="admin-page">
      <SectionHeader
        eyebrow="SYSTEM CONTROL ROOM"
        title="管理概览"
        detail="全局用户、项目、Provider 和调用健康度。"
        action={
          <Link to="/admin/providers">
            <Button variant="soft">
              <Server size={15} />
              管理 Provider
            </Button>
          </Link>
        }
      />
      <div className="admin-metrics">
        <MetricCard
          label="用户"
          value={formatNumber(data.total_users)}
          detail={`${data.active_users} 个活跃`}
          icon={<Users size={17} />}
          tone="sage"
        />
        <MetricCard
          label="项目"
          value={formatNumber(data.total_projects)}
          detail={`${data.running_projects} 个运行中`}
          icon={<Database size={17} />}
        />
        <MetricCard
          label="模型调用"
          value={formatNumber(data.total_llm_calls)}
          detail={`${formatNumber(data.total_tokens)} tokens`}
          icon={<Activity size={17} />}
          tone="amber"
        />
        <MetricCard
          label="累计成本"
          value={formatCost(data.total_cost)}
          detail={`${data.total_runs} 次运行`}
          icon={<Gauge size={17} />}
          tone="coral"
        />
      </div>
      <div className="admin-overview-grid">
        <section className="admin-section">
          <SectionHeader
            eyebrow="PROVIDER HEALTH"
            title="Provider 状态"
            action={
              <Link to="/admin/providers" className="text-link">
                全部 <RefreshCw size={13} />
              </Link>
            }
          />
          <div className="provider-health-list">
            {data.providers.map((provider) => (
              <div className="provider-health-row" key={provider.id}>
                <span className={`health-dot dot-${statusTone(provider.status)}`} />
                <div>
                  <strong>{provider.name}</strong>
                  <small>
                    {provider.total_calls} calls · {formatCost(provider.total_cost)}
                  </small>
                </div>
                <Badge tone={statusTone(provider.status)}>{provider.status}</Badge>
              </div>
            ))}
          </div>
        </section>
        <section className="admin-section">
          <SectionHeader
            eyebrow="AUDIT STREAM"
            title="最近活动"
            action={
              <Link to="/admin/audit" className="text-link">
                打开审计 <ListChecks size={13} />
              </Link>
            }
          />
          <div className="activity-list">
            {data.recent_activities.map((item) => (
              <div className="activity-row" key={item.id}>
                <span className="activity-dot" />
                <div>
                  <strong>{item.action}</strong>
                  <small>
                    {item.resource_type || 'system'} · {formatDate(item.created_at, true)}
                  </small>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

function AdminUsers() {
  const { user: currentUser } = useAuth()
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['admin-users'], queryFn: () => adminApi.users() })
  const [search, setSearch] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const users = (query.data?.users ?? []).filter((user) =>
    `${user.email} ${user.full_name || ''}`.toLowerCase().includes(search.toLowerCase()),
  )
  async function changeRole(user: User, role: string) {
    try {
      await adminApi.changeRole(user.id, role)
      await client.invalidateQueries({ queryKey: ['admin-users'] })
      toast.success('角色已更新')
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }
  async function toggle(user: User) {
    try {
      await adminApi.toggleUser(user.id, !user.is_active)
      await client.invalidateQueries({ queryKey: ['admin-users'] })
      toast.success(user.is_active ? '用户已停用' : '用户已激活')
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }
  return (
    <div className="admin-page">
      <SectionHeader
        eyebrow="ACCESS CONTROL"
        title="用户与权限"
        detail="角色和激活状态由管理员控制，项目访问仍按 owner/admin 规则执行。"
        action={
          <Button variant="soft" onClick={() => setCreateOpen(true)}>
            <Plus size={15} />
            创建用户
          </Button>
        }
      />
      <div className="table-toolbar">
        <div className="table-search">
          <Users size={15} />
          <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="按邮箱或姓名搜索" />
        </div>
        <Badge>
          {users.length} / {query.data?.total || 0}
        </Badge>
      </div>
      <div className="table-panel">
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>用户</th>
                <th>角色</th>
                <th>状态</th>
                <th>加入时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>
                    <div className="table-user">
                      <span className="avatar avatar-sm">
                        {(user.full_name || user.email).slice(0, 1).toUpperCase()}
                      </span>
                      <span>
                        <strong>{user.full_name || '未设置姓名'}</strong>
                        <small>{user.email}</small>
                      </span>
                    </div>
                  </td>
                  <td>
                    <select
                      className="native-select"
                      value={user.role}
                      disabled={user.id === currentUser?.id}
                      aria-label={`设置 ${user.email} 的角色`}
                      title={user.id === currentUser?.id ? '不能修改自己的管理员角色' : '修改用户角色'}
                      onChange={(event) => void changeRole(user, event.target.value)}
                    >
                      <option value="user">user</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td>
                    <Badge tone={user.is_active ? 'success' : 'danger'}>{user.is_active ? '活跃' : '停用'}</Badge>
                  </td>
                  <td>{formatDate(user.created_at)}</td>
                  <td>
                    <Button
                      variant={user.is_active ? 'ghost' : 'soft'}
                      size="sm"
                      disabled={user.id === currentUser?.id}
                      title={user.id === currentUser?.id ? '不能停用当前账户' : undefined}
                      onClick={() => void toggle(user)}
                    >
                      {user.is_active ? '停用' : '激活'}
                    </Button>
                  </td>
                </tr>
              ))}
              {!query.isLoading && users.length === 0 && (
                <tr>
                  <td className="table-empty-cell" colSpan={5}>
                    没有匹配的用户
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="admin-user-dialog">
          <p className="eyebrow">NEW ACCOUNT</p>
          <DialogTitle className="admin-dialog-title">创建用户</DialogTitle>
          <DialogDescription className="admin-dialog-description">
            新账户会立即激活，并获得所选角色对应的访问范围。
          </DialogDescription>
          <CreateUserForm
            onCreated={() => {
              setCreateOpen(false)
              void client.invalidateQueries({ queryKey: ['admin-users'] })
            }}
            onCancel={() => setCreateOpen(false)}
          />
        </DialogContent>
      </Dialog>
    </div>
  )
}

function CreateUserForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const [form, setForm] = useState({ email: '', full_name: '', password: '', confirm: '', role: 'user' })
  const mutation = useMutation({
    mutationFn: () =>
      adminApi.createUser({
        email: form.email.trim(),
        password: form.password,
        full_name: form.full_name.trim() || undefined,
        role: form.role,
      }),
    onSuccess: () => {
      toast.success('用户已创建')
      onCreated()
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (form.password !== form.confirm) {
      toast.error('两次输入的密码不一致')
      return
    }
    mutation.mutate()
  }

  return (
    <form className="admin-create-user-form" onSubmit={submit}>
      <div className="form-grid">
        <div className="field-group field-span-2">
          <Label htmlFor="admin-user-email">邮箱</Label>
          <Input
            id="admin-user-email"
            type="email"
            autoComplete="off"
            required
            value={form.email}
            onChange={(event) => setForm({ ...form, email: event.target.value })}
            placeholder="name@organization.org"
          />
        </div>
        <div className="field-group">
          <Label htmlFor="admin-user-name">显示名称</Label>
          <Input
            id="admin-user-name"
            autoComplete="off"
            value={form.full_name}
            onChange={(event) => setForm({ ...form, full_name: event.target.value })}
            placeholder="可选"
          />
        </div>
        <div className="field-group">
          <Label htmlFor="admin-user-role">角色</Label>
          <select
            id="admin-user-role"
            className="native-select admin-role-select"
            value={form.role}
            onChange={(event) => setForm({ ...form, role: event.target.value })}
          >
            <option value="user">user · 个人空间</option>
            <option value="admin">admin · 全局管理</option>
          </select>
        </div>
        <div className="field-group">
          <Label htmlFor="admin-user-password">初始密码</Label>
          <Input
            id="admin-user-password"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
            placeholder="至少 12 个字符"
          />
        </div>
        <div className="field-group">
          <Label htmlFor="admin-user-confirm">确认密码</Label>
          <Input
            id="admin-user-confirm"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            value={form.confirm}
            onChange={(event) => setForm({ ...form, confirm: event.target.value })}
            placeholder="再次输入"
          />
        </div>
      </div>
      <div className="form-actions">
        <Button type="button" variant="ghost" onClick={onCancel}>
          取消
        </Button>
        <Button type="submit" disabled={mutation.isPending || !form.email.trim() || form.password.length < 12}>
          {mutation.isPending ? '创建中…' : '创建用户'}
        </Button>
      </div>
    </form>
  )
}

function AdminProviders() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['admin-providers'], queryFn: () => adminApi.providers() })
  const [kind, setKind] = useState('all')
  const [showForm, setShowForm] = useState(false)
  const [providerToDelete, setProviderToDelete] = useState<ProviderInfo | null>(null)
  const [deleting, setDeleting] = useState(false)
  const providers = (query.data?.providers ?? []).filter((provider) => kind === 'all' || provider.kind === kind)
  async function toggle(provider: ProviderInfo) {
    try {
      await adminApi.toggleProvider(provider.id)
      await client.invalidateQueries({ queryKey: ['admin-providers'] })
      toast.success('Provider 状态已更新')
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }
  async function test(provider: ProviderInfo) {
    try {
      const result = await adminApi.testProvider(provider.id)
      toast[result.healthy ? 'success' : 'error'](result.message || (result.healthy ? '健康检查通过' : '健康检查失败'))
      await client.invalidateQueries({ queryKey: ['admin-providers'] })
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }
  async function reload() {
    try {
      await adminApi.reloadProviders()
      toast.success('运行时 Provider 已重载')
      await client.invalidateQueries({ queryKey: ['admin-providers'] })
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }
  async function removeProvider() {
    if (!providerToDelete) return
    setDeleting(true)
    try {
      await adminApi.deleteProvider(providerToDelete.id)
      await client.invalidateQueries({ queryKey: ['admin-providers'] })
      await client.invalidateQueries({ queryKey: ['admin-audit'] })
      toast.success(`Provider「${providerToDelete.display_name}」已删除`)
      setProviderToDelete(null)
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Provider 删除失败'))
    } finally {
      setDeleting(false)
    }
  }
  return (
    <div className="admin-page">
      <SectionHeader
        eyebrow="MODEL ROUTING"
        title="Provider 管理"
        detail="密钥只显示掩码；健康状态来自后端检查和运行时池。"
        action={
          <div className="header-actions">
            <Button variant="outline" onClick={() => void reload()}>
              <RefreshCw size={15} />
              重载池
            </Button>
            <Button onClick={() => setShowForm((value) => !value)}>
              <Plus size={15} />
              新增 Provider
            </Button>
          </div>
        }
      />
      {showForm && (
        <ProviderForm
          onCreated={() => {
            setShowForm(false)
            void client.invalidateQueries({ queryKey: ['admin-providers'] })
          }}
        />
      )}
      <div className="segmented-control">
        <button className={kind === 'all' ? 'segment-active' : ''} onClick={() => setKind('all')}>
          全部
        </button>
        <button className={kind === 'llm' ? 'segment-active' : ''} onClick={() => setKind('llm')}>
          LLM
        </button>
        <button className={kind === 'embedding' ? 'segment-active' : ''} onClick={() => setKind('embedding')}>
          Embedding
        </button>
        <button className={kind === 'rerank' ? 'segment-active' : ''} onClick={() => setKind('rerank')}>
          Rerank
        </button>
      </div>
      <div className="provider-grid">
        {providers.map((provider) => (
          <Card className="provider-card" key={provider.id}>
            <CardContent>
              <div className="provider-card-heading">
                <div className={`provider-logo provider-logo-${provider.kind}`}>
                  {provider.kind === 'llm' ? 'L' : provider.kind === 'embedding' ? 'E' : 'R'}
                </div>
                <div>
                  <h3>{provider.display_name}</h3>
                  <p>{provider.model || '模型未设置'}</p>
                </div>
                <Badge tone={statusTone(provider.health_status)}>{provider.health_status}</Badge>
              </div>
              <div className="provider-details">
                <span>
                  <small>Endpoint</small>
                  <strong>{provider.base_url}</strong>
                </span>
                <span>
                  <small>RPM limit</small>
                  <strong>{provider.rpm_limit}</strong>
                </span>
                <span>
                  <small>Priority</small>
                  <strong>{provider.priority}</strong>
                </span>
                <span>
                  <small>API key</small>
                  <strong>{provider.api_key_hint || '未设置'}</strong>
                </span>
              </div>
              {provider.last_error && (
                <div className="provider-error">
                  <AlertTriangle size={14} />
                  {provider.last_error}
                </div>
              )}
              <div className="provider-actions">
                <Button variant="outline" size="sm" onClick={() => void test(provider)}>
                  <Activity size={14} />
                  健康检查
                </Button>
                <Button
                  variant={provider.is_enabled ? 'ghost' : 'soft'}
                  size="sm"
                  onClick={() => void toggle(provider)}
                >
                  <ToggleLeft size={14} />
                  {provider.is_enabled ? '停用' : '启用'}
                </Button>
                <Button
                  className="provider-delete"
                  variant="ghost"
                  size="icon"
                  aria-label={`删除 ${provider.display_name}`}
                  title={`删除 ${provider.display_name}`}
                  onClick={() => setProviderToDelete(provider)}
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      <Dialog
        open={Boolean(providerToDelete)}
        onOpenChange={(open) => {
          if (!open && !deleting) setProviderToDelete(null)
        }}
      >
        <DialogContent className="admin-confirm-dialog">
          <DialogTitle className="admin-dialog-title">删除 Provider</DialogTitle>
          <DialogDescription className="admin-dialog-description">
            {providerToDelete ? `将从运行时池中移除「${providerToDelete.display_name}」，已有调用记录不会被删除。` : ''}
          </DialogDescription>
          <div className="form-actions">
            <Button variant="ghost" disabled={deleting} onClick={() => setProviderToDelete(null)}>
              取消
            </Button>
            <Button variant="danger" disabled={deleting} onClick={() => void removeProvider()}>
              <Trash2 size={14} />
              {deleting ? '删除中…' : '删除 Provider'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function AdminSources() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['admin-sources'], queryFn: adminApi.sources })
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  async function mutate(
    config: SourceConfigInfo,
    action: 'replace' | 'append' | 'clear',
  ) {
    const value = (drafts[config.key] ?? '').trim()
    try {
      if (action === 'clear') {
        await adminApi.clearSource(config.key)
      } else if (action === 'append') {
        if (!value) return toast.error('请输入需要追加的值')
        await adminApi.appendSource(config.key, value)
      } else {
        if (!value) return toast.error('请输入配置值')
        await adminApi.updateSource(config.key, value)
      }
      setDrafts((current) => ({ ...current, [config.key]: '' }))
      await client.invalidateQueries({ queryKey: ['admin-sources'] })
      toast.success(action === 'clear' ? '信息源配置已清除' : '信息源配置已保存')
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  const configs = query.data?.configs ?? []
  const byKey = new Map(configs.map((config) => [config.key, config]))
  return (
    <div className="admin-page">
      <SectionHeader
        eyebrow="ACADEMIC SOURCES"
        title="信息源配置"
        detail="认证信息加密保存；检索源开关在运行配置中统一控制。"
      />
      <div className="source-catalog-grid">
        {(query.data?.sources ?? []).map((source) => {
          const dependencies = source.configuration_keys.map((key) => byKey.get(key)).filter(Boolean) as SourceConfigInfo[]
          const ready = dependencies.length === 0 || dependencies.every((config) => config.is_set && config.is_enabled)
          return (
            <Card className="source-catalog-card" key={source.key}>
              <CardContent>
                <div className="provider-card-heading">
                  <div className="provider-logo provider-logo-rerank"><BookOpen size={17} /></div>
                  <div>
                    <h3>{source.label}</h3>
                    <p>{source.authentication}</p>
                  </div>
                  <Badge tone={ready ? 'success' : 'neutral'}>{ready ? '就绪' : '待配置'}</Badge>
                </div>
                <p className="source-catalog-description">{source.description}</p>
                <div className="source-catalog-meta">
                  <span>{source.rate_limit_hint}</span>
                  <span>{dependencies.length ? dependencies.map((config) => config.label).join(' · ') : '无需配置'}</span>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
      <section className="admin-section source-config-section">
        <SectionHeader eyebrow="CREDENTIALS" title="认证与联系信息" />
        <div className="source-config-list">
          {configs.map((config) => (
            <Card key={config.key}>
              <CardContent>
                <div className="source-config-row">
                  <div>
                    <div className="source-config-title">
                      <h3>{config.label}</h3>
                      <Badge tone={config.is_set && config.is_enabled ? 'success' : 'neutral'}>
                        {config.is_set && config.is_enabled ? '已配置' : '未配置'}
                      </Badge>
                    </div>
                    <p>{config.description}</p>
                    <small>{config.value_source === 'db' ? '数据库覆盖' : '环境变量'}{config.supports_multiple ? ` · ${config.key_count} 个有效 Key` : ''}</small>
                  </div>
                  <div className="source-config-control">
                    <Input
                      aria-label={config.label}
                      type={config.is_secret ? 'password' : 'email'}
                      value={drafts[config.key] ?? ''}
                      onChange={(event) => setDrafts((current) => ({ ...current, [config.key]: event.target.value }))}
                      placeholder={config.supports_multiple ? '输入一个或多个 Key（逗号分隔）' : config.is_secret ? '输入新的密钥' : 'name@example.org'}
                    />
                    <div className="source-config-actions">
                      {config.supports_multiple && (
                        <Button variant="soft" size="sm" onClick={() => void mutate(config, 'append')}>
                          <Plus size={14} />
                          追加
                        </Button>
                      )}
                      <Button variant="outline" size="sm" onClick={() => void mutate(config, 'replace')}>
                        <Save size={14} />
                        保存
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => void mutate(config, 'clear')}>
                        <Trash2 size={14} />
                        清除
                      </Button>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
    </div>
  )
}

function ProviderForm({ onCreated }: { onCreated: () => void }) {
  const [form, setForm] = useState({
    kind: 'llm',
    display_name: '',
    base_url: '',
    model: '',
    api_key: '',
    rpm_limit: '10',
  })
  const mutation = useMutation({
    mutationFn: () => adminApi.createProvider({ ...form, rpm_limit: Number(form.rpm_limit), is_enabled: true }),
    onSuccess: () => {
      toast.success('Provider 已创建')
      onCreated()
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  })
  return (
    <Card className="provider-form">
      <CardContent>
        <div className="form-grid">
          <div className="field-group">
            <Label htmlFor="provider-kind">类型</Label>
            <select
              id="provider-kind"
              className="native-select"
              value={form.kind}
              onChange={(event) => setForm({ ...form, kind: event.target.value })}
            >
              <option value="llm">LLM</option>
              <option value="embedding">Embedding</option>
              <option value="rerank">Rerank</option>
            </select>
          </div>
          <div className="field-group">
            <Label htmlFor="provider-name">名称</Label>
            <Input
              id="provider-name"
              value={form.display_name}
              onChange={(event) => setForm({ ...form, display_name: event.target.value })}
              placeholder="例如：local-qwen"
            />
          </div>
          <div className="field-group field-span-2">
            <Label htmlFor="provider-base-url">Base URL</Label>
            <Input
              id="provider-base-url"
              value={form.base_url}
              onChange={(event) => setForm({ ...form, base_url: event.target.value })}
              placeholder={form.kind === 'rerank' ? 'https://provider.example/v1/rerank' : 'https://provider.example/v1'}
            />
          </div>
          <div className="field-group">
            <Label htmlFor="provider-model">模型</Label>
            <Input
              id="provider-model"
              value={form.model}
              onChange={(event) => setForm({ ...form, model: event.target.value })}
              placeholder="model-name"
            />
          </div>
          <div className="field-group">
            <Label htmlFor="provider-rpm">RPM</Label>
            <Input
              id="provider-rpm"
              type="number"
              min="1"
              value={form.rpm_limit}
              onChange={(event) => setForm({ ...form, rpm_limit: event.target.value })}
            />
          </div>
          <div className="field-group field-span-2">
            <Label htmlFor="provider-api-key">API Key</Label>
            <Input
              id="provider-api-key"
              type="password"
              value={form.api_key}
              onChange={(event) => setForm({ ...form, api_key: event.target.value })}
              placeholder="仅在提交时发送"
            />
          </div>
        </div>
        <div className="form-actions">
          <Button variant="ghost" onClick={onCreated}>
            取消
          </Button>
          <Button
            disabled={mutation.isPending || !form.display_name || !form.base_url}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? '保存中…' : '保存 Provider'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function AdminProjects() {
  const query = useQuery({ queryKey: ['admin-projects'], queryFn: () => adminApi.projects({ skip: 0, limit: 100 }) })
  const [search, setSearch] = useState('')
  const projects = (query.data?.projects ?? []).filter((project) =>
    `${project.name} ${project.query} ${project.user_id || ''}`.toLowerCase().includes(search.toLowerCase()),
  )
  return (
    <div className="admin-page">
      <SectionHeader
        eyebrow="GLOBAL INVENTORY"
        title="全局项目"
        detail="管理员可查看跨用户项目状态，但不改变项目 owner 语义。"
      />
      <div className="table-toolbar">
        <div className="table-search">
          <Database size={15} />
          <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索项目或用户" />
        </div>
        <Badge>{projects.length} 个项目</Badge>
      </div>
      <div className="table-panel">
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>项目</th>
                <th>所有者</th>
                <th>状态</th>
                <th>论文</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((project) => (
                <tr key={project.id}>
                  <td>
                    <Link to={`/projects/${project.id}`} className="table-link">
                      <strong>{project.name}</strong>
                      <small>{project.query}</small>
                    </Link>
                  </td>
                  <td>
                    <strong>{project.user_name || '—'}</strong>
                    <small>{project.user_email || project.user_id}</small>
                  </td>
                  <td>
                    <Badge tone={statusTone(project.status)}>{project.status}</Badge>
                  </td>
                  <td>{project.paper_count ?? '—'}</td>
                  <td>{formatDate(project.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function AdminUsage() {
  const [callType, setCallType] = useState<'all' | 'llm' | 'embedding' | 'rerank'>('all')
  const [callPage, setCallPage] = useState(0)
  const trendQuery = useQuery({ queryKey: ['admin-usage-trend'], queryFn: () => adminApi.usageTrend(30) })
  const providerQuery = useQuery({ queryKey: ['admin-provider-usage'], queryFn: () => adminApi.providerUsage(30) })
  const callsQuery = useQuery({
    queryKey: ['admin-recent-calls', callType, callPage],
    queryFn: () =>
      adminApi.recentCalls({
        limit: 100,
        skip: callPage * 100,
        call_type: callType === 'all' ? undefined : callType,
      }),
  })
  const calls = (callsQuery.data ?? []).filter((call) => callType === 'all' || call.call_type === callType)
  return (
    <div className="admin-page">
      <SectionHeader eyebrow="OBSERVABILITY" title="全局用量" detail="管理员可查看所有用户、项目和模型调用明细。" />
      <div className="admin-usage-grid">
        <Card>
          <CardContent>
            <SectionHeader eyebrow="30 DAY TOKENS" title="调用趋势" />
            {trendQuery.data?.length ? (
              <UsageTrendChart data={trendQuery.data} height={260} />
            ) : (
              <EmptyState icon={<Activity size={22} />} title="暂无趋势数据" />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent>
            <SectionHeader eyebrow="PROVIDER MIX" title="Provider 表现" />
            {providerQuery.data?.length ? (
              <div className="provider-usage-list">
                {providerQuery.data.slice(0, 8).map((item: Record<string, unknown>, index: number) => (
                  <div className="provider-usage-row" key={`${String(item.provider_name)}-${index}`}>
                    <span>{String(item.provider_name || 'unknown')}</span>
                    <strong>{formatNumber(Number(item.total_tokens || 0))}</strong>
                    <small>{formatCost(Number(item.total_cost || 0))}</small>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState icon={<Server size={22} />} title="暂无 Provider 数据" />
            )}
          </CardContent>
        </Card>
      </div>
      <section className="admin-section admin-call-details">
        <SectionHeader title="调用明细" detail={`第 ${callPage + 1} 页 · ${calls.length} 条记录`} />
        <div className="segmented-control call-type-filter" role="group" aria-label="调用类型">
          {(['all', 'llm', 'embedding', 'rerank'] as const).map((type) => (
            <button
              type="button"
              key={type}
              className={callType === type ? 'segment-active' : ''}
              onClick={() => {
                setCallType(type)
                setCallPage(0)
              }}
            >
              {type === 'all' ? '全部' : type}
            </button>
          ))}
        </div>
        {callsQuery.isLoading ? (
          <Skeleton className="skeleton-panel" />
        ) : callsQuery.isError ? (
          <EmptyState icon={<AlertTriangle size={22} />} title="调用记录加载失败" />
        ) : calls.length === 0 ? (
          <EmptyState icon={<Activity size={22} />} title="暂无调用记录" />
        ) : (
          <div className="data-table-wrap">
            <table className="data-table admin-call-table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>类型</th>
                  <th>用户 / 项目</th>
                  <th>节点</th>
                  <th>Provider / 模型</th>
                  <th>Token</th>
                  <th>耗时</th>
                  <th>成本</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((call: LlmCall) => (
                  <tr key={call.id}>
                    <td>{formatDate(call.created_at, true)}</td>
                    <td>
                      <Badge tone={call.call_type === 'embedding' ? 'active' : 'neutral'}>
                        {call.call_type || 'llm'}
                      </Badge>
                    </td>
                    <td>
                      <strong>{call.user_email || '系统'}</strong>
                      <small>{call.project_name || call.project_id || '—'}</small>
                    </td>
                    <td>
                      <code>{call.node_name || '—'}</code>
                    </td>
                    <td>
                      <strong>{call.provider_name || '—'}</strong>
                      <small>{call.upstream_model || call.model_name || call.requested_model || '—'}</small>
                    </td>
                    <td>{formatNumber(call.total_tokens)}</td>
                    <td>{formatDuration(call.latency_ms)}</td>
                    <td>{formatCost(call.cost)}</td>
                    <td>
                      <Badge tone={statusTone(call.status)}>{call.status || 'unknown'}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="table-pagination" aria-label="调用明细分页">
          <Button
            variant="ghost"
            size="sm"
            disabled={callPage === 0 || callsQuery.isFetching}
            onClick={() => setCallPage((page) => Math.max(0, page - 1))}
          >
            上一页
          </Button>
          <span>第 {callPage + 1} 页</span>
          <Button
            variant="ghost"
            size="sm"
            disabled={calls.length < 100 || callsQuery.isFetching}
            onClick={() => setCallPage((page) => page + 1)}
          >
            下一页
          </Button>
        </div>
      </section>
    </div>
  )
}

function AdminAudit() {
  const query = useQuery({ queryKey: ['admin-audit'], queryFn: () => adminApi.audit({ limit: 200 }) })
  return (
    <div className="admin-page">
      <SectionHeader eyebrow="AUDIT LOG" title="审计事件" detail="记录用户、项目、Provider 和权限变更。" />
      <div className="table-panel">
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>动作</th>
                <th>资源</th>
                <th>用户</th>
                <th>详情</th>
              </tr>
            </thead>
            <tbody>
              {(query.data?.logs ?? []).map((log) => (
                <tr key={String(log.id)}>
                  <td>{formatDate(String(log.created_at || ''), true)}</td>
                  <td>
                    <code>{String(log.action || '—')}</code>
                  </td>
                  <td>
                    {String(log.resource_type || '—')}
                    <small>{String(log.resource_id || '')}</small>
                  </td>
                  <td>
                    <strong>{log.user_email || log.user_id || '系统'}</strong>
                    {log.user_email && log.user_id && <small>{log.user_id}</small>}
                  </td>
                  <td className="audit-detail">{JSON.stringify(log.details || {})}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function AdminConfig() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['admin-config'], queryFn: adminApi.pipelineConfig })
  async function update(key: string, value: string) {
    try {
      const result = await adminApi.updatePipelineConfig(key, value)
      await client.invalidateQueries({ queryKey: ['admin-config'] })
      if (result.reindex_required) {
        toast.warning(`维度已更新；现有 ${result.existing_dimensions?.join('、') || '旧'} 维向量需要重新生成。`)
      } else {
        toast.success('配置已更新')
      }
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }
  async function reset() {
    try {
      await adminApi.resetPipelineConfig()
      await client.invalidateQueries({ queryKey: ['admin-config'] })
      toast.success('运行配置已恢复默认值')
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }
  const groups = (query.data ?? []).reduce<Record<string, Array<Record<string, unknown>>>>((result, item) => {
    const group = String(item.group || '其他')
    result[group] = [...(result[group] ?? []), item]
    return result
  }, {})
  return (
    <div className="admin-page">
      <SectionHeader
        eyebrow="RUNTIME POLICY"
        title="运行配置"
        detail="仅管理员可修改；公开 features 读取由后端单独提供。"
        action={
          <Button variant="outline" onClick={() => void reset()}>
            <RotateCcw size={15} />
            恢复默认值
          </Button>
        }
      />
      <div className="config-groups">
        {Object.entries(groups).map(([group, items]) => (
          <section className="config-group" key={group}>
            <h2>{group}</h2>
            <div className="config-list">
        {items.map((item) => (
          <Card key={String(item.key)}>
            <CardContent>
              <div className="config-row">
                <div>
                  <h3>{String(item.label || item.key)}</h3>
                  <p>{String(item.description || '')}</p>
                  <code>{String(item.key)}</code>
                </div>
                <div className="config-control">
                  {String(item.type) === 'bool' ? (
                    <button
                      className={String(item.value) === 'true' ? 'toggle-control toggle-on' : 'toggle-control'}
                      onClick={() => void update(String(item.key), String(item.value) === 'true' ? 'false' : 'true')}
                    >
                      <span />
                      <strong>{String(item.value) === 'true' ? '开启' : '关闭'}</strong>
                    </button>
                  ) : String(item.type) === 'sources' ? (
                    <div className="config-source-options" role="group" aria-label={String(item.label || item.key)}>
                      {(Array.isArray(item.options) ? item.options : []).map((option) => {
                        let selected = false
                        try { selected = JSON.parse(String(item.value)).includes(option) } catch { selected = false }
                        return (
                          <label key={String(option)}>
                            <input
                              type="checkbox"
                              checked={selected}
                              onChange={() => {
                                let values: string[] = []
                                try { values = JSON.parse(String(item.value)) } catch { values = [] }
                                const next = selected ? values.filter((value) => value !== option) : [...values, String(option)]
                                if (next.length) void update(String(item.key), JSON.stringify(next))
                              }}
                            />
                            {String(option)}
                          </label>
                        )
                      })}
                    </div>
                  ) : String(item.type) === 'choice' ? (
                    <label className="config-select-control">
                      <ListFilter size={15} />
                      <select
                        className="native-select"
                        aria-label={String(item.label || item.key)}
                        value={String(item.value)}
                        onChange={(event) => void update(String(item.key), event.target.value)}
                      >
                        {(Array.isArray(item.options) ? item.options : []).map((option) => (
                          <option key={String(option)} value={String(option)}>
                            {String(option)}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : (
                    <Input
                      type={String(item.type) === 'integer' || String(item.type) === 'number' ? 'number' : 'text'}
                      min={typeof item.minimum === 'number' ? item.minimum : undefined}
                      max={typeof item.maximum === 'number' ? item.maximum : undefined}
                      step={String(item.type) === 'integer' ? 1 : 'any'}
                      defaultValue={String(item.value)}
                      onBlur={(event) => void update(String(item.key), event.target.value)}
                    />
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
