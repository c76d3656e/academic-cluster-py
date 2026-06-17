<script setup lang="ts">
import { ref, nextTick, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useI18n } from '@/i18n'
import { formatTime } from '@/lib/utils'
import { projectsApi } from '@/api/projects'
import { Button } from '@/components/ui/button'

const router = useRouter()
const { user, logout } = useAuth()
const { t } = useI18n()

interface ChatMessage {
  id: string
  role: 'user' | 'system' | 'progress' | 'result'
  content: string
  time: string
  node?: string
  status?: string
}

const messages = ref<ChatMessage[]>([])
const input = ref('')
const isProcessing = ref(false)
const currentProjectId = ref<string | null>(null)
const progressNode = ref('')
const progressMessage = ref('')
let eventSource: EventSource | null = null

const messagesContainer = ref<HTMLElement | null>(null)

const nodeKeyMap: Record<string, string> = {
  search: 'nodes.searchFull',
  deduplicate: 'nodes.deduplicateFull',
  filter: 'nodes.filterFull',
  bm25: 'nodes.bm25Full',
  embedding: 'nodes.embeddingFull',
  pgvector_knn: 'nodes.pgvectorKnnFull',
  rerank: 'nodes.rerankFull',
  kg_extraction: 'nodes.kgExtractionFull',
  community_detection: 'nodes.communityDetectionFull',
  visualize_community: 'nodes.visualizeCommunityFull',
  evidence_cards: 'nodes.evidenceCardsFull',
  gap_analysis: 'nodes.gapAnalysisFull',
  targeted_refine: 'nodes.targetedRefineFull',
  outline_generation: 'nodes.outlineGenerationFull',
  user_confirm: 'nodes.userConfirmFull',
  write_review: 'nodes.writeReviewFull',
  coverage_audit: 'nodes.coverageAuditFull',
  section_revision: 'nodes.sectionRevisionFull',
  artifact_registration: 'nodes.artifactRegistrationFull',
  finalize: 'nodes.finalizeFull',
}

function getNodeLabel(node: string): string {
  const key = nodeKeyMap[node]
  return key ? t(key) : node
}

function addMessage(role: ChatMessage['role'], content: string, extra?: Partial<ChatMessage>) {
  messages.value.push({
    id: crypto.randomUUID(),
    role,
    content,
    time: formatTime(),
    ...extra,
  })
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

async function handleSubmit() {
  const query = input.value.trim()
  if (!query || isProcessing.value) return

  input.value = ''
  addMessage('user', query)
  isProcessing.value = true

  try {
    const project = await projectsApi.createProject({
      name: query.slice(0, 100),
      query,
    })

    currentProjectId.value = project.id
    addMessage('system', t('pipeline.projectCreated'))

    await projectsApi.startPipeline(project.id)

    connectSSE(project.id)
  } catch (err: any) {
    const error = err.response?.data?.detail || err.message || ''
    addMessage('system', t('pipeline.createFailed', { error }))
    isProcessing.value = false
  }
}

function connectSSE(projectId: string) {
  if (eventSource) eventSource.close()

  const baseUrl = import.meta.env.VITE_API_URL || '/api'
  const url = `${baseUrl}/stream/${projectId}`
  eventSource = new EventSource(url)

  eventSource.addEventListener('connected', () => {
    addMessage('progress', t('pipeline.connected'), { node: 'system' })
  })

  eventSource.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data)
    progressNode.value = data.node || ''
    progressMessage.value = data.message || ''

    const label = getNodeLabel(data.node || '')
    addMessage('progress', data.message || label, { node: data.node, status: data.status })
  })

  eventSource.addEventListener('complete', () => {
    addMessage('result', t('pipeline.pipelineCompleted'))
    disconnectSSE()
    isProcessing.value = false
  })

  eventSource.addEventListener('error', () => {
    addMessage('system', t('pipeline.disconnected'))
  })
}

function disconnectSSE() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

function viewResult() {
  if (currentProjectId.value) {
    router.push(`/projects/${currentProjectId.value}`)
  }
}

function viewConsole() {
  router.push('/console/overview')
}

async function handleLogout() {
  await logout()
  router.push('/login')
}

const hasResult = computed(() => messages.value.some(m => m.role === 'result'))

onUnmounted(() => {
  disconnectSSE()
})
</script>

