import { onUnmounted, shallowRef } from 'vue'

export interface PollingContext {
  signal: AbortSignal
  isCurrent: () => boolean
}

/**
 * Composable that waits for a callback to settle before scheduling the next poll.
 *
 * The timer is automatically cleaned up when the component unmounts.
 *
 * Usage:
 * ```ts
 * const { isPolling, start, stop } = usePolling(loadData, 5000)
 * ```
 */
export function usePolling(
  callback: (context: PollingContext) => void | Promise<void>,
  intervalMs: number,
) {
  const isPolling = shallowRef(false)
  let timer: ReturnType<typeof setTimeout> | null = null
  let generation = 0
  let controller: AbortController | null = null

  async function run(activeGeneration: number, activeController: AbortController) {
    const isCurrent = () => (
      isPolling.value
      && generation === activeGeneration
      && controller === activeController
      && !activeController.signal.aborted
    )

    try {
      await callback({ signal: activeController.signal, isCurrent })
    } catch (error) {
      if (isCurrent()) console.warn('Polling callback failed', error)
    }

    if (!isCurrent()) return
    timer = setTimeout(() => {
      timer = null
      void run(activeGeneration, activeController)
    }, intervalMs)
  }

  function start() {
    if (isPolling.value) return
    isPolling.value = true
    const activeGeneration = ++generation
    const activeController = new AbortController()
    controller = activeController
    void run(activeGeneration, activeController)
  }

  function stop() {
    generation += 1
    controller?.abort()
    controller = null
    if (timer) clearTimeout(timer)
    timer = null
    isPolling.value = false
  }

  onUnmounted(stop)

  return { isPolling, start, stop }
}
