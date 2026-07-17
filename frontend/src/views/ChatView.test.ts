import type { Ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('vue', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue')>()
  return {
    ...actual,
    onMounted: vi.fn(),
    onUnmounted: vi.fn(),
    useSSRContext: () => ({ modules: new Set<string>() }),
  }
})

const projectMocks = vi.hoisted(() => ({
  createProject: vi.fn(),
  getProjectStatus: vi.fn(),
  listProjects: vi.fn().mockResolvedValue({ projects: [], total: 0 }),
  startPipeline: vi.fn().mockResolvedValue({
    message: 'accepted',
    project_id: 'project',
    execution_id: 'execution',
  }),
}))

const streamHarness = vi.hoisted(() => ({
  connect: vi.fn(),
  disconnect: vi.fn(),
}))

const pollingHarness = vi.hoisted(() => ({
  callback: null as null | ((context: {
    signal: AbortSignal
    isCurrent: () => boolean
  }) => void | Promise<void>),
  start: vi.fn(),
  stop: vi.fn(),
}))

vi.mock('@/api/projects', () => ({ projectsApi: projectMocks }))
vi.mock('@/composables/useAuth', () => ({
  useAuth: () => ({ user: { value: null }, logout: vi.fn() }),
}))
vi.mock('@/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@/composables/useSSE', () => ({
  useSSE: () => ({
    connect: streamHarness.connect,
    disconnect: streamHarness.disconnect,
  }),
}))
vi.mock('@/composables/usePolling', () => ({
  usePolling: (callback: typeof pollingHarness.callback) => {
    pollingHarness.callback = callback
    return { start: pollingHarness.start, stop: pollingHarness.stop }
  },
}))

import ChatView from './ChatView.vue'

interface ChatBindings {
  currentProjectId: Ref<string | null>
  handleSubmit: () => Promise<void>
  input: Ref<string>
  isProcessing: Ref<boolean>
  messages: Ref<Array<{ content: string; role: string }>>
  startNewChat: () => void
}

function setupChat(): ChatBindings {
  const component = ChatView as unknown as {
    setup: (_props: Record<string, never>, context: { expose: () => void }) => ChatBindings
  }
  return component.setup({}, { expose: vi.fn() })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function project(id: string) {
  return { id, name: id, query: id, status: 'pending' as const }
}

describe('ChatView pipeline session isolation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    projectMocks.listProjects.mockResolvedValue({ projects: [], total: 0 })
    projectMocks.startPipeline.mockResolvedValue({
      message: 'accepted',
      project_id: 'project',
      execution_id: 'execution',
    })
    pollingHarness.callback = null
  })

  it('does not let an abandoned create request take over a newer chat', async () => {
    const abandoned = deferred<ReturnType<typeof project>>()
    const current = deferred<ReturnType<typeof project>>()
    projectMocks.createProject
      .mockReturnValueOnce(abandoned.promise)
      .mockReturnValueOnce(current.promise)
    const chat = setupChat()

    chat.input.value = 'abandoned topic'
    const abandonedSubmit = chat.handleSubmit()
    chat.startNewChat()
    chat.input.value = 'current topic'
    const currentSubmit = chat.handleSubmit()

    current.resolve(project('project-current'))
    await vi.waitFor(() => expect(projectMocks.startPipeline).toHaveBeenCalledOnce())
    await currentSubmit
    abandoned.resolve(project('project-abandoned'))
    await abandonedSubmit

    expect(projectMocks.startPipeline).toHaveBeenCalledWith('project-current')
    expect(chat.currentProjectId.value).toBe('project-current')
    expect(chat.messages.value.some(message => message.content === 'abandoned topic')).toBe(false)
    expect(streamHarness.connect).toHaveBeenCalledOnce()
  })

  it('drops a terminal status response from the previous chat session', async () => {
    projectMocks.createProject
      .mockResolvedValueOnce(project('project-old'))
      .mockResolvedValueOnce(project('project-current'))
    const oldStatus = deferred<{
      project_id: string
      execution_id: string
      status: 'completed'
      current_phase: null
    }>()
    projectMocks.getProjectStatus.mockReturnValueOnce(oldStatus.promise)
    const chat = setupChat()

    chat.input.value = 'old topic'
    await chat.handleSubmit()
    const oldPoll = pollingHarness.callback?.({
      signal: new AbortController().signal,
      isCurrent: () => true,
    })

    chat.startNewChat()
    chat.input.value = 'current topic'
    await chat.handleSubmit()
    oldStatus.resolve({
      project_id: 'project-old',
      execution_id: 'execution-old',
      status: 'completed',
      current_phase: null,
    })
    await oldPoll

    expect(chat.currentProjectId.value).toBe('project-current')
    expect(chat.isProcessing.value).toBe(true)
    expect(chat.messages.value.some(message => message.role === 'result')).toBe(false)
  })
})