<template>
  <div class="flex flex-col h-screen bg-background">
    <!-- Header -->
    <header class="flex items-center justify-between px-4 md:px-6 py-3 border-b border-border shrink-0 gap-2 flex-wrap">
      <div class="flex items-center gap-3 min-w-0">
        <h1 class="text-sm font-semibold tracking-tight shrink-0">Academic Cluster</h1>
        <span class="text-[0.65rem] text-muted-foreground hidden sm:inline">{{ t('pipeline.assistant') }}</span>
      </div>
      <div class="flex items-center gap-2 md:gap-3">
        <span class="text-xs text-muted-foreground truncate max-w-[120px] md:max-w-none">{{ user?.email }}</span>
        <Button variant="ghost" size="sm" @click="viewConsole">{{ t('pipeline.console') }}</Button>
        <Button variant="ghost" size="sm" class="text-destructive" @click="handleLogout">{{ t('auth.logout') }}</Button>
      </div>
    </header>

    <!-- Messages -->
    <div ref="messagesContainer" class="flex-1 overflow-y-auto">
      <!-- Empty state -->
      <div v-if="messages.length === 0" class="flex flex-col items-center justify-center h-full text-center px-4">
        <div class="mb-6">
          <h2 class="text-2xl font-semibold tracking-tight mb-2">{{ t('pipeline.assistant') }}</h2>
          <p class="text-muted-foreground max-w-md">
            {{ t('pipeline.assistantDesc') }}
          </p>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-lg w-full">
          <button
            v-for="topic in [
              'Large Language Model survey',
              'Transformer attention mechanisms',
              'Graph neural networks for drug discovery',
              'Federated learning privacy',
            ]"
            :key="topic"
            @click="input = topic"
            class="text-left p-3 rounded-lg border border-border hover:bg-muted/50 transition-colors text-sm"
          >
            {{ topic }}
          </button>
        </div>
      </div>

      <!-- Message list -->
      <div v-else class="max-w-3xl mx-auto px-4 py-6 space-y-4">
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="flex gap-3"
          :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <!-- User message -->
          <div
            v-if="msg.role === 'user'"
            class="max-w-[80%] rounded-2xl px-4 py-2.5 bg-foreground text-background"
          >
            <p class="text-sm">{{ msg.content }}</p>
            <p class="text-[0.6rem] opacity-60 mt-1 text-right">{{ msg.time }}</p>
          </div>

          <!-- System / Progress / Result messages -->
          <div v-else class="max-w-[85%]">
            <div
              class="rounded-2xl px-4 py-2.5"
              :class="{
                'bg-muted': msg.role === 'system',
                'bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800': msg.role === 'progress',
                'bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-800': msg.role === 'result',
              }"
            >
              <div v-if="msg.role === 'progress'" class="flex items-start gap-2">
                <div class="size-2 rounded-full bg-blue-500 mt-1.5 shrink-0 animate-pulse" />
                <div>
                  <p class="text-[0.65rem] font-medium text-blue-600 dark:text-blue-400 mb-0.5">
                    {{ getNodeLabel(msg.node || '') || msg.node || t('common.processing') }}
                  </p>
                  <p class="text-sm text-foreground">{{ msg.content }}</p>
                </div>
              </div>
              <div v-else-if="msg.role === 'result'">
                <p class="text-sm font-medium text-green-700 dark:text-green-400">{{ msg.content }}</p>
              </div>
              <div v-else>
                <p class="text-sm text-foreground">{{ msg.content }}</p>
              </div>
              <p class="text-[0.6rem] text-muted-foreground mt-1">{{ msg.time }}</p>
            </div>
          </div>
        </div>

        <!-- View result button -->
        <div v-if="hasResult" class="flex justify-center pt-4">
          <Button @click="viewResult" class="gap-2">
            {{ t('pipeline.viewFullReview') }}
          </Button>
        </div>
      </div>
    </div>

    <!-- Input -->
    <div class="border-t border-border p-4 shrink-0">
      <div class="max-w-3xl mx-auto">
        <div class="flex gap-2 items-end">
          <div class="flex-1 relative">
            <textarea
              v-model="input"
              @keydown.enter.exact.prevent="handleSubmit"
              :placeholder="t('pipeline.inputPlaceholder')"
              :disabled="isProcessing"
              rows="1"
              class="w-full resize-none rounded-xl border border-border bg-muted/50 px-4 py-3 pr-12 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
              style="min-height: 48px; max-height: 120px;"
            />
          </div>
          <Button
            @click="handleSubmit"
            :disabled="!input.trim() || isProcessing"
            size="icon"
            class="rounded-xl size-12 shrink-0"
          >
            <span v-if="isProcessing" class="animate-spin">&#8635;</span>
            <span v-else>&#9654;</span>
          </Button>
        </div>
        <p class="text-[0.6rem] text-muted-foreground text-center mt-2">
          {{ t('pipeline.inputHint') }}
        </p>
      </div>
    </div>
  </div>
</template>
