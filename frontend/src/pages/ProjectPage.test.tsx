import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ProjectPage } from './ProjectPage'

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  status: vi.fn(),
  progress: vi.fn(),
  review: vi.fn(),
  sources: vi.fn(),
  logs: vi.fn(),
  contracts: vi.fn(),
  calls: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  projectsApi: {
    get: apiMocks.get,
    status: apiMocks.status,
    progress: apiMocks.progress,
    review: apiMocks.review,
    sources: apiMocks.sources,
    logs: apiMocks.logs,
    contracts: apiMocks.contracts,
  },
  consoleApi: { calls: apiMocks.calls },
  getFeatures: vi.fn().mockResolvedValue({ show_usage: false }),
  apiErrorMessage: () => 'request failed',
}))

vi.mock('../lib/auth', () => ({
  useAuth: () => ({ isAdmin: false }),
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

describe('ProjectPage review presentation', () => {
  it('integrates linked citations and omits internal node contracts', async () => {
    apiMocks.get.mockResolvedValue({ id: 'project-1', name: 'Test project', query: 'Test query', status: 'completed' })
    apiMocks.status.mockResolvedValue({
      project_id: 'project-1',
      execution_id: 'execution-1',
      status: 'completed',
      current_phase: 'finalize',
    })
    apiMocks.progress.mockResolvedValue({ execution_id: 'execution-1', nodes: [] })
    apiMocks.review.mockResolvedValue({
      project_id: 'project-1',
      outline: { title: 'Review' },
      sections: [],
      evidence_cards: [
        {
          id: 'evidence-1',
          paper_id: 'paper-1',
          source_api: 'OpenAlex',
          title: 'Structured source',
          authors: '王伟, 李明',
          year: '2026',
          claim: '多注意力网络改善了结果。',
        },
      ],
      references: [
        {
          new_number: 1,
          original_number: 7,
          paper_id: 'paper-1',
          title: 'Structured source',
          authors: '王伟, 李明',
          year: '2026',
        },
      ],
      final_review: '# Review\n\n[1]提出了多注意力混合网络。\n\n## 参考文献\n\n[1] stale reference',
      abstract: null,
      status: 'completed',
    })
    apiMocks.sources.mockResolvedValue({ project_id: 'project-1', total: 0, sources: [] })
    apiMocks.calls.mockResolvedValue([])
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/projects/project-1']}>
          <Routes>
            <Route path="/projects/:id" element={<ProjectPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const citation = await screen.findByRole('link', { name: '查看参考文献 1' })
    expect(citation).toHaveAttribute('href', '#reference-1')
    const toc = screen.getByRole('navigation', { name: '文章目录' })
    expect(within(toc).getByRole('link', { name: '参考文献' })).toHaveAttribute('href', '#academic-bibliography-title')
    expect(screen.getAllByRole('heading', { name: 'Review' })).toHaveLength(1)
    expect(citation.closest('p')).toHaveTextContent('王伟[1]提出了多注意力混合网络。')
    const bibliography = screen.getByRole('list', { name: '参考文献' })
    expect(within(bibliography).getAllByRole('listitem')).toHaveLength(1)
    expect(screen.queryByText('stale reference')).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '节点契约' })).not.toBeInTheDocument()
    expect(apiMocks.logs).not.toHaveBeenCalled()
    expect(apiMocks.contracts).not.toHaveBeenCalled()

    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: '来源与证据' }))
    const ledger = document.querySelector('.paper-ledger')
    expect(ledger).not.toBeNull()
    expect(within(ledger as HTMLElement).getByText('Structured source')).toBeInTheDocument()
    expect(within(ledger as HTMLElement).getByText(/王伟, 李明/)).toBeInTheDocument()
  })
})
