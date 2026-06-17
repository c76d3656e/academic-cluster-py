import { onUnmounted, shallowRef } from 'vue'

export interface SSEOptions {
  /** Full SSE endpoint URL (token will be appended automatically when provided) */
  url: string
  /** Bearer token – appended as ?token= query param */
  token?: string
  /** Fired when the "connected" event arrives */
  onConnected?: () => void
  /** Fired on each "progress" SSE event */
  onProgress?: (data: Record<string, unknown>) => void
  /** Fired when a pipeline node finishes */
  onNodeFinished?: (data: Record<string, unknown>) => void
  /** Fired when the "complete" event arrives */
  onComplete?: () => void
  /** Fired on SSE error events that carry data */
  onError?: (data: Record<string, unknown>) => void
}

/**
 * Composable that manages an SSE (Server-Sent Events) connection.
 *
 * Usage:
 * ```ts
 * const { isConnected, connect, disconnect } = useSSE({
 *   url: `${baseUrl}/stream/${id}`,
 *   token: localStorage.getItem('access_token') ?? undefined,
 *   onProgress(data) { /* ... *\/ },
 *   onComplete()  { /* ... *\/ },
 * })
 * ```
 */
export function useSSE(options: SSEOptions) {
  const isConnected = shallowRef(false)
  let eventSource: EventSource | null = null

  function connect() {
    if (eventSource) return

    const url = options.token
      ? `${options.url}?token=${encodeURIComponent(options.token)}`
      : options.url

    eventSource = new EventSource(url)
    isConnected.value = true

    if (options.onConnected) {
      eventSource.addEventListener('connected', () => options.onConnected!())
    }
    if (options.onProgress) {
      eventSource.addEventListener('progress', (e: MessageEvent) => {
        try { options.onProgress!(JSON.parse(e.data)) } catch { /* ignore */ }
      })
    }
    if (options.onNodeFinished) {
      eventSource.addEventListener('node_finished', (e: MessageEvent) => {
        try { options.onNodeFinished!(JSON.parse(e.data)) } catch { /* ignore */ }
      })
    }
    if (options.onComplete) {
      eventSource.addEventListener('complete', () => options.onComplete!())
    }
    if (options.onError) {
      eventSource.addEventListener('error', (e: MessageEvent) => {
        try { options.onError!(JSON.parse(e.data)) } catch { /* ignore */ }
      })
    }

    // Auto-disconnect on fatal transport error
    eventSource.onerror = () => disconnect()
  }

  function disconnect() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
      isConnected.value = false
    }
  }

  onUnmounted(disconnect)

  return { isConnected, connect, disconnect }
}
