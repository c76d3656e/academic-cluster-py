import * as Dialog from '@radix-ui/react-dialog'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { AnimatePresence, motion } from 'motion/react'
import {
  Activity,
  BookOpen,
  ChevronDown,
  Command,
  Database,
  FolderKanban,
  LayoutDashboard,
  ListChecks,
  LockKeyhole,
  LogOut,
  Menu,
  Moon,
  Plus,
  Server,
  Settings2,
  ShieldCheck,
  Sun,
  UserRound,
  Users,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi, type Project } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatDate, statusTone } from '../lib/pipeline'
import { cn } from '../lib/utils'
import { Avatar, Button, Divider, Hint, IconButton, TooltipProvider } from './ui'

const userNav = [
  { to: '/console/overview', label: '概览', icon: LayoutDashboard },
  { to: '/console/projects', label: '项目', icon: FolderKanban },
  { to: '/console/usage', label: '用量', icon: Activity },
]

const adminNav = [
  { to: '/admin/overview', label: '管理概览', icon: ShieldCheck },
  { to: '/admin/users', label: '用户与权限', icon: Users },
  { to: '/admin/providers', label: 'Provider', icon: Server },
  { to: '/admin/sources', label: '信息源', icon: BookOpen },
  { to: '/admin/projects', label: '全局项目', icon: Database },
  { to: '/admin/usage', label: '全局用量', icon: Activity },
  { to: '/admin/audit', label: '审计日志', icon: ListChecks },
  { to: '/admin/pipeline-config', label: '运行配置', icon: Settings2 },
]

function SidebarContent({
  projects,
  onNavigate,
  collapsed,
  onToggleTheme,
  onToggleCollapse,
  dark,
}: {
  projects: Project[]
  onNavigate?: () => void
  collapsed: boolean
  onToggleTheme: () => void
  onToggleCollapse?: () => void
  dark: boolean
}) {
  const { user, logout, isAdmin } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const inAdmin = location.pathname.startsWith('/admin')
  const [projectSearch, setProjectSearch] = useState('')
  const filteredProjects = useMemo(
    () =>
      projects
        .filter((project) => `${project.name} ${project.query}`.toLowerCase().includes(projectSearch.toLowerCase()))
        .slice(0, 8),
    [projectSearch, projects],
  )

  async function signOut() {
    await logout()
    navigate('/login')
  }

  return (
    <div className={cn('shell-sidebar-inner', collapsed && 'shell-sidebar-inner-collapsed')}>
      <div className="brand-row">
        <Link to="/" className="brand-mark" onClick={onNavigate} aria-label="Academic Cluster 首页">
          <span className="brand-glyph">A</span>
          {!collapsed && (
            <span>
              <strong>Academic</strong>
              <em>Cluster</em>
            </span>
          )}
        </Link>
        {onToggleCollapse && (
          <Hint label={collapsed ? '展开侧栏' : '收起侧栏'}>
            <IconButton
              label={collapsed ? '展开侧栏' : '收起侧栏'}
              variant="ghost"
              className="collapse-button"
              onClick={onToggleCollapse}
            >
              <ChevronDown size={16} className={collapsed ? '-rotate-90' : 'rotate-90'} />
            </IconButton>
          </Hint>
        )}
      </div>

      <div className="workspace-switcher">
        <span className="workspace-dot" />
        {!collapsed && (
          <>
            <span className="workspace-copy">
              <small>访问范围</small>
              <strong>{inAdmin ? '系统管理空间' : '个人研究空间'}</strong>
            </span>
            <LockKeyhole size={14} aria-hidden="true" />
          </>
        )}
      </div>

      <Button
        variant="soft"
        className="new-research-button"
        onClick={() => {
          navigate('/')
          onNavigate?.()
        }}
      >
        <Plus size={16} />
        {!collapsed && '开始新研究'}
      </Button>

      <nav className="primary-nav" aria-label="主导航">
        {(inAdmin ? adminNav : userNav).map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            onClick={onNavigate}
            className={({ isActive }) => cn('nav-link', isActive && 'nav-link-active')}
          >
            <Icon size={17} strokeWidth={1.8} />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        ))}
        {isAdmin && !inAdmin && (
          <NavLink to="/admin/overview" onClick={onNavigate} className="nav-link nav-link-admin">
            <ShieldCheck size={17} strokeWidth={1.8} />
            {!collapsed && <span>管理后台</span>}
          </NavLink>
        )}
        {inAdmin && (
          <NavLink to="/" onClick={onNavigate} className="nav-link nav-link-admin">
            <BookOpen size={17} strokeWidth={1.8} />
            {!collapsed && <span>返回研究空间</span>}
          </NavLink>
        )}
      </nav>

      {!collapsed && (
        <>
          <div className="sidebar-section-heading">
            <span>研究项目</span>
            <Hint label="搜索项目">
              <Command size={13} />
            </Hint>
          </div>
          <div className="project-search-wrap">
            <Command size={13} />
            <input
              value={projectSearch}
              onChange={(event) => setProjectSearch(event.target.value)}
              placeholder="搜索项目"
              aria-label="搜索项目"
            />
          </div>
        </>
      )}
      <div className="project-list" aria-label="最近项目">
        {filteredProjects.map((project) => (
          <NavLink
            key={project.id}
            to={`/projects/${project.id}`}
            onClick={onNavigate}
            className={cn(
              'project-nav-item',
              location.pathname === `/projects/${project.id}` && 'project-nav-item-active',
            )}
          >
            <span className={`project-status-dot dot-${statusTone(project.status)}`} />
            {!collapsed && (
              <span className="project-nav-copy">
                <strong>{project.name || project.query}</strong>
                <small>{formatDate(project.created_at)}</small>
              </span>
            )}
          </NavLink>
        ))}
        {!collapsed && !filteredProjects.length && <span className="sidebar-empty">还没有研究项目</span>}
      </div>

      <div className="sidebar-spacer" />
      {!collapsed && (
        <div className="sidebar-footer-card">
          <BookOpen size={17} />
          <div>
            <strong>研究工作台</strong>
            <span>可追溯的多智能体流程</span>
          </div>
        </div>
      )}
      <Divider />
      <div className="sidebar-user-row">
        <Avatar name={user?.full_name || user?.email} size="sm" />
        {!collapsed && (
          <span className="sidebar-user-copy">
            <strong>{user?.full_name || '研究者'}</strong>
            <small>{user?.email}</small>
          </span>
        )}
        {!collapsed && (
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <IconButton label="打开账户菜单" variant="ghost">
                <ChevronDown size={14} />
              </IconButton>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content className="dropdown-content" sideOffset={8} align="end">
                <DropdownMenu.Item className="dropdown-item" onSelect={() => navigate('/console/profile')}>
                  <UserRound size={15} />
                  个人资料
                </DropdownMenu.Item>
                <DropdownMenu.Item className="dropdown-item" onSelect={onToggleTheme}>
                  {dark ? <Sun size={15} /> : <Moon size={15} />}
                  {dark ? '浅色模式' : '深色模式'}
                </DropdownMenu.Item>
                <DropdownMenu.Separator className="dropdown-separator" />
                <DropdownMenu.Item className="dropdown-item danger-item" onSelect={() => void signOut()}>
                  <LogOut size={15} />
                  退出登录
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        )}
      </div>
    </div>
  )
}

