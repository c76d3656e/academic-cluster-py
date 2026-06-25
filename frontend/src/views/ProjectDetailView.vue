<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { projectsApi, type Project } from '@/api/projects'
import { consoleApi, type ConsoleLlmCall } from '@/api/console'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { toast } from 'vue-sonner'
import { useI18n } from '@/i18n'
import { useFeatures } from '@/composables/useFeatures'
import { useProjectReview } from '@/composables/useProjectReview'
import { useProjectProgress } from '@/composables/useProjectProgress'
import { getStatusVariant, getStatusLabel } from '@/lib/utils'
import ReviewArticle from '@/components/ReviewArticle.vue'
import PipelineProgress from '@/components/PipelineProgress.vue'
import LlmCallsTable from '@/components/LlmCallsTable.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const projectId = route.params.id as string

const project = ref<Project | null>(null)
const isLoading = ref(true)
const isStarting = ref(false)
const isResuming = ref(false)

// Features
const { features, loadFeatures } = useFeatures()
const showUsage = computed(() => features.value.show_usage ?? false)

// Review composable
const {
  outline, sections, evidenceCards, references,
  hasReview, totalWordCount, uniqueClusters, articleAbstract, evidenceCardByPaperId,
  loadReview,
} = useProjectReview(projectId)

// Progress composable
const {
  progressLogs, currentProgressNode, progressMessage,
  completedNodes,
  connectSSE, startStatusPolling, startCallsPolling,
  loadHistoricalProgress,
} = useProjectProgress(projectId, {
  async onCompleted() {
    // Fetch actual status instead of hardcoding 'completed'
    try {
      const s = await projectsApi.getProjectStatus(projectId)
      if (project.value && s.status) project.value.status = s.status
    } catch {
      if (project.value) project.value.status = 'completed'
    }
    loadReview()
  },
})

const isRunning = computed(() => {
  const s = project.value?.status || ''
  return s.startsWith('running') || s === 'running'
})

// LLM Calls
const llmCalls = ref<ConsoleLlmCall[]>([])
const isLoadingCalls = ref(false)
const selectedLlmNode = ref('')

async function loadLlmCalls() {
  isLoadingCalls.value = true
  try {
    llmCalls.value = await consoleApi.getMyCalls({
      project_id: projectId,
      node_name: selectedLlmNode.value || undefined,
      limit: 200,
    })
  } catch {
    llmCalls.value = []
  } finally {
    isLoadingCalls.value = false
  }
}

function onLlmNodeFilterChange() {
  loadLlmCalls()
}

// Pipeline controls
async function startPipeline() {
  isStarting.value = true
  try {
    await projectsApi.startPipeline(projectId)
    if (project.value) project.value.status = 'running'
    toast.success(t('pipeline.started'))
    connectSSE()
    startStatusPolling()
    startCallsPolling(loadLlmCalls)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    toast.error(err.response?.data?.detail || t('pipeline.startFailed'))
  } finally {
    isStarting.value = false
  }
}

async function resumePipeline() {
  isResuming.value = true
  try {
    await projectsApi.resumePipeline(projectId)
    if (project.value) project.value.status = 'running'
    toast.success(t('pipeline.resumed'))
    connectSSE()
    startStatusPolling()
    startCallsPolling(loadLlmCalls)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    toast.error(err.response?.data?.detail || t('pipeline.resumeFailed'))
  } finally {
    isResuming.value = false
  }
}

// Download
const showDownloadMenu = ref(false)
const downloadMenuRef = ref<HTMLElement | null>(null)

function onClickOutside(e: MouseEvent) {
  if (downloadMenuRef.value && !downloadMenuRef.value.contains(e.target as Node)) {
    showDownloadMenu.value = false
  }
}

