import { Activity, ArrowUpRight, BookOpen, Coins, FolderKanban, KeyRound, Search, UserRound } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { consoleApi, getFeatures, projectsApi, apiErrorMessage } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatCost, formatDate, formatNumber, statusLabel, statusTone } from '../lib/pipeline'
import {
  Badge,
  Button,
  Card,
  CardContent,
  EmptyState,
  Input,
  Label,
  MetricCard,
  SectionHeader,
  Skeleton,
} from '../components/ui'
import { UsageTrendChart } from '../components/UsageTrendChart'

export function ConsolePage() {
  const { section = 'overview' } = useParams()
  const { user, refreshUser } = useAuth()
  const queryClient = useQueryClient()
  const overviewQuery = useQuery({ queryKey: ['console-overview'], queryFn: consoleApi.overview })
  const projectsQuery = useQuery({ queryKey: ['projects', 'console'], queryFn: () => projectsApi.list(0, 100) })
  const featuresQuery = useQuery({ queryKey: ['features'], queryFn: getFeatures })
  const trendQuery = useQuery({
    queryKey: ['console-trend'],
    queryFn: () => consoleApi.trend(30),
    enabled: section === 'usage',
  })
  const callsQuery = useQuery({
    queryKey: ['console-calls'],
    queryFn: () => consoleApi.calls({ limit: 100 }),
    enabled: section === 'usage',
  })

  if (section === 'projects')
    return <ProjectsPanel projects={projectsQuery.data?.projects ?? []} loading={projectsQuery.isLoading} />
  if (section === 'usage')
    return featuresQuery.data?.show_usage ? (
      <UsagePanel
        trend={trendQuery.data ?? []}
        calls={callsQuery.data ?? []}
        loading={trendQuery.isLoading || callsQuery.isLoading}
      />
    ) : (
      <EmptyState
        icon={<Activity size={25} />}
        title="用量面板当前未开放"
        detail="管理员可在运行配置中启用个人用量视图。"
      />
    )
  if (section === 'profile')
    return (
      <ProfilePanel
        email={user?.email || ''}
        initialName={user?.full_name || ''}
        onSaved={() => {
          void refreshUser()
          void queryClient.invalidateQueries({ queryKey: ['console-overview'] })
        }}
      />
    )

  const overview = overviewQuery.data
  return (
    <div className="console-page">
      <SectionHeader
        eyebrow="YOUR WORKSPACE"
        title={`上午好，${user?.full_name || user?.email?.split('@')[0] || '研究者'}`}
        detail="这里汇总你有权限访问的项目、来源和模型用量。"
        action={
          <Link to="/">
            <Button>
              <Search size={15} />
              开始研究
            </Button>
          </Link>
        }
      />
      <div className="console-metrics">
        <MetricCard
          label="研究项目"
          value={formatNumber(overview?.project_count)}
          detail={`${overview?.running_projects || 0} 个正在运行`}
          icon={<FolderKanban size={17} />}
          tone="sage"
        />
        <MetricCard
          label="纳入论文"
          value={formatNumber(overview?.total_papers)}
          detail="当前用户空间"
          icon={<BookOpen size={17} />}
          tone="amber"
        />
        <MetricCard
          label="Token 用量"
          value={formatNumber(overview?.total_tokens)}
          detail="累计模型调用"
          icon={<Activity size={17} />}
        />
        <MetricCard
          label="估算成本"
          value={formatCost(overview?.total_cost)}
          detail="按 Provider 定价"
          icon={<Coins size={17} />}
          tone="coral"
        />
      </div>
      <div className="console-overview-grid">
        <section className="workspace-section">
          <SectionHeader
            eyebrow="RECENT PROJECTS"
            title="最近研究"
            action={
              <Link to="/console/projects" className="text-link">
                查看全部 <ArrowUpRight size={14} />
              </Link>
            }
          />
          {overviewQuery.isLoading ? (
            <Skeleton className="skeleton-panel" />
          ) : overview?.recent_projects.length ? (
            <div className="recent-projects-list">
              {overview.recent_projects.map((project) => (
                <Link to={`/projects/${project.id}`} className="recent-project-row" key={project.id}>
                  <span className={`project-status-dot dot-${statusTone(project.status)}`} />
                  <div>
                    <strong>{project.name}</strong>
                    <small>{formatDate(project.created_at)}</small>
                  </div>
                  <Badge tone={statusTone(project.status)}>{statusLabel(project.status)}</Badge>
                  <ArrowUpRight size={15} />
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={<FolderKanban size={22} />}
              title="还没有研究项目"
              action={
                <Link to="/">
                  <Button variant="soft">创建第一个项目</Button>
                </Link>
              }
            />
          )}
        </section>
        <aside className="workspace-aside">
          <SectionHeader eyebrow="ACCESS BOUNDARY" title="空间与权限" />
          <Card className="access-card">
            <CardContent>
              <div className="access-avatar">
                <UserRound size={20} />
              </div>
              <div>
                <strong>个人研究空间</strong>
                <p>项目按账户所有权隔离；管理员拥有全局审计权限。</p>
              </div>
              <Badge tone="success">{user?.role === 'admin' ? 'admin' : 'member'}</Badge>
            </CardContent>
          </Card>
          <div className="workspace-signal">
            <span className="signal-line signal-sage" />
            <div>
              <strong>身份状态</strong>
              <p>{user?.is_active ? '账户已激活' : '账户已停用'}</p>
            </div>
          </div>
          <div className="workspace-signal">
            <span className="signal-line signal-amber" />
            <div>
              <strong>访问范围</strong>
              <p>{user?.role === 'admin' ? '系统全局视图' : '仅自己的项目与用量'}</p>
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}

function ProjectsPanel({
  projects,
  loading,
}: {
  projects: Awaited<ReturnType<typeof projectsApi.list>>['projects']
  loading: boolean
}) {
  const [search, setSearch] = useState('')
  const filtered = useMemo(
    () => projects.filter((project) => `${project.name} ${project.query}`.toLowerCase().includes(search.toLowerCase())),
    [projects, search],
  )
  return (
    <div className="console-page">
      <SectionHeader
        eyebrow="PROJECT LEDGER"
        title="研究项目"
        detail="当前用户空间内的全部研究任务。"
        action={
          <Link to="/">
            <Button>
              <Search size={15} />
              新研究
            </Button>
          </Link>
        }
      />
      <div className="table-toolbar">
        <div className="table-search">
          <Search size={15} />
          <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索项目或问题" />
        </div>
        <Badge>{filtered.length} 个项目</Badge>
      </div>
      {loading ? (
        <Skeleton className="skeleton-panel" />
      ) : (
        <div className="project-cards-grid">
          {filtered.map((project) => (
            <Link to={`/projects/${project.id}`} key={project.id} className="project-ledger-card">
              <div className="project-ledger-top">
                <span className={`project-status-dot dot-${statusTone(project.status)}`} />
                <Badge tone={statusTone(project.status)}>{statusLabel(project.status)}</Badge>
                <span>{formatDate(project.created_at)}</span>
              </div>
              <h3>{project.name}</h3>
              <p>{project.query}</p>
              <div className="project-ledger-bottom">
                <span>{project.current_phase || 'supervisor'}</span>
                <ArrowUpRight size={15} />
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

function UsagePanel({
  trend,
  calls,
  loading,
}: {
  trend: Awaited<ReturnType<typeof consoleApi.trend>>
  calls: Awaited<ReturnType<typeof consoleApi.calls>>
  loading: boolean
}) {
  const totals = trend.reduce(
    (acc, item) => ({
      tokens: acc.tokens + item.total_tokens,
      cost: acc.cost + item.total_cost,
      calls: acc.calls + item.call_count,
    }),
    { tokens: 0, cost: 0, calls: 0 },
  )
  return (
    <div className="console-page">
      <SectionHeader eyebrow="USAGE & COST" title="个人用量" detail="仅统计当前用户可访问项目的模型调用。" />
      <div className="console-metrics">
        <MetricCard label="30 天调用" value={formatNumber(totals.calls)} icon={<Activity size={17} />} tone="sage" />
        <MetricCard label="30 天 Token" value={formatNumber(totals.tokens)} icon={<BookOpen size={17} />} />
        <MetricCard label="30 天成本" value={formatCost(totals.cost)} icon={<Coins size={17} />} tone="amber" />
      </div>
      {loading ? (
        <Skeleton className="skeleton-panel" />
      ) : (
        <>
          <section className="usage-band">
            <SectionHeader eyebrow="30 DAY TREND" title="调用趋势" />
            {trend.length ? (
              <UsageTrendChart data={trend} />
            ) : (
              <EmptyState icon={<Activity size={22} />} title="这个周期没有调用记录" />
            )}
          </section>
          <section className="table-panel">
            <SectionHeader eyebrow="RECENT CALLS" title="最近调用" />
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>项目 / 节点</th>
                    <th>模型</th>
                    <th>Token</th>
                    <th>成本</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {calls.slice(0, 30).map((call) => (
                    <tr key={call.id}>
                      <td>
                        <strong>{call.project_name || '未命名项目'}</strong>
                        <small>{call.node_name || 'unknown'}</small>
                      </td>
                      <td>{call.upstream_model || call.model_name || '—'}</td>
                      <td>{formatNumber(call.total_tokens)}</td>
                      <td>{formatCost(call.cost)}</td>
                      <td>
                        <Badge tone={statusTone(call.status)}>{call.status || 'unknown'}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}

function ProfilePanel({ email, initialName, onSaved }: { email: string; initialName: string; onSaved: () => void }) {
  const [name, setName] = useState(initialName)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  async function saveProfile(event: FormEvent) {
    event.preventDefault()
    try {
      await consoleApi.updateProfile({ full_name: name })
      onSaved()
      toast.success('个人资料已更新')
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }
  async function savePassword(event: FormEvent) {
    event.preventDefault()
    try {
      await consoleApi.changePassword({ current_password: currentPassword, new_password: newPassword })
      setCurrentPassword('')
      setNewPassword('')
      toast.success('密码已更新')
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }
  return (
    <div className="console-page">
      <SectionHeader eyebrow="ACCOUNT" title="个人资料" detail="维护你的显示信息和登录凭据。" />
      <div className="settings-grid">
        <Card>
          <CardContent>
            <div className="settings-heading">
              <UserRound size={18} />
              <div>
                <h3>基础资料</h3>
                <p>显示在研究空间和审计记录中</p>
              </div>
            </div>
            <form className="settings-form" onSubmit={saveProfile}>
              <div className="field-group">
                <Label htmlFor="profile-email">邮箱</Label>
                <Input id="profile-email" value={email} disabled />
              </div>
              <div className="field-group">
                <Label htmlFor="profile-name">显示名称</Label>
                <Input id="profile-name" value={name} onChange={(event) => setName(event.target.value)} />
              </div>
              <Button type="submit">保存资料</Button>
            </form>
          </CardContent>
        </Card>
        <Card>
          <CardContent>
            <div className="settings-heading">
              <KeyRound size={18} />
              <div>
                <h3>更改密码</h3>
                <p>新密码至少需要 12 个字符</p>
              </div>
            </div>
            <form className="settings-form" onSubmit={savePassword}>
              <div className="field-group">
                <Label htmlFor="current-password">当前密码</Label>
                <Input
                  id="current-password"
                  type="password"
                  value={currentPassword}
                  onChange={(event) => setCurrentPassword(event.target.value)}
                  required
                />
              </div>
              <div className="field-group">
                <Label htmlFor="new-password">新密码</Label>
                <Input
                  id="new-password"
                  type="password"
                  minLength={12}
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  required
                />
              </div>
              <Button type="submit" variant="soft">
                更新密码
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
