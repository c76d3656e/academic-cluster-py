<script setup lang="ts">
import { ref, nextTick, onUnmounted, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useI18n } from '@/i18n'
import { formatTime } from '@/lib/utils'
import { projectsApi, type Project } from '@/api/projects'
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

// 历史记录相关
const projects = ref<Project[]>([])
const isLoadingProjects = ref(false)
const sidebarOpen = ref(true)

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

async function loadProjects() {
  isLoadingProjects.value = true
  try {
    const res = await projectsApi.listProjects(0, 50)
    projects.value = res.projects
  } catch {
    // ignore
  } finally {
    isLoadingProjects.value = false
  }
}

function startNewChat() {
  messages.value = []
  currentProjectId.value = null
  isProcessing.value = false
  disconnectSSE()
}

function loadProjectChat(project: Project) {
  // 跳转到项目详情页
  router.push(`/projects/${project.id}`)
}

function getStatusColor(status: string): string {
  if (status === 'completed') return 'text-green-600'
  if (status === 'failed') return 'text-red-600'
  if (status.startsWith('running')) return 'text-blue-600'
  return 'text-muted-foreground'
}

function getStatusLabel(status: string): string {
  if (status === 'completed') return '✓'
  if (status === 'failed') return '✗'
  if (status.startsWith('running')) return '●'
  return '○'
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

    // 刷新项目列表
    loadProjects()

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
  const token = localStorage.getItem('access_token')
  const url = `${baseUrl}/stream/${projectId}?token=${token}`
  eventSource = new EventSource(url)

  let retryCount = 0
  const maxRetries = 3

  eventSource.addEventListener('connected', () => {
    retryCount = 0
    addMessage('progress', t('pipeline.connected'), { node: 'system' })
  })

  eventSource.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data)
    progressNode.value = data.node || ''
    progressMessage.value = data.message || ''

    const existingIdx = messages.value.findIndex(
      m => m.role === 'progress' && m.node === data.node
    )
    if (existingIdx >= 0) {
      messages.value[existingIdx].content = data.message || getNodeLabel(data.node || '')
      messages.value[existingIdx].time = formatTime()
    } else {
      const label = getNodeLabel(data.node || '')
      addMessage('progress', data.message || label, { node: data.node, status: data.status })
    }

    nextTick(() => {
      if (messagesContainer.value) {
        messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
      }
    })
  })

  eventSource.addEventListener('complete', () => {
    addMessage('result', t('pipeline.pipelineCompleted'))
    disconnectSSE()
    isProcessing.value = false
    // 刷新项目列表更新状态
    loadProjects()
  })

  eventSource.onerror = () => {
    retryCount++
    if (retryCount >= maxRetries) {
      addMessage('system', t('pipeline.disconnected'))
      disconnectSSE()
      isProcessing.value = false
    }
  }
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

onMounted(() => {
  loadProjects()
})

onUnmounted(() => {
  disconnectSSE()
})
</script>

<template>
  <div class="flex h-screen bg-background">
    <!-- Sidebar -->
    <aside
      class="flex flex-col border-r border-border bg-muted/30 shrink-0 transition-all duration-300"
      :class="sidebarOpen ? 'w-64' : 'w-0 overflow-hidden'"
    >
      <!-- Sidebar Header -->
      <div class="p-3 border-b border-border">
        <Button variant="outline" class="w-full justify-start gap-2" @click="startNewChat">
          <span class="text-base">+</span>
          <span class="text-sm">{{ t('pipeline.newChat') || 'New Chat' }}</span>
        </Button>
      </div>

      <!-- Project List -->
      <div class="flex-1 overflow-y-auto p-2 space-y-1">
        <div v-if="isLoadingProjects" class="text-center py-4 text-muted-foreground text-xs">
          {{ t('common.loading') }}
        </div>
        <div v-else-if="projects.length === 0" class="text-center py-4 text-muted-foreground text-xs">
          {{ t('project.noProjects') }}
        </div>
        <button
          v-for="project in projects"
          :key="project.id"
          class="w-full text-left p-2.5 rounded-lg text-sm transition-colors hover:bg-muted group"
          :class="{ 'bg-muted': currentProjectId === project.id }"
          @click="loadProjectChat(project)"
        >
          <div class="flex items-start gap-2">
            <span class="mt-0.5 shrink-0" :class="getStatusColor(project.status)">
              {{ getStatusLabel(project.status) }}
            </span>
            <div class="min-w-0 flex-1">
              <p class="font-medium truncate text-foreground">{{ project.name }}</p>
              <p class="text-[0.65rem] text-muted-foreground mt-0.5">
                {{ project.created_at ? new Date(project.created_at).toLocaleDateString() : '' }}
              </p>
            </div>
          </div>
        </button>
      </div>

      <!-- Sidebar Footer -->
      <div class="p-3 border-t border-border space-y-1">
        <Button variant="ghost" size="sm" class="w-full justify-start text-xs" @click="viewConsole">
          {{ t('pipeline.console') }}
        </Button>
        <Button variant="ghost" size="sm" class="w-full justify-start text-xs text-destructive" @click="handleLogout">
          {{ t('auth.logout') }}
        </Button>
      </div>
    </aside>

    <!-- Main Content -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Header -->
      <header class="flex items-center justify-between px-4 py-3 border-b border-border shrink-0 gap-2">
        <div class="flex items-center gap-3 min-w-0">
          <Button variant="ghost" size="icon" class="size-8 shrink-0" @click="sidebarOpen = !sidebarOpen">
            <span class="text-base">&#9776;</span>
          </Button>
          <h1 class="text-sm font-semibold tracking-tight truncate">Academic Cluster</h1>
        </div>
        <div class="flex items-center gap-2">
          <a
            href="https://github.com/c76d3656e/academic-cluster-py"
            target="_blank"
            rel="noopener noreferrer"
            class="flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors"
          >
            <svg viewBox="0 0 24 24" class="size-5" fill="currentColor">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/>
            </svg>
            <span class="text-xs font-medium hidden sm:inline">GitHub</span>
          </a>
          <span class="text-xs text-muted-foreground truncate max-w-[120px]">{{ user?.email }}</span>
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
              class="text-left p-3 rounded-lg border border-border hover:bg-muted/50 transition-colors text-sm"
              @click="input = topic"
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
            <Button class="gap-2" @click="viewResult">
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
                :placeholder="t('pipeline.inputPlaceholder')"
                :disabled="isProcessing"
                rows="1"
                class="w-full resize-none rounded-xl border border-border bg-muted/50 px-4 py-3 pr-12 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
                style="min-height: 48px; max-height: 120px;"
                @keydown.enter.exact.prevent="handleSubmit"
              />
            </div>
            <Button
              :disabled="!input.trim() || isProcessing"
              size="icon"
              class="rounded-xl size-12 shrink-0"
              @click="handleSubmit"
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
  </div>
</template>
