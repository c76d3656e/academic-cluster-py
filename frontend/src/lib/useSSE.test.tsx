import { render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseSSEBlock, useSSE, type StreamEvent } from './useSSE'
import { accessToken, refreshAccessToken } from './api'

vi.mock('./api', () => ({
  accessToken: vi.fn(() => 'access-token'),
  apiBaseUrl: vi.fn(() => '/api'),
  refreshAccessToken: vi.fn(() => Promise.resolve('refreshed-token')),
}))

function streamResponse(chunks: string[], status = 200) {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
      controller.close()
    },
  })
  return new Response(body, {
    status,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

function Harness({ projectId, onEvent }: { projectId: string; onEvent: (event: StreamEvent) => void }) {
  useSSE({ projectId, onEvent })
  return null
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('parseSSEBlock', () => {
  it('parses named events, comments and multiline JSON data', () => {
    const event = parseSSEBlock(': heartbeat\nevent: progress\ndata: {"node":\ndata: "research"}')
    expect(event).toEqual({ type: 'progress', data: { node: 'research' } })
  })

  it('keeps non-JSON event data as a readable message', () => {
    expect(parseSSEBlock('event: error\ndata: upstream unavailable')).toEqual({
      type: 'error',
      data: { message: 'upstream unavailable' },
    })
  })
})

describe('useSSE', () => {
  it('flushes a terminal event when the stream closes without a final blank line', async () => {
    const onEvent = vi.fn()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          streamResponse([
            'event: connected\ndata: {"project_id":"project-1"}\n\n',
            'event: complete\ndata: {"status":"completed"}',
          ]),
        ),
    )

    render(<Harness projectId="project-1" onEvent={onEvent} />)

    await waitFor(() =>
      expect(onEvent).toHaveBeenCalledWith({
        type: 'complete',
        data: { status: 'completed' },
      }),
    )
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('rotates an expired access token before reconnecting', async () => {
    const onEvent = vi.fn()
    vi.mocked(accessToken).mockReturnValue('expired-token')
    vi.mocked(refreshAccessToken).mockResolvedValue('fresh-token')
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(streamResponse(['event: complete\ndata: {"ok":true}\n\n']))
    vi.stubGlobal('fetch', fetchMock)

    render(<Harness projectId="project-2" onEvent={onEvent} />)

    await waitFor(() => expect(onEvent).toHaveBeenCalledWith({ type: 'complete', data: { ok: true } }))
    expect(refreshAccessToken).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/stream/project-2',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer fresh-token' }),
      }),
    )
  })

  it('aborts the previous project stream when the project changes', async () => {
    const signals: AbortSignal[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) => {
        signals.push(init?.signal as AbortSignal)
        return new Promise<Response>(() => undefined)
      }),
    )

    const { rerender, unmount } = render(<Harness projectId="project-a" onEvent={vi.fn()} />)
    await waitFor(() => expect(signals).toHaveLength(1))
    rerender(<Harness projectId="project-b" onEvent={vi.fn()} />)
    await waitFor(() => expect(signals).toHaveLength(2))
    expect(signals[0].aborted).toBe(true)
    expect(signals[1].aborted).toBe(false)
    unmount()
    expect(signals[1].aborted).toBe(true)
  })
})
