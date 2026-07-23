import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AdminPage } from './AdminPage'

const apiMocks = vi.hoisted(() => ({
  users: vi.fn(),
  createUser: vi.fn(),
  changeRole: vi.fn(),
  toggleUser: vi.fn(),
  providers: vi.fn(),
  createProvider: vi.fn(),
  deleteProvider: vi.fn(),
  toggleProvider: vi.fn(),
  testProvider: vi.fn(),
  reloadProviders: vi.fn(),
  usageTrend: vi.fn(),
  providerUsage: vi.fn(),
  recentCalls: vi.fn(),
  audit: vi.fn(),
  pipelineConfig: vi.fn(),
  updatePipelineConfig: vi.fn(),
  resetPipelineConfig: vi.fn(),
  sources: vi.fn(),
  updateSource: vi.fn(),
  appendSource: vi.fn(),
  clearSource: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  adminApi: apiMocks,
  apiErrorMessage: () => 'request failed',
}))

vi.mock('../lib/auth', () => ({
  useAuth: () => ({ user: { id: 'admin-1', email: 'admin@example.org', role: 'admin', is_active: true } }),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

describe('AdminPage user management', () => {
  it('creates a user with the backend AdminCreateUserRequest contract', async () => {
    apiMocks.users.mockResolvedValue({ users: [], total: 0 })
    apiMocks.createUser.mockResolvedValue({ id: 'user-2', email: 'ada@example.org', role: 'admin', is_active: true })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const user = userEvent.setup()

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/admin/users']}>
          <Routes>
            <Route path="/admin/:section" element={<AdminPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await user.click(screen.getByRole('button', { name: '创建用户' }))
    await user.type(screen.getByLabelText('邮箱'), 'ada@example.org')
    await user.type(screen.getByLabelText('显示名称'), 'Ada Lovelace')
    await user.selectOptions(screen.getByLabelText('角色'), 'admin')
    await user.type(screen.getByLabelText('初始密码'), 'correct-horse')
    await user.type(screen.getByLabelText('确认密码'), 'correct-horse')
    await user.click(screen.getByRole('button', { name: '创建用户' }))

    await waitFor(() =>
      expect(apiMocks.createUser).toHaveBeenCalledWith({
        email: 'ada@example.org',
        password: 'correct-horse',
        full_name: 'Ada Lovelace',
        role: 'admin',
      }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('deletes a provider after explicit confirmation', async () => {
    apiMocks.providers.mockResolvedValue({
      providers: [
        {
          id: 'provider-1',
          kind: 'llm',
          display_name: 'Local Qwen',
          base_url: 'http://localhost:11434/v1',
          model: 'qwen',
          is_enabled: true,
          priority: 1,
          rpm_limit: 10,
          health_status: 'healthy',
          failure_count: 0,
        },
      ],
      total: 1,
    })
    apiMocks.deleteProvider.mockResolvedValue({ id: 'provider-1', display_name: 'Local Qwen', reloaded: 0 })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const user = userEvent.setup()

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/admin/providers']}>
          <Routes>
            <Route path="/admin/:section" element={<AdminPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await user.click(await screen.findByRole('button', { name: '删除 Local Qwen' }))
    expect(screen.getByText(/已有调用记录不会被删除/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '删除 Provider' }))
    await waitFor(() => expect(apiMocks.deleteProvider).toHaveBeenCalledWith('provider-1'))
  })

  it('creates a rerank provider through the registry contract', async () => {
    apiMocks.providers.mockResolvedValue({ providers: [], total: 0 })
    apiMocks.createProvider.mockResolvedValue({
      id: 'rerank-1',
      kind: 'rerank',
      display_name: 'Academic Reranker',
      base_url: 'https://rerank.example/v1/rerank',
      model: 'rerank-model',
      is_enabled: true,
      priority: 100,
      rpm_limit: 20,
      health_status: 'unknown',
      failure_count: 0,
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const user = userEvent.setup()

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/admin/providers']}>
          <Routes>
            <Route path="/admin/:section" element={<AdminPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await user.click(await screen.findByRole('button', { name: '新增 Provider' }))
    await user.selectOptions(screen.getByLabelText('类型'), 'rerank')
    await user.type(screen.getByLabelText('名称'), 'Academic Reranker')
    await user.type(screen.getByLabelText('Base URL'), 'https://rerank.example/v1/rerank')
    await user.type(screen.getByLabelText('模型'), 'rerank-model')
    const rpm = screen.getByLabelText('RPM')
    await user.clear(rpm)
    await user.type(rpm, '20')
    await user.click(screen.getByRole('button', { name: '保存 Provider' }))

    await waitFor(() =>
      expect(apiMocks.createProvider).toHaveBeenCalledWith({
        kind: 'rerank',
        display_name: 'Academic Reranker',
        base_url: 'https://rerank.example/v1/rerank',
        model: 'rerank-model',
        api_key: '',
        rpm_limit: 20,
        is_enabled: true,
      }),
    )
  })

  it('renders choice policies and resets the runtime configuration', async () => {
    apiMocks.pipelineConfig.mockResolvedValue([
      {
        key: 'rerank.failure_mode',
        value: 'passthrough',
        label: 'Rerank 失败语义',
        description: 'Failure semantics',
        group: 'Rerank',
        type: 'choice',
        options: ['passthrough', 'fail'],
      },
    ])
    apiMocks.resetPipelineConfig.mockResolvedValue({ message: 'reset' })
    apiMocks.updatePipelineConfig.mockResolvedValue({ key: 'rerank.failure_mode', value: 'fail' })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const user = userEvent.setup()

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/admin/pipeline-config']}>
          <Routes>
            <Route path="/admin/:section" element={<AdminPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await user.selectOptions(await screen.findByLabelText('Rerank 失败语义'), 'fail')
    await waitFor(() =>
      expect(apiMocks.updatePipelineConfig).toHaveBeenCalledWith('rerank.failure_mode', 'fail'),
    )
    await user.click(screen.getByRole('button', { name: '恢复默认值' }))
    await waitFor(() => expect(apiMocks.resetPipelineConfig).toHaveBeenCalled())
  })

  it('shows academic source requirements and appends a Semantic Scholar key', async () => {
    apiMocks.sources.mockResolvedValue({
      sources: [
        {
          key: 'semantic_scholar',
          label: 'Semantic Scholar',
          description: 'Metadata search',
          authentication: 'Optional API Key',
          rate_limit_hint: '1 req/s',
          configuration_keys: ['semantic_scholar_api_key'],
        },
        {
          key: 'arxiv',
          label: 'arXiv',
          description: 'Preprints',
          authentication: 'No authentication',
          rate_limit_hint: '1 req / 3 seconds',
          configuration_keys: [],
        },
      ],
      configs: [
        {
          key: 'semantic_scholar_api_key',
          label: 'Semantic Scholar API Key',
          description: 'Supports multiple keys',
          is_set: true,
          is_enabled: true,
          key_count: 2,
          value_source: 'db',
          is_secret: true,
          supports_multiple: true,
        },
      ],
    })
    apiMocks.appendSource.mockResolvedValue({})
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const user = userEvent.setup()

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/admin/sources']}>
          <Routes>
            <Route path="/admin/:section" element={<AdminPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('Semantic Scholar')).toBeInTheDocument()
    expect(screen.getByText('arXiv')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Semantic Scholar API Key'), 'new-key')
    await user.click(screen.getByRole('button', { name: '追加' }))
    await waitFor(() => expect(apiMocks.appendSource).toHaveBeenCalledWith('semantic_scholar_api_key', 'new-key'))
  })

  it('shows both LLM and embedding calls in the global usage details', async () => {
    apiMocks.usageTrend.mockResolvedValue([])
    apiMocks.providerUsage.mockResolvedValue([])
    apiMocks.recentCalls.mockResolvedValue([
      {
        id: 'call-llm',
        call_type: 'llm',
        user_email: 'writer@example.org',
        project_name: 'Review A',
        provider_name: 'OpenAI',
        model_name: 'gpt-test',
        total_tokens: 120,
        latency_ms: 80,
        cost: 0.01,
        status: 'completed',
      },
      {
        id: 'call-embedding',
        call_type: 'embedding',
        user_email: 'reader@example.org',
        project_name: 'Review B',
        provider_name: 'Embedding API',
        model_name: 'embed-test',
        total_tokens: 40,
        latency_ms: 20,
        cost: 0.001,
        status: 'completed',
      },
    ])
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const user = userEvent.setup()
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/admin/usage']}>
          <Routes>
            <Route path="/admin/:section" element={<AdminPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => expect(container.querySelector('.admin-call-table')).not.toBeNull())
    const table = container.querySelector('.admin-call-table')
    expect(within(table as HTMLElement).getByText('writer@example.org')).toBeInTheDocument()
    expect(within(table as HTMLElement).getByText('reader@example.org')).toBeInTheDocument()
    expect(within(table as HTMLElement).getByText('llm')).toBeInTheDocument()
    expect(within(table as HTMLElement).getByText('embedding')).toBeInTheDocument()
    expect(apiMocks.recentCalls).toHaveBeenCalledWith({ limit: 100, skip: 0, call_type: undefined })
    await user.click(screen.getByRole('button', { name: 'embedding' }))
    await waitFor(() =>
      expect(apiMocks.recentCalls).toHaveBeenLastCalledWith({ limit: 100, skip: 0, call_type: 'embedding' }),
    )
  })

  it('uses the user email as the primary audit identity', async () => {
    apiMocks.audit.mockResolvedValue({
      logs: [
        {
          id: 'audit-1',
          user_id: 'user-uuid',
          user_email: 'operator@example.org',
          action: 'provider.delete',
          resource_type: 'provider',
          resource_id: 'provider-1',
          details: {},
          created_at: '2026-07-18T12:00:00Z',
        },
      ],
      total: 1,
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/admin/audit']}>
          <Routes>
            <Route path="/admin/:section" element={<AdminPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('operator@example.org')).toBeInTheDocument()
    expect(screen.getByText('user-uuid')).toBeInTheDocument()
  })
})
