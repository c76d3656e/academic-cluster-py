import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '../components/ui'
import { ChatPage } from './ChatPage'

const projectMocks = vi.hoisted(() => ({
  create: vi.fn(),
  start: vi.fn(),
  status: vi.fn(),
  progress: vi.fn(),
  review: vi.fn(),
  sources: vi.fn(),
  pause: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  projectsApi: projectMocks,
  apiErrorMessage: () => 'request failed',
}))

vi.mock('../lib/auth', () => ({
  useAuth: () => ({ user: { id: 'user-1', email: 'user@example.org', role: 'user', is_active: true } }),
}))

vi.mock('../lib/useSSE', () => ({ useSSE: vi.fn() }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

describe('ChatPage pipeline startup', () => {
  it('refreshes status and progress without polling hidden audit logs', async () => {
    projectMocks.create.mockResolvedValue({ id: 'project-1', name: 'Test', query: 'Test', status: 'pending' })
    projectMocks.start.mockResolvedValue({ project_id: 'project-1', execution_id: 'execution-1', message: 'started' })
    projectMocks.status.mockResolvedValue({
      project_id: 'project-1',
      execution_id: 'execution-1',
      status: 'running',
      current_phase: 'supervisor',
    })
    projectMocks.progress.mockResolvedValue({ execution_id: 'execution-1', nodes: [] })
    projectMocks.sources.mockResolvedValue({ project_id: 'project-1', total: 0, sources: [] })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    const user = userEvent.setup()

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <TooltipProvider>
            <ChatPage />
          </TooltipProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await user.type(screen.getByLabelText('研究问题'), 'Trace a complete pipeline')
    await user.click(screen.getByRole('button', { name: '开始研究' }))

    await waitFor(() => expect(projectMocks.start).toHaveBeenCalledWith('project-1'))
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['project-status', 'project-1'] })
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['project-progress', 'project-1'] })
    })
  })

  it('expands the main workspace when the execution rail is hidden', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const user = userEvent.setup()

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <TooltipProvider>
            <ChatPage />
          </TooltipProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(container.querySelector('.chat-grid')).toHaveClass('chat-grid-with-rail')
    await user.click(within(container).getByRole('button', { name: '切换执行轨迹' }))
    expect(container.querySelector('.chat-grid')).toHaveClass('chat-grid-full')
    await waitFor(() => expect(container.querySelector('.chat-right-rail')).not.toBeInTheDocument())
  })
})
