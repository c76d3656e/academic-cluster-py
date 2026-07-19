import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AppShell } from './AppShell'

vi.mock('../lib/api', () => ({
  projectsApi: {
    list: vi.fn().mockResolvedValue({ projects: [], total: 0 }),
  },
}))

vi.mock('../lib/auth', () => ({
  useAuth: () => ({
    user: { id: 'admin-1', email: 'admin@example.org', full_name: 'Admin', role: 'admin', is_active: true },
    isAdmin: true,
    logout: vi.fn().mockResolvedValue(undefined),
  }),
}))

describe('AppShell administrator navigation', () => {
  it('exposes every management route while the administrator is in the admin workspace', () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/admin/users']}>
          <AppShell>
            <div>Admin content</div>
          </AppShell>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(screen.getByRole('link', { name: '用户与权限' })).toHaveAttribute('href', '/admin/users')
    expect(screen.getByRole('link', { name: 'Provider' })).toHaveAttribute('href', '/admin/providers')
    expect(screen.getByRole('link', { name: '全局项目' })).toHaveAttribute('href', '/admin/projects')
    expect(screen.getByRole('link', { name: '全局用量' })).toHaveAttribute('href', '/admin/usage')
    expect(screen.getByRole('link', { name: '审计日志' })).toHaveAttribute('href', '/admin/audit')
    expect(screen.getByRole('link', { name: '运行配置' })).toHaveAttribute('href', '/admin/pipeline-config')
    expect(screen.getByRole('link', { name: '返回研究空间' })).toHaveAttribute('href', '/')
  })
})