function downloadFile(filename: string, content: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function getSectionTitle(section: { section_id: string }, idx: number): string {
  const outlineTitles = outline.value?.sections?.map(s => s.title ?? s.heading ?? s.id ?? '') ?? []
  if (idx < outlineTitles.length && outlineTitles[idx]) return outlineTitles[idx]
  return section.section_id.replace(/[_-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function downloadTopicMd() {
  showDownloadMenu.value = false
  const title = outline.value?.title || project.value?.query || 'Review'
  let md = `# ${title}\n\n`
  for (let i = 0; i < sections.value.length; i++) {
    const s = sections.value[i]
    md += `## ${getSectionTitle(s, i)}\n\n${s.content}\n\n`
  }
  const safeTitle = (outline.value?.title || project.value?.query || 'topic').replace(/[<>:"/\\|?*]/g, '_').substring(0, 100)
  downloadFile(`${safeTitle}.md`, md, 'text/markdown')
}

function downloadReferenceBib() {
  showDownloadMenu.value = false
  let bib = ''
  for (let i = 0; i < references.value.length; i++) {
    const ref = references.value[i]
    const key = `ref${ref.new_number || i + 1}`
    bib += `@article{${key},\n`
    if (ref.title) bib += `  title = {${ref.title}},\n`
    if (ref.authors) bib += `  author = {${ref.authors}},\n`
    if (ref.year) bib += `  year = {${ref.year}},\n`
    if (ref.venue) bib += `  journal = {${ref.venue}},\n`
    if (ref.doi) bib += `  doi = {${ref.doi}},\n`
    bib += `}\n\n`
  }
  const safeTitle = (outline.value?.title || project.value?.query || 'reference').replace(/[<>:"/\\|?*]/g, '_').substring(0, 100)
  downloadFile(`${safeTitle}.bib`, bib, 'application/x-bibtex')
}

// Mount
onMounted(async () => {
  document.addEventListener('click', onClickOutside)
  try {
    project.value = await projectsApi.getProject(projectId)
    loadHistoricalProgress()
    if (isRunning.value) {
      connectSSE()
      startStatusPolling()
      startCallsPolling(loadLlmCalls)
    }
    await loadFeatures()
    await loadReview()
    if (showUsage.value) await loadLlmCalls()
  } catch (e: unknown) {
    const err = e as { response?: { status?: number } }
    if (err.response?.status === 401 || err.response?.status === 403) {
      router.push('/login')
    } else {
      toast.error(t('project.loadFailed'))
      if (window.history.length > 1) {
        router.back()
      } else {
        router.push('/console/projects')
      }
    }
  } finally {
    isLoading.value = false
  }
})
</script>

<template>
  <div class="min-h-screen bg-background">
    <!-- Top Navigation Bar -->
    <header class="border-b border-border sticky top-0 z-10 bg-background/80 backdrop-blur-sm">
      <div class="max-w-[1100px] mx-auto px-4 md:px-6 py-2.5 flex items-center gap-2 md:gap-3">
        <router-link to="/console/overview" class="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg>
          {{ t('common.back') }}
        </router-link>
        <Separator orientation="vertical" class="h-5" />
        <h1 class="text-sm font-medium text-foreground truncate">{{ project?.name || t('common.loading') }}</h1>
        <Badge v-if="project" :variant="getStatusVariant(project.status)" class="shrink-0 text-xs">
          {{ getStatusLabel(project.status) }}
        </Badge>
        <!-- Download button -->
        <div v-if="hasReview" class="ml-auto">
          <div ref="downloadMenuRef" class="relative">
            <Button variant="outline" size="sm" class="gap-1.5 text-xs" @click="showDownloadMenu = !showDownloadMenu">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
              {{ t('article.download') }}
            </Button>
            <div v-if="showDownloadMenu" class="absolute right-0 top-full mt-1 w-44 bg-card border border-border rounded-lg shadow-lg py-1 z-20">
              <button class="w-full px-3 py-2 text-left text-sm hover:bg-secondary transition-colors flex items-center gap-2" @click="downloadTopicMd">
                <span class="text-muted-foreground font-mono text-xs">.md</span>
                {{ (outline?.title || project?.query || 'topic') + '.md' }}
              </button>
              <button class="w-full px-3 py-2 text-left text-sm hover:bg-secondary transition-colors flex items-center gap-2" @click="downloadReferenceBib">
                <span class="text-muted-foreground font-mono text-xs">.bib</span>
                {{ (outline?.title || project?.query || 'references') + '.bib' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </header>

    <!-- Loading -->
    <div v-if="isLoading" class="flex items-center justify-center py-32 text-muted-foreground text-sm">
      {{ t('common.loading') }}
    </div>

    <main v-else-if="project" class="max-w-[1100px] mx-auto px-4 md:px-6 min-w-0">
      <!-- Running: Progress Panel -->
      <PipelineProgress
        v-if="isRunning || progressLogs.length > 0"
        :is-running="isRunning"
        :completed-nodes="completedNodes"
        :progress-logs="progressLogs"
        :current-progress-node="currentProgressNode"
        :progress-message="progressMessage"
        :project-status="project.status"
      />

      <!-- LLM Calls Table -->
      <LlmCallsTable
        v-if="showUsage && (isRunning || progressLogs.length > 0)"
        :llm-calls="llmCalls"
        :is-loading-calls="isLoadingCalls"
        :selected-llm-node="selectedLlmNode"
        @update:selected-llm-node="selectedLlmNode = $event"
        @filter-change="onLlmNodeFilterChange"
      />

      <!-- Not started yet -->
      <div v-if="project.status === 'created'" class="my-12 text-center">
        <p class="text-muted-foreground mb-4">{{ t('pipeline.ready') }}</p>
        <Button :disabled="isStarting" size="lg" @click="startPipeline">
          {{ isStarting ? t('pipeline.starting') : t('pipeline.startPipeline') }}
        </Button>
      </div>

      <!-- Nature article layout -->
      <ReviewArticle
        v-if="hasReview"
        :outline="outline"
        :sections="sections"
        :references="references"
        :evidence-cards="evidenceCards"
        :evidence-card-by-paper-id="evidenceCardByPaperId"
        :total-word-count="totalWordCount"
        :unique-clusters="uniqueClusters"
        :article-abstract="articleAbstract"
        :project-query="project.query"
        :project-created-at="project.created_at"
        :project-status="project.status"
      />

      <!-- Empty state for completed but no content -->
      <div v-else-if="project.status === 'completed'" class="text-center py-20">
        <div class="text-muted-foreground/60 mb-2">
          <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="mx-auto"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" /></svg>
        </div>
        <p class="text-foreground font-medium">{{ t('pipeline.noContent') }}</p>
        <p class="text-sm text-muted-foreground mt-1">{{ t('pipeline.noContentDesc') }}</p>
      </div>

      <!-- Interrupted / Failed state -->
      <div v-else-if="(project.status === 'interrupted' || project.status === 'failed') && !hasReview" class="text-center py-16">
        <div class="text-muted-foreground/60 mb-2">
          <svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="mx-auto"><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></svg>
        </div>
        <p class="text-foreground font-medium">{{ project.status === 'failed' ? t('pipeline.taskFailed') : t('pipeline.taskInterrupted') }}</p>
        <p class="text-sm text-muted-foreground mt-1">{{ project.status === 'failed' ? t('pipeline.taskFailedDesc') : t('pipeline.taskInterruptedDesc') }}</p>
        <Button size="sm" class="mt-4" :disabled="isResuming" @click="resumePipeline">
          {{ isResuming ? t('pipeline.resuming') : t('pipeline.resumePipeline') }}
        </Button>
      </div>
    </main>
  </div>
</template>
