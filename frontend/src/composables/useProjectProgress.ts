import { ref, onUnmounted } from 'vue'
import { projectsApi } from '@/api/projects'
import { useSSE } from '@/composables/useSSE'
import { usePolling } from '@/composables/usePolling'
import { formatTime } from '@/lib/utils'

export interface ProgressLog {
  time: string
  node: string
  message: string
}

export const PIPELINE_STAGES = [
  { key: 'search', label: '搜索', icon: '🔍' },
  { key: 'deduplicate', label: '去重', icon: '🔄' },
  { key: 'filter', label: '过滤', icon: '🔽' },
  { key: 'bm25', label: 'BM25', icon: '📊' },
  { key: 'embedding', label: '嵌入', icon: '📐' },
  { key: 'pgvector_knn', label: 'KNN', icon: '🕸️' },
  { key: 'rerank', label: '重排序', icon: '📈' },
  { key: 'kg_extraction', label: '实体抽取', icon: '🏷️' },
  { key: 'community_memory', label: '社区记忆', icon: '🧠' },
  { key: 'community_detection', label: '聚类', icon: '🧩' },
  { key: 'visualize_community', label: '可视化', icon: '🎨' },
  { key: 'evidence_cards', label: '证据卡片', icon: '📋' },
  { key: 'outline_generation', label: '大纲', icon: '📝' },
  { key: 'gap_analysis', label: '缺口分析', icon: '🔎' },
  { key: 'write_review', label: '写作', icon: '✍️' },
  { key: 'finalize', label: '完成', icon: '✅' },
]

const STAGE_LABEL_MAP: Record<string, string> = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, s.label])
)

export function useProjectProgress(projectId: string, opts?: {
  onCompleted?: () => void
}) {
  const progressLogs = ref<ProgressLog[]>([])
  const currentProgressNode = ref('')
  const progressMessage = ref('')
  const completedNodes = ref<Set<string>>(new Set())
  const failedNodes = ref<Set<string>>(new Set())

  // ── SSE ──
  const baseUrl = import.meta.env.VITE_API_URL || '/api'

  const { isConnected, connect: sseConnect, disconnect: sseDisconnect } = useSSE({
    url: `${baseUrl}/stream/${projectId}`,
    token: localStorage.getItem('access_token') ?? undefined,
    onConnected() {
      progressLogs.value.push({ time: formatTime(), node: 'system', message: 'Connected to progress stream' })
    },
    onProgress(data) {
      currentProgressNode.value = (data.node as string) || ''
      progressMessage.value = (data.message as string) || ''
      if (data.message) {
        progressLogs.value.push({ time: formatTime(), node: (data.node as string) || '', message: data.message as string })
      }
    },
    onNodeFinished(data) {
      const node = data.node as string
      if (!node) return
      if (data.status === 'succeeded') {
        completedNodes.value.add(node)
        failedNodes.value.delete(node)
      } else if (data.status === 'failed') {
        failedNodes.value.add(node)
      }
    },
    onComplete() {
      progressLogs.value.push({ time: formatTime(), node: 'system', message: 'Pipeline completed!' })
      sseDisconnect()
      opts?.onCompleted?.()
    },
    onError(data) {
      progressLogs.value.push({ time: formatTime(), node: 'error', message: `Error: ${data.message}` })
    },
  })

  // ── Status polling ──
  const { start: startStatusPolling, stop: stopStatusPolling } = usePolling(async () => {
    try {
      const status = await projectsApi.getProjectStatus(projectId)
      if (status.status?.startsWith('running:')) {
        currentProgressNode.value = status.status.replace('running:', '')
      }
      if (status.status === 'completed' || status.status === 'failed') {
        stopStatusPolling()
        stopCallsPolling()
        opts?.onCompleted?.()
      } else if (status.status === 'interrupted') {
        stopStatusPolling()
      }
    } catch { /* ignore */ }
  }, 5000)

  // ── Calls polling (stub – the view passes its own loadLlmCalls) ──
  let callsPollTimer: ReturnType<typeof setInterval> | null = null

  function startCallsPolling(loadCalls: () => void) {
    if (callsPollTimer) return
    loadCalls()
    callsPollTimer = setInterval(loadCalls, 5000)
  }

  function stopCallsPolling() {
    if (callsPollTimer) { clearInterval(callsPollTimer); callsPollTimer = null }
  }

  // ── Historical progress ──
  async function loadHistoricalProgress() {
    try {
      const res = await projectsApi.getProjectProgress(projectId)
      for (const node of res.nodes) {
        const label = STAGE_LABEL_MAP[node.node_name] || node.node_name
        const time = node.finished_at
          ? new Date(node.finished_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
          : new Date(node.started_at || '').toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
        if (node.status === 'succeeded') {
          progressLogs.value.push({ time, node: node.node_name, message: `${label} 完成` })
          completedNodes.value.add(node.node_name)
        } else if (node.status === 'failed') {
          const err = node.error_message ? `: ${node.error_message}` : ''
          progressLogs.value.push({ time, node: node.node_name, message: `${label} 失败${err}` })
          failedNodes.value.add(node.node_name)
        }
      }
    } catch { /* ignore */ }
  }

  function connectSSE() { sseConnect() }
  function disconnectSSE() { sseDisconnect() }

  onUnmounted(() => {
    disconnectSSE()
    stopStatusPolling()
    stopCallsPolling()
  })

  return {
    progressLogs, currentProgressNode, progressMessage,
    completedNodes, failedNodes, isConnected,
    connectSSE, disconnectSSE,
    startStatusPolling, stopStatusPolling,
    startCallsPolling, stopCallsPolling,
    loadHistoricalProgress,
    pipelineStages: PIPELINE_STAGES,
  }
}
