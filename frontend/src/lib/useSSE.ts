import { useEffect, useRef } from 'react'
import { accessToken, apiBaseUrl, refreshAccessToken } from './api'

export interface StreamEvent {
  type: 'connected' | 'progress' | 'error' | 'complete' | string
  data: Record<string, unknown>
}

interface UseSSEOptions {
  projectId?: string | null
  enabled?: boolean
  onEvent: (event: StreamEvent) => void
  onTransportError?: (error: Error) => void
}

class SSEHttpError extends Error {
  constructor(readonly status: number) {
    super(`SSE connection failed (${status})`)
    this.name = 'SSEHttpError'
  }
}

export function parseSSEBlock(block: string): StreamEvent | null {
  let type = 'message'
  const dataLines: string[] = []
  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue
    if (line.startsWith('event:')) type = line.slice(6).trim()
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }
  if (!dataLines.length) return null
  const rawData = dataLines.join('\n')
  try {
    const parsed = JSON.parse(rawData) as unknown
    const data =
      parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : { value: parsed }
    return { type, data }
  } catch {
    return { type, data: { message: rawData } }
  }
}

function nextBlock(buffer: string) {
  const boundary = /\r?\n\r?\n/.exec(buffer)
  if (!boundary || boundary.index === undefined) return null
  return {
    block: buffer.slice(0, boundary.index),
    rest: buffer.slice(boundary.index + boundary[0].length),
  }
}

function abortableDelay(delayMs: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    if (signal.aborted) return resolve()
    const timeout = window.setTimeout(done, delayMs)
    signal.addEventListener('abort', done, { once: true })
    function done() {
      window.clearTimeout(timeout)
      signal.removeEventListener('abort', done)
      resolve()
    }
  })
}

export function useSSE({ projectId, enabled = true, onEvent, onTransportError }: UseSSEOptions) {
  const eventCallback = useRef(onEvent)
  const errorCallback = useRef(onTransportError)

  useEffect(() => {
    eventCallback.current = onEvent
    errorCallback.current = onTransportError
  }, [onEvent, onTransportError])

  useEffect(() => {
    if (!enabled || !projectId) return

    const controller = new AbortController()
    let current = true
    let retryAttempt = 0

    const emit = (event: StreamEvent) => {
      if (!current || controller.signal.aborted) return
      if (event.type === 'connected') retryAttempt = 0
      eventCallback.current(event)
    }

    async function readStream(token: string): Promise<'terminal' | 'closed'> {
      const response = await fetch(`${apiBaseUrl()}/stream/${projectId}`, {
        headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' },
        cache: 'no-store',
        signal: controller.signal,
      })
      if (!response.ok || !response.body) throw new SSEHttpError(response.status)

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let terminal = false

      const processEvent = (event: StreamEvent | null) => {
        if (!event) return
        emit(event)
        if (event.type === 'complete' || event.type === 'error') terminal = true
      }

      while (current && !controller.signal.aborted && !terminal) {
        const { done, value } = await reader.read()
        buffer += decoder.decode(value, { stream: !done })
        let chunk = nextBlock(buffer)
        while (chunk) {
          buffer = chunk.rest
          processEvent(parseSSEBlock(chunk.block))
          if (terminal) break
          chunk = nextBlock(buffer)
        }
        if (done) {
          const tail = buffer.trim()
          if (tail) processEvent(parseSSEBlock(tail))
          break
        }
      }

      if (terminal) {
        await reader.cancel().catch(() => undefined)
        return 'terminal'
      }
      return 'closed'
    }

    async function connect() {
      let token = accessToken()
      if (!token) return

      while (current && !controller.signal.aborted) {
        try {
          const result = await readStream(token)
          if (result === 'terminal' || !current) return
          throw new Error('SSE connection closed before a terminal event')
        } catch (error) {
          if (!current || controller.signal.aborted) return

          if (error instanceof SSEHttpError && error.status === 401) {
            try {
              token = await refreshAccessToken()
              continue
            } catch (refreshError) {
              errorCallback.current?.(
                refreshError instanceof Error ? refreshError : new Error('Session refresh failed'),
              )
              return
            }
          }

          const transportError = error instanceof Error ? error : new Error('SSE transport error')
          errorCallback.current?.(transportError)
          if (error instanceof SSEHttpError && [403, 404].includes(error.status)) return

          retryAttempt += 1
          const retryDelay = Math.min(10_000, 750 * 2 ** Math.min(retryAttempt - 1, 4))
          await abortableDelay(retryDelay, controller.signal)
          token = accessToken() || token
        }
      }
    }

    void connect()
    return () => {
      current = false
      controller.abort()
    }
  }, [enabled, projectId])
}
