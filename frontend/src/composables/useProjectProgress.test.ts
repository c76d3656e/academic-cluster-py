import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('vue', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue')>()
  return { ...actual, onUnmounted: vi.fn() }
})

const apiMocks = vi.hoisted(() => ({
  getProjectProgress: vi.fn(),
  getProjectStatus: vi.fn(),
}))

const sseHarness = vi.hoisted(() => ({
  connect: vi.fn(),
  disconnect: vi.fn(),
  options: null as null | {
    onComplete?: (data: Record<string, unknown>) => void
  },
}))

vi.mock('@/api/projects', () => ({
  projectsApi: apiMocks,
}))

vi.mock('./useSSE', () => ({
  useSSE: (options: typeof sseHarness.options) => {
    sseHarness.options = options
    return {
      connect: sseHarness.connect,
      disconnect: sseHarness.disconnect,
    }
  },
}))

import { useProjectProgress } from './useProjectProgress'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('useProjectProgress', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sseHarness.options = null
  })

  it('preserves checkpoint progress but resets it for a fresh execution id', async () => {
    apiMocks.getProjectProgress.mockResolvedValueOnce({
      execution_id: 'execution-old',
      nodes: [{
        node_name: 'research',
        status: 'completed',
        started_at: '2026-07-17T10:00:00Z',
        finished_at: '2026-07-17T10:01:00Z',
        elapsed_ms: 60_000,
        error_message: null,
      }],
    })
    const progress = useProjectProgress('project-1')

    await progress.loadHistoricalProgress()
    expect(progress.executionId.value).toBe('execution-old')
    expect(progress.completedNodes.value.has('research')).toBe(true)
    expect(progress.progressLogs.value).toHaveLength(1)

    progress.beginExecution('execution-old')
    expect(progress.completedNodes.value.has('research')).toBe(true)
    expect(progress.progressLogs.value).toHaveLength(1)

    progress.beginExecution('execution-new')
    expect(progress.executionId.value).toBe('execution-new')
    expect(progress.completedNodes.value.size).toBe(0)
    expect(progress.progressLogs.value).toEqual([])
    expect(progress.currentProgressNode.value).toBe('')
  })

  it('ignores an older running response after a newer terminal response', async () => {
    const olderRunning = deferred<Record<string, unknown>>()
    const newerCompleted = deferred<Record<string, unknown>>()
    apiMocks.getProjectStatus
      .mockReturnValueOnce(olderRunning.promise)
      .mockReturnValueOnce(newerCompleted.promise)
    const onStatusChange = vi.fn()
    const onTerminal = vi.fn()
    const progress = useProjectProgress('project-1', { onStatusChange, onTerminal })

    progress.startStatusPolling()
    expect(apiMocks.getProjectStatus).toHaveBeenCalledTimes(1)
    sseHarness.options?.onComplete?.({})
    expect(apiMocks.getProjectStatus).toHaveBeenCalledTimes(2)

    newerCompleted.resolve({
      project_id: 'project-1',
      execution_id: 'execution-1',
      status: 'completed',
      current_phase: null,
    })
    await vi.waitFor(() => expect(onTerminal).toHaveBeenCalledOnce())

    olderRunning.resolve({
      project_id: 'project-1',
      execution_id: 'execution-1',
      status: 'running',
      current_phase: 'writing',
    })
    await Promise.resolve()
    await Promise.resolve()

    expect(onStatusChange).toHaveBeenCalledTimes(1)
    expect(onStatusChange).toHaveBeenCalledWith(expect.objectContaining({ status: 'completed' }))
    expect(progress.currentProgressNode.value).toBe('')
    expect(progress.completedNodes.value.size).toBe(6)
    progress.stopStatusPolling()
  })
})
