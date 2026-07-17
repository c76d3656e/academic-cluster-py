import { onUnmounted, ref } from 'vue'
import {
  projectsApi,
  type PipelineStatusResponse,
} from '@/api/projects'
import { useSSE } from '@/composables/useSSE'
import { usePolling } from '@/composables/usePolling'
import { formatTime } from '@/lib/utils'
import {
  isTerminalPipelineStatus,
  normalizePipelinePhase,
  PIPELINE_STAGES,
  type PipelinePhase,
} from '@/lib/pipeline'

export { PIPELINE_STAGES } from '@/lib/pipeline'

export interface ProgressLog {
  time: string
  node: string
  message: string
}

export interface ProjectProgressOptions {
  onStatusChange?: (status: PipelineStatusResponse) => void
  onTerminal?: (status: PipelineStatusResponse) => void
}

function eventMessage(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function eventFailed(value: unknown): boolean {
  return typeof value === 'string' && (value === 'failed' || value.endsWith('_failed'))
}

function nodeTime(value: string | null): string {
  if (!value) return formatTime()
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? formatTime() : date.toLocaleTimeString()
}

export function useProjectProgress(projectId: string, options?: ProjectProgressOptions) {
  const progressLogs = ref<ProgressLog[]>([])
  const currentProgressNode = ref<PipelinePhase | ''>('')
  const progressMessage = ref('')
  const completedNodes = ref<Set<PipelinePhase>>(new Set())
  const failedNodes = ref<Set<PipelinePhase>>(new Set())
  const executionId = ref<string | null>(null)
  let historicalProgressLoaded = false
  let historyRequestGeneration = 0
  let statusRequestGeneration = 0
  let notifiedTerminalKey: string | null = null

  function addLog(node: string, message: string) {
    progressLogs.value.push({ time: formatTime(), node, message })
  }

  function activatePhase(phase: PipelinePhase) {
    const previous = currentProgressNode.value
    if (previous && previous !== phase && !failedNodes.value.has(previous)) {
      completedNodes.value.add(previous)
    }
    currentProgressNode.value = phase
  }

  function resetProgress() {
    progressLogs.value = []
    currentProgressNode.value = ''
    progressMessage.value = ''
    completedNodes.value = new Set()
    failedNodes.value = new Set()
    historicalProgressLoaded = false
  }

  function normalizedExecutionId(value: string | null | undefined): string | null {
    const normalized = value?.trim()
    return normalized || null
  }

  function adoptExecution(nextExecutionId: string | null | undefined): boolean {
    const next = normalizedExecutionId(nextExecutionId)
    if (!next || executionId.value === next) return false

    const changedExecution = executionId.value !== null
    if (changedExecution) resetProgress()
    executionId.value = next
    notifiedTerminalKey = null
    historyRequestGeneration += 1
    return changedExecution
  }

  /** Start tracking an accepted execution while preserving same-checkpoint resumes. */
  function beginExecution(nextExecutionId: string) {
    statusRequestGeneration += 1
    notifiedTerminalKey = null
    adoptExecution(nextExecutionId)
  }

  const baseUrl = import.meta.env.VITE_API_URL || '/api'
  const {
    connect: connectSSE,
    disconnect: disconnectSSE,
  } = useSSE({
    url: `${baseUrl}/stream/${projectId}`,
    token: () => localStorage.getItem('access_token') ?? undefined,
    onConnected() {
      addLog('system', 'Connected to progress stream')
    },
    onProgress(data) {
      const phase = normalizePipelinePhase(data.phase ?? data.node)
      const message = eventMessage(data.message)

      if (phase) {
        activatePhase(phase)
        if (eventFailed(data.status)) {
          failedNodes.value.add(phase)
          completedNodes.value.delete(phase)
        } else {
          failedNodes.value.delete(phase)
        }
      }
      progressMessage.value = message
      if (message) addLog(phase ?? eventMessage(data.node), message)
    },
    onComplete() {
      disconnectSSE()
      addLog('system', 'Pipeline execution finished')
      void refreshStatus()
    },
    onError(data) {
      disconnectSSE()
      addLog('error', eventMessage(data.message) || 'Pipeline execution failed')
      void refreshStatus()
    },
    onTransportError() {
      addLog('system', 'Progress stream disconnected; status polling is still active')
    },
  })

  async function refreshStatus(): Promise<PipelineStatusResponse | null> {
    const requestGeneration = ++statusRequestGeneration
    try {
      const status = await projectsApi.getProjectStatus(projectId)
      if (requestGeneration !== statusRequestGeneration) return null
      adoptExecution(status.execution_id)
      if (status.current_phase) activatePhase(status.current_phase)
      options?.onStatusChange?.(status)

      if (isTerminalPipelineStatus(status.status)) {
        if (status.status === 'completed') {
          for (const stage of PIPELINE_STAGES) completedNodes.value.add(stage.key)
          failedNodes.value.clear()
          currentProgressNode.value = ''
        } else if (currentProgressNode.value) {
          failedNodes.value.add(currentProgressNode.value)
          completedNodes.value.delete(currentProgressNode.value)
        }
        stopStatusPolling()
        stopCallsPolling()
        disconnectSSE()
        const terminalKey = `${status.execution_id ?? executionId.value ?? 'none'}:${status.status}`
        if (notifiedTerminalKey !== terminalKey) {
          notifiedTerminalKey = terminalKey
          options?.onTerminal?.(status)
        }
      } else {
        notifiedTerminalKey = null
      }
      return status
    } catch {
      return null
    }
  }

  const statusPolling = usePolling(async () => {
    await refreshStatus()
  }, 5000)

  function startStatusPolling() {
    statusPolling.start()
  }

  function stopStatusPolling() {
    statusRequestGeneration += 1
    statusPolling.stop()
  }

  let loadCallsCallback: (() => void | Promise<void>) | null = null
  const callsPolling = usePolling(async () => {
    await loadCallsCallback?.()
  }, 5000)

  function startCallsPolling(loadCalls: () => void | Promise<void>) {
    loadCallsCallback = loadCalls
    callsPolling.start()
  }

  function stopCallsPolling() {
    callsPolling.stop()
    loadCallsCallback = null
  }

  async function loadHistoricalProgress() {
    if (historicalProgressLoaded) return
    historicalProgressLoaded = true
    const requestGeneration = ++historyRequestGeneration
    const expectedExecutionId = executionId.value
    try {
      const response = await projectsApi.getProjectProgress(projectId)
      if (requestGeneration !== historyRequestGeneration) {
        historicalProgressLoaded = false
        return
      }
      const responseExecutionId = normalizedExecutionId(response.execution_id)
      if (
        expectedExecutionId
        && responseExecutionId
        && expectedExecutionId !== responseExecutionId
      ) {
        historicalProgressLoaded = false
        return
      }
      if (!expectedExecutionId && responseExecutionId) {
        executionId.value = responseExecutionId
      }
      for (const node of response.nodes) {
        const phase = normalizePipelinePhase(node.node_name)
        if (!phase) continue

        const time = nodeTime(node.finished_at ?? node.started_at)
        if (node.status === 'succeeded' || node.status === 'completed') {
          progressLogs.value.push({ time, node: phase, message: `${phase} completed` })
          completedNodes.value.add(phase)
          failedNodes.value.delete(phase)
        } else if (node.status === 'failed') {
          const detail = node.error_message ? `: ${node.error_message}` : ''
          progressLogs.value.push({ time, node: phase, message: `${phase} failed${detail}` })
          failedNodes.value.add(phase)
          completedNodes.value.delete(phase)
          currentProgressNode.value = phase
        } else if (node.status === 'running') {
          activatePhase(phase)
        } else if (node.status === 'interrupted') {
          progressLogs.value.push({ time, node: phase, message: `${phase} interrupted` })
          failedNodes.value.add(phase)
          completedNodes.value.delete(phase)
          currentProgressNode.value = phase
        }
      }
    } catch {
      if (requestGeneration === historyRequestGeneration) historicalProgressLoaded = false
    }
  }

  onUnmounted(() => {
    disconnectSSE()
    stopStatusPolling()
    stopCallsPolling()
  })

  return {
    progressLogs,
    currentProgressNode,
    progressMessage,
    completedNodes,
    executionId,
    beginExecution,
    connectSSE,
    disconnectSSE,
    startStatusPolling,
    stopStatusPolling,
    startCallsPolling,
    stopCallsPolling,
    loadHistoricalProgress,
  }
}
