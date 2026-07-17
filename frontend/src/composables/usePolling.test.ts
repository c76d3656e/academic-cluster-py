import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('vue', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue')>()
  return { ...actual, onUnmounted: vi.fn() }
})

import { usePolling } from './usePolling'

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('waits for the active callback before scheduling the next poll', async () => {
    const first = deferred()
    const callback = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValue(undefined)
    const polling = usePolling(callback, 1000)

    polling.start()
    expect(callback).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(5000)
    expect(callback).toHaveBeenCalledTimes(1)

    first.resolve()
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(999)
    expect(callback).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(callback).toHaveBeenCalledTimes(2)

    polling.stop()
  })

  it('invalidates an in-flight callback when polling stops', async () => {
    const active = deferred()
    const contexts: Array<{ isCurrent: () => boolean; signal: AbortSignal }> = []
    const callback = vi.fn((context) => {
      contexts.push(context)
      return active.promise
    })
    const polling = usePolling(callback, 1000)

    polling.start()
    expect(contexts[0].isCurrent()).toBe(true)
    polling.stop()

    expect(contexts[0].signal.aborted).toBe(true)
    expect(contexts[0].isCurrent()).toBe(false)
    active.resolve()
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(5000)
    expect(callback).toHaveBeenCalledTimes(1)
    expect(polling.isPolling.value).toBe(false)
  })
})
