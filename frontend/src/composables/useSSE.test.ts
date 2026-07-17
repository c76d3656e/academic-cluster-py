import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('vue', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue')>()
  return { ...actual, onUnmounted: vi.fn() }
})

import { useSSE } from './useSSE'

interface ControlledStream {
  response: Response
  emit: (event: string) => void
  fail: () => void
}

function controlledStream(): ControlledStream {
  let streamController: ReadableStreamDefaultController<Uint8Array>
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      streamController = controller
    },
  })
  return {
    response: new Response(stream, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }),
    emit(event: string) {
      streamController.enqueue(encoder.encode(event))
    },
    fail() {
      streamController.error(new Error('transport failed'))
    },
  }
}

describe('useSSE', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('resolves dynamic URLs and keeps bearer tokens out of the URL', async () => {
    let projectId = 'project-1'
    let token = 'token one'
    const first = controlledStream()
    const second = controlledStream()
    fetchMock.mockResolvedValueOnce(first.response).mockResolvedValueOnce(second.response)
    const stream = useSSE({
      url: () => `/api/stream/${projectId}`,
      token: () => token,
    })

    stream.connect()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const [firstUrl, firstInit] = fetchMock.mock.calls[0]
    expect(firstUrl).toBe('/api/stream/project-1')
    expect(new Headers(firstInit?.headers).get('Authorization')).toBe('Bearer token one')

    stream.disconnect()
    projectId = 'project-2'
    token = 'token two'
    stream.connect()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    const [secondUrl, secondInit] = fetchMock.mock.calls[1]
    expect(secondUrl).toBe('/api/stream/project-2')
    expect(new Headers(secondInit?.headers).get('Authorization')).toBe('Bearer token two')
    stream.disconnect()
  })

  it('parses progress and completion payloads while ignoring malformed data', async () => {
    const transport = controlledStream()
    fetchMock.mockResolvedValueOnce(transport.response)
    const onConnected = vi.fn()
    const onProgress = vi.fn()
    const onComplete = vi.fn()
    const stream = useSSE({
      url: '/api/stream/project-1',
      token: 'token',
      onConnected,
      onProgress,
      onComplete,
    })

    stream.connect()
    transport.emit('event: connected\ndata: {"project_id":"project-1"}\n\n')
    transport.emit('event: progress\ndata: {"node":"research","status":"running"}\n\n')
    transport.emit('event: progress\ndata: not-json\n\n')
    transport.emit('event: complete\ndata: {"status":"completed"}\n\n')

    await vi.waitFor(() => expect(onComplete).toHaveBeenCalledOnce())
    expect(onConnected).toHaveBeenCalledOnce()
    expect(onProgress).toHaveBeenCalledOnce()
    expect(onProgress).toHaveBeenCalledWith({ node: 'research', status: 'running' })
    expect(onComplete).toHaveBeenCalledWith({ status: 'completed' })
    stream.disconnect()
  })

  it('reports transport failures and resets connection state', async () => {
    const transport = controlledStream()
    fetchMock.mockResolvedValueOnce(transport.response)
    const onTransportError = vi.fn()
    const stream = useSSE({
      url: '/api/stream/project-1',
      onTransportError,
    })

    stream.connect()
    transport.emit('event: connected\ndata: {}\n\n')
    await vi.waitFor(() => expect(stream.isConnected.value).toBe(true))
    transport.fail()

    await vi.waitFor(() => expect(onTransportError).toHaveBeenCalledOnce())
    expect(stream.isConnected.value).toBe(false)
    stream.disconnect()
  })

  it('isolates a delayed response from a disconnected stream generation', async () => {
    let resolveFirst!: (response: Response) => void
    const firstResponse = new Promise<Response>((resolve) => {
      resolveFirst = resolve
    })
    const first = controlledStream()
    const second = controlledStream()
    fetchMock.mockReturnValueOnce(firstResponse).mockResolvedValueOnce(second.response)
    const onProgress = vi.fn()
    const stream = useSSE({
      url: '/api/stream/project-1',
      onProgress,
      reconnect: false,
    })

    stream.connect()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    stream.disconnect()
    stream.connect()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))

    resolveFirst(first.response)
    first.emit('event: progress\ndata: {"node":"research"}\n\n')
    second.emit('event: progress\ndata: {"node":"writing"}\n\n')

    await vi.waitFor(() => expect(onProgress).toHaveBeenCalledOnce())
    expect(onProgress).toHaveBeenCalledWith({ node: 'writing' })
    stream.disconnect()
  })

  it('reconnects with fresh dynamic credentials after a transport failure', async () => {
    vi.useFakeTimers()
    const replacement = controlledStream()
    fetchMock
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(replacement.response)
    let token = 'expired-token'
    const stream = useSSE({
      url: '/api/stream/project-1',
      token: () => token,
      reconnect: { maxAttempts: 2, baseDelayMs: 10, maxDelayMs: 20 },
    })

    stream.connect()
    await Promise.resolve()
    await Promise.resolve()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    token = 'fresh-token'
    await vi.advanceTimersByTimeAsync(10)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    const [, reconnectInit] = fetchMock.mock.calls[1]
    expect(new Headers(reconnectInit?.headers).get('Authorization')).toBe('Bearer fresh-token')
    stream.disconnect()
  })

  it('stops reconnecting after the configured attempt limit', async () => {
    vi.useFakeTimers()
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    fetchMock.mockRejectedValue(new Error('offline'))
    const onTransportError = vi.fn()
    const stream = useSSE({
      url: '/api/stream/project-1',
      onTransportError,
      reconnect: { maxAttempts: 2, baseDelayMs: 10, maxDelayMs: 20 },
    })

    stream.connect()
    await Promise.resolve()
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(10)
    await vi.advanceTimersByTimeAsync(20)
    await vi.advanceTimersByTimeAsync(1000)

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(onTransportError).toHaveBeenCalledTimes(3)
    stream.disconnect()
  })
})
