import { onUnmounted, shallowRef } from 'vue'

export type SSEPayload = Record<string, unknown>

type DynamicValue<T> = T | (() => T)

export interface SSEReconnectOptions {
  maxAttempts?: number
  baseDelayMs?: number
  maxDelayMs?: number
}

export interface SSEOptions {
  /** Full SSE endpoint URL. It can be resolved lazily for dynamic project IDs. */
  url: DynamicValue<string>
  /** Bearer token sent in an Authorization header. */
  token?: DynamicValue<string | undefined>
  onConnected?: () => void
  onProgress?: (data: SSEPayload) => void
  onComplete?: (data: SSEPayload) => void
  onError?: (data: SSEPayload) => void
  onTransportError?: () => void
  /** Reconnect transient transport failures with bounded exponential backoff. */
  reconnect?: false | SSEReconnectOptions
}

interface ParsedEvent {
  type: string
  data: string
}

function resolveValue<T>(value: DynamicValue<T>): T {
  return typeof value === 'function' ? (value as () => T)() : value
}

function parsePayload(data: string): SSEPayload | null {
  try {
    const parsed: unknown = JSON.parse(data)
    return parsed && typeof parsed === 'object' ? parsed as SSEPayload : null
  }
  catch {
    return null
  }
}

function parseEventBlock(block: string): ParsedEvent | null {
  let type = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue
    const separator = line.indexOf(':')
    const field = separator === -1 ? line : line.slice(0, separator)
    const value = separator === -1 ? '' : line.slice(separator + 1).replace(/^ /, '')
    if (field === 'event') type = value
    if (field === 'data') data.push(value)
  }
  return data.length > 0 ? { type, data: data.join('\n') } : null
}

/** Manage one authenticated Server-Sent Events connection without URL secrets. */
export function useSSE(options: SSEOptions) {
  const isConnected = shallowRef(false)
  let activeController: AbortController | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let connectionGeneration = 0
  let reconnectAttempts = 0
  let wantsConnection = false

  const reconnectOptions = options.reconnect === false
    ? null
    : {
        maxAttempts: Math.max(0, options.reconnect?.maxAttempts ?? 3),
        baseDelayMs: Math.max(0, options.reconnect?.baseDelayMs ?? 1000),
        maxDelayMs: Math.max(0, options.reconnect?.maxDelayMs ?? 8000),
      }

  function isActive(controller: AbortController, generation: number): boolean {
    return wantsConnection
      && connectionGeneration === generation
      && activeController === controller
      && !controller.signal.aborted
  }

  function dispatch(event: ParsedEvent, controller: AbortController, generation: number) {
    if (!isActive(controller, generation)) return
    const data = parsePayload(event.data)
    if (event.type === 'connected') {
      isConnected.value = true
      options.onConnected?.()
    }
    else if (event.type === 'progress' && data) {
      options.onProgress?.(data)
    }
    else if (event.type === 'complete') {
      options.onComplete?.(data ?? {})
    }
    else if (event.type === 'error' && data) {
      options.onError?.(data)
    }
  }

  function scheduleReconnect(generation: number) {
    if (
      !reconnectOptions
      || !wantsConnection
      || connectionGeneration !== generation
      || reconnectAttempts >= reconnectOptions.maxAttempts
    ) {
      wantsConnection = false
      return
    }

    const delay = Math.min(
      reconnectOptions.maxDelayMs,
      reconnectOptions.baseDelayMs * (2 ** reconnectAttempts),
    )
    reconnectAttempts += 1
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      if (wantsConnection && connectionGeneration === generation) open(generation)
    }, delay)
  }

  async function consume(
    url: string,
    token: string | undefined,
    controller: AbortController,
    generation: number,
  ) {
    try {
      const headers = new Headers({ Accept: 'text/event-stream' })
      if (token) headers.set('Authorization', `Bearer ${token}`)
      const response = await fetch(url, {
        method: 'GET',
        headers,
        signal: controller.signal,
        credentials: 'same-origin',
        cache: 'no-store',
      })
      if (!isActive(controller, generation)) return
      if (!response.ok) throw new Error(`SSE request failed with ${response.status}`)
      if (!response.body) throw new Error('SSE response has no readable body')

      const reader = response.body.getReader()
      const cancelReader = () => {
        void reader.cancel().catch(() => undefined)
      }
      controller.signal.addEventListener('abort', cancelReader, { once: true })
      const decoder = new TextDecoder()
      let buffer = ''
      try {
        while (isActive(controller, generation)) {
          const { done, value } = await reader.read()
          if (!isActive(controller, generation)) return
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          buffer = buffer.replace(/\r\n/g, '\n')
          let boundary = buffer.indexOf('\n\n')
          while (boundary !== -1) {
            if (!isActive(controller, generation)) return
            const event = parseEventBlock(buffer.slice(0, boundary))
            buffer = buffer.slice(boundary + 2)
            if (event) dispatch(event, controller, generation)
            boundary = buffer.indexOf('\n\n')
          }
        }
        if (!isActive(controller, generation)) return
        buffer += decoder.decode()
        const finalEvent = parseEventBlock(buffer.replace(/\r\n/g, '\n'))
        if (finalEvent) dispatch(finalEvent, controller, generation)
      } finally {
        controller.signal.removeEventListener('abort', cancelReader)
        try {
          reader.releaseLock()
        } catch {
          // The reader can already be released by an aborted fetch implementation.
        }
      }
    }
    catch (error) {
      if (isActive(controller, generation)) {
        console.warn('SSE transport failed', error)
      }
    }
    finally {
      if (activeController === controller && connectionGeneration === generation) {
        activeController = null
        isConnected.value = false
        if (!controller.signal.aborted && wantsConnection) {
          options.onTransportError?.()
          scheduleReconnect(generation)
        }
      }
    }
  }

  function open(generation: number) {
    if (!wantsConnection || connectionGeneration !== generation || activeController) return
    const controller = new AbortController()
    activeController = controller
    const url = resolveValue(options.url)
    const token = options.token === undefined ? undefined : resolveValue(options.token)
    void consume(url, token, controller, generation)
  }

  function connect() {
    if (wantsConnection || activeController || reconnectTimer) return
    wantsConnection = true
    reconnectAttempts = 0
    const generation = ++connectionGeneration
    open(generation)
  }

  function disconnect() {
    wantsConnection = false
    connectionGeneration += 1
    reconnectAttempts = 0
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectTimer = null
    const controller = activeController
    activeController = null
    controller?.abort()
    isConnected.value = false
  }

  onUnmounted(disconnect)

  return { isConnected, connect, disconnect }
}
