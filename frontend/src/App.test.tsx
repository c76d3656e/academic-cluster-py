import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { useAuth } from './lib/auth'

vi.mock('./lib/auth', () => ({ useAuth: vi.fn() }))
vi.mock('./components/AppShell', () => ({ AppShell: ({ children }: { children: React.ReactNode }) => children }))
vi.mock('./pages/AuthPage', () => ({ AuthPage: () => <div>登录页面</div> }))
vi.mock('./pages/ChatPage', () => ({ ChatPage: () => <div>研究页面</div> }))
vi.mock('./pages/ProjectPage', () => ({ ProjectPage: () => <div>项目页面</div> }))
vi.mock('./pages/ConsolePage', () => ({ ConsolePage: () => <div>控制台页面</div> }))
vi.mock('./pages/AdminPage', () => ({ AdminPage: () => <div>管理页面</div> }))

function renderRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

const baseAuth: ReturnType<typeof useAuth> = {
  user: null,
  loading: false,
  isAuthenticated: false,
  isAdmin: false,
  login: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
  refreshUser: vi.fn(),
}

describe('application authorization routes', () => {
  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue(baseAuth)
  })

  it('redirects unauthenticated visitors to login', async () => {
    renderRoute('/admin/users')
    expect(await screen.findByText('登录页面')).toBeInTheDocument()
  })

  it('redirects a regular user away from admin routes', async () => {
    vi.mocked(useAuth).mockReturnValue({
      ...baseAuth,
      user: { id: 'user-1', email: 'user@example.org', role: 'user', is_active: true },
      isAuthenticated: true,
      isAdmin: false,
    })
    renderRoute('/admin/users')
    expect(await screen.findByText('研究页面')).toBeInTheDocument()
  })

  it('allows administrators to open admin routes', async () => {
    vi.mocked(useAuth).mockReturnValue({
      ...baseAuth,
      user: { id: 'admin-1', email: 'admin@example.org', role: 'admin', is_active: true },
      isAuthenticated: true,
      isAdmin: true,
    })
    renderRoute('/admin/users')
    expect(await screen.findByText('管理页面')).toBeInTheDocument()
  })
})
