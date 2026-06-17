import { onUnmounted, shallowRef } from 'vue'

/**
 * Composable that runs a callback on a fixed interval until stopped.
 *
 * The timer is automatically cleaned up when the component unmounts.
 *
 * Usage:
 * ```ts
 * const { isPolling, start, stop } = usePolling(loadData, 5000)
 * ```
 */
export function usePolling(callback: () => void | Promise<void>, intervalMs: number) {
  const isPolling = shallowRef(false)
  let timer: ReturnType<typeof setInterval> | null = null

  function start() {
    if (timer) return
    isPolling.value = true
    // Fire once immediately, then on interval
    callback()
    timer = setInterval(callback, intervalMs)
  }

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
      isPolling.value = false
    }
  }

  onUnmounted(stop)

  return { isPolling, start, stop }
}