export function AppShell({ children }: { children?: ReactNode }) {
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [dark, setDark] = useState(() => localStorage.getItem('theme') === 'dark')
  const { user } = useAuth()
  const { data } = useQuery({
    queryKey: ['projects', 'shell'],
    queryFn: () => projectsApi.list(0, 50),
    staleTime: 30_000,
  })

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }, [dark])

  const sidebarProps = {
    projects: data?.projects ?? [],
    collapsed,
    onToggleTheme: () => setDark((value) => !value),
    dark,
  }
  return (
    <TooltipProvider>
      <div className="app-shell">
        <aside className={cn('desktop-sidebar', collapsed && 'desktop-sidebar-collapsed')}>
          <SidebarContent
            {...sidebarProps}
            onNavigate={() => undefined}
            onToggleCollapse={() => setCollapsed((value) => !value)}
          />
        </aside>
        <Dialog.Root open={mobileOpen} onOpenChange={setMobileOpen}>
          <Dialog.Portal>
            <Dialog.Overlay className="dialog-overlay" />
            <Dialog.Content className="mobile-sidebar-dialog">
              <Dialog.Title className="sr-only">主导航</Dialog.Title>
              <SidebarContent {...sidebarProps} collapsed={false} onNavigate={() => setMobileOpen(false)} />
              <Dialog.Close asChild>
                <IconButton label="关闭导航" variant="ghost" className="mobile-close">
                  <X size={18} />
                </IconButton>
              </Dialog.Close>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
        <div className="app-main">
          <header className="mobile-topbar">
            <IconButton label="打开导航" variant="ghost" onClick={() => setMobileOpen(true)}>
              <Menu size={19} />
            </IconButton>
            <Link to="/" className="mobile-brand">
              Academic Cluster
            </Link>
            <div className="mobile-topbar-spacer" />
            <Hint label="账户设置">
              <Link to="/console/profile" className="mobile-avatar-link">
                <Avatar name={user?.full_name || user?.email} size="sm" />
              </Link>
            </Hint>
          </header>
          <AnimatePresence mode="wait">
            <motion.main
              className="route-surface"
              initial={{ opacity: 0, y: 7 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.22, ease: 'easeOut' }}
              key={location.pathname}
            >
              {children || <Outlet />}
            </motion.main>
          </AnimatePresence>
        </div>
      </div>
    </TooltipProvider>
  )
}
