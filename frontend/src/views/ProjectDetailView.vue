<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  projectsApi,
  type Project,
  type ReviewResponse,
  type WrittenSection,
  type EvidenceCard,
  type Outline,
} from '../api/projects'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { toast } from 'vue-sonner'

const route = useRoute()
const router = useRouter()
const projectId = route.params.id as string

const project = ref<Project | null>(null)
const reviewData = ref<ReviewResponse | null>(null)
const isLoading = ref(true)
const isStarting = ref(false)

// SSE progress
const progressLogs = ref<Array<{ time: string; node: string; message: string }>>([])
const currentProgressNode = ref('')
const progressMessage = ref('')
const completedNodes = ref<Set<string>>(new Set())
const failedNodes = ref<Set<string>>(new Set())
const nodeDetails = ref<Record<string, string>>({})
let eventSource: EventSource | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null

// Pipeline stages for visual progress
const pipelineStages = [
  { key: 'search', label: '搜索', icon: '🔍' },
  { key: 'deduplicate', label: '去重', icon: '🔄' },
  { key: 'filter', label: '过滤', icon: '🔽' },
  { key: 'bm25', label: 'BM25', icon: '📊' },
  { key: 'embedding', label: '嵌入', icon: '📐' },
  { key: 'pgvector_knn', label: 'KNN', icon: '🕸️' },
  { key: 'rerank', label: '重排序', icon: '📈' },
  { key: 'kg_extraction', label: '实体抽取', icon: '🏷️' },
  { key: 'community_detection', label: '聚类', icon: '🧩' },
  { key: 'visualize_community', label: '可视化', icon: '🎨' },
  { key: 'evidence_cards', label: '证据卡片', icon: '📋' },
  { key: 'outline_generation', label: '大纲', icon: '📝' },
  { key: 'gap_analysis', label: '缺口分析', icon: '🔎' },
  { key: 'write_review', label: '写作', icon: '✍️' },
  { key: 'finalize', label: '完成', icon: '✅' },
]

const isRunning = computed(() => {
  const s = project.value?.status || ''
  return s.startsWith('running') || s === 'running'
})

const hasReview = computed(() => {
  return reviewData.value && reviewData.value.sections && reviewData.value.sections.length > 0
})

const outline = computed<Outline | null>(() => reviewData.value?.outline ?? null)
const sections = computed<WrittenSection[]>(() => reviewData.value?.sections ?? [])
const evidenceCards = computed<EvidenceCard[]>(() => reviewData.value?.evidence_cards ?? [])
const references = computed(() => reviewData.value?.references ?? [])

/** Ordered outline section titles (indexed by position) */
const outlineTitles = computed<string[]>(() => {
  if (!outline.value?.sections) return []
  return outline.value.sections.map((s) => s.title ?? s.heading ?? s.id ?? '')
})

/** Render a single section content as sanitized HTML with citation links */
function renderSection(content: string): string {
  if (!content) return ''
  let cleaned = content
    .replace(/\(\s*\[(\d+)\]\s*\)/g, '[$1]')
    .replace(/\(\s*\[x\]\s*\)/gi, '')
    .replace(/（\s*\[(\d+)\]\s*）/g, '[$1]')
    .replace(/（\s*\[x\]\s*）/gi, '')
  let html = marked.parse(cleaned) as string
  // Convert [N] citation patterns to superscript links
  html = html.replace(/\[(\d+(?:[,、]\s*\d+)*)\]/g, (_, nums: string) => {
    return nums
      .split(/[,、]\s*/)
      .map((n: string) => `<sup class="cite-ref"><a href="#ref-${n.trim()}" title="Reference ${n.trim()}">[${n.trim()}]</a></sup>`)
      .join('')
  })
  return DOMPurify.sanitize(html, { ADD_ATTR: ['title'] })
}

/** Get display title for a written section */
function getSectionTitle(section: WrittenSection, idx: number): string {
  // Try index-based match first (most reliable)
  if (idx < outlineTitles.value.length && outlineTitles.value[idx]) {
    return outlineTitles.value[idx]
  }
  // Fallback: use section_id, replacing underscores/hyphens with spaces
  const sid = section.section_id
  return sid.replace(/[_-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Total word count across all sections */
const totalWordCount = computed(() => {
  return sections.value.reduce((sum, s) => sum + (s.word_count ?? 0), 0)
})

/** Cluster count from evidence cards */
const uniqueClusters = computed(() => {
  const ids = new Set(evidenceCards.value.map((c) => c.cluster_id).filter(Boolean))
  return ids.size
})

/** Extract abstract from first section (first paragraph) */
const articleAbstract = computed(() => {
  if (!sections.value.length) return ''
  const firstContent = sections.value[0].content || ''
  const paragraphs = firstContent.split(/\n\n+/).filter((p) => p.trim() && !p.trim().startsWith('#'))
  return paragraphs[0]?.trim() || ''
})

/** Table of contents items */
const tocItems = computed(() => {
  return sections.value.map((s, i) => ({
    idx: i,
    title: getSectionTitle(s, i),
  }))
})

/** Active section index for ToC highlighting */
const activeSection = ref(-1)
let observer: IntersectionObserver | null = null

function setupSectionObserver() {
  if (observer) observer.disconnect()
  const ids = sections.value.map((_, i) => `section-${i}`)
  ids.push('references')
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          const id = entry.target.id
          if (id === 'references') {
            activeSection.value = -2
          } else {
            const idx = parseInt(id.replace('section-', ''), 10)
            if (!isNaN(idx)) activeSection.value = idx
          }
        }
      }
    },
    { rootMargin: '-80px 0px -60% 0px', threshold: 0 }
  )
  for (const id of ids) {
    const el = document.getElementById(id)
    if (el) observer.observe(el)
  }
}

function formatTime(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function connectSSE() {
  if (eventSource) return
  const token = localStorage.getItem('access_token')
  if (!token) return
  const baseUrl = import.meta.env.VITE_API_URL || '/api'
  const url = `${baseUrl}/stream/${projectId}?token=${encodeURIComponent(token)}`
  eventSource = new EventSource(url)

  eventSource.addEventListener('connected', () => {
    progressLogs.value.push({ time: formatTime(), node: 'system', message: 'Connected to progress stream' })
  })

  eventSource.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data)
    currentProgressNode.value = data.node || ''
    progressMessage.value = data.message || ''
    if (data.node) {
      nodeDetails.value[data.node] = data.message || ''
    }
    if (data.message) {
      progressLogs.value.push({ time: formatTime(), node: data.node || '', message: data.message })
    }
    if (project.value && data.node) {
      project.value.status = `running:${data.node}`
    }
  })

  eventSource.addEventListener('node_finished', (e) => {
    const data = JSON.parse(e.data)
    if (data.node) {
      if (data.status === 'succeeded') {
        completedNodes.value.add(data.node)
        failedNodes.value.delete(data.node)
      } else if (data.status === 'failed') {
        failedNodes.value.add(data.node)
      }
    }
  })

  eventSource.addEventListener('complete', () => {
    progressLogs.value.push({ time: formatTime(), node: 'system', message: 'Pipeline completed!' })
    if (project.value) project.value.status = 'completed'
    loadReview()
    disconnectSSE()
  })

  eventSource.addEventListener('error', (e) => {
    if (e instanceof MessageEvent) {
      try {
        const errData = JSON.parse(e.data)
        progressLogs.value.push({ time: formatTime(), node: 'error', message: `Error: ${errData.message}` })
      } catch { /* ignore */ }
    }
  })

  eventSource.onerror = () => disconnectSSE()
}

function disconnectSSE() {
  if (eventSource) { eventSource.close(); eventSource = null }
}

function startStatusPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    try {
      const status = await projectsApi.getProjectStatus(projectId)
      if (project.value) project.value.status = status.status
      // Sync current node from status for progress visualization
      if (status.status?.startsWith('running:')) {
        const node = status.status.replace('running:', '')
        currentProgressNode.value = node
      }
      if (status.status === 'completed' || status.status === 'failed') {
        stopStatusPolling()
        loadReview()
      }
    } catch { /* ignore */ }
  }, 5000)
}

function stopStatusPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

async function loadReview() {
  try {
    const data = await projectsApi.getReview(projectId)
    reviewData.value = data
    // Set up intersection observer after DOM updates
    if (data?.sections?.length) {
      nextTick(() => setupSectionObserver())
    }
  } catch {
    // review may not exist yet
  }
}

onMounted(async () => {
  document.addEventListener('click', onClickOutside)
  try {
    project.value = await projectsApi.getProject(projectId)
    if (isRunning.value) {
      connectSSE()
      startStatusPolling()
    }
    await loadReview()
  } catch (e: unknown) {
    const err = e as { response?: { status?: number } }
    if (err.response?.status === 401 || err.response?.status === 403) {
      router.push('/login')
    } else {
      toast.error('加载项目失败')
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

onUnmounted(() => {
  document.removeEventListener('click', onClickOutside)
  disconnectSSE()
  stopStatusPolling()
  if (observer) { observer.disconnect(); observer = null }
})

async function startPipeline() {
  isStarting.value = true
  try {
    await projectsApi.startPipeline(projectId)
    if (project.value) project.value.status = 'running'
    toast.success('Pipeline started')
    connectSSE()
    startStatusPolling()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    toast.error(err.response?.data?.detail || 'Failed to start')
  } finally {
    isStarting.value = false
  }
}

function getStatusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'completed') return 'default'
  if (status.startsWith('running')) return 'secondary'
  if (status === 'failed') return 'destructive'
  return 'outline'
}

function getStatusLabel(status: string): string {
  if (status === 'completed') return 'Completed'
  if (status === 'failed') return 'Failed'
  if (status === 'created') return 'Ready'
  if (status.startsWith('running:')) {
    const node = status.replace('running:', '')
    const nodeNames: Record<string, string> = {
      search: 'Searching',
      deduplicate: 'Deduplicating',
      filter: 'Filtering',
      bm25: 'Building index',
      embedding: 'Vectorizing',
      pgvector_knn: 'Building KNN',
      rerank: 'Reranking',
      kg_extraction: 'Extracting KG',
      community_detection: 'Detecting communities',
      visualize_community: 'Generating visualization',
      evidence_cards: 'Generating evidence cards',
      gap_analysis: 'Analyzing gaps',
      targeted_refine: 'Supplementary search',
      outline_generation: 'Generating outline',
      user_confirm: 'Awaiting confirmation',
      write_review: 'Writing review',
      coverage_audit: 'Auditing coverage',
      section_revision: 'Revising sections',
      artifact_registration: 'Registering artifacts',
      finalize: 'Finalizing',
    }
    return nodeNames[node] || `Running: ${node}`
  }
  if (status === 'running') return 'Running'
  return status
}

/** Download menu state */
const showDownloadMenu = ref(false)
const downloadMenuRef = ref<HTMLElement | null>(null)

/** Close download menu on outside click */
function onClickOutside(e: MouseEvent) {
  if (downloadMenuRef.value && !downloadMenuRef.value.contains(e.target as Node)) {
    showDownloadMenu.value = false
  }
}

/** Download topic.md - assemble from sections */
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

/** Download reference.bib - assemble from evidence cards */
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

/** Helper: trigger browser file download */
function downloadFile(filename: string, content: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** Scroll to a section by index */
function scrollToSection(idx: number) {
  const el = document.getElementById(`section-${idx}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** Scroll to references section */
function scrollToReferences() {
  const el = document.getElementById('references')
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <div class="min-h-screen bg-background">
    <!-- Top Navigation Bar -->
    <header class="border-b border-border sticky top-0 z-10 bg-background/80 backdrop-blur-sm">
      <div class="max-w-[1100px] mx-auto px-6 py-2.5 flex items-center gap-3">
        <router-link to="/console/overview" class="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>
          返回
        </router-link>
        <Separator orientation="vertical" class="h-5" />
        <h1 class="text-sm font-medium text-foreground truncate">{{ project?.name || 'Loading...' }}</h1>
        <Badge v-if="project" :variant="getStatusVariant(project.status)" class="shrink-0 text-xs">
          {{ getStatusLabel(project.status) }}
        </Badge>
        <!-- Download button -->
        <div v-if="hasReview" class="ml-auto">
          <div class="relative" ref="downloadMenuRef">
            <Button variant="outline" size="sm" class="gap-1.5 text-xs" @click="showDownloadMenu = !showDownloadMenu">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Download
            </Button>
            <div v-if="showDownloadMenu" class="absolute right-0 top-full mt-1 w-44 bg-card border border-border rounded-lg shadow-lg py-1 z-20">
              <button class="w-full px-3 py-2 text-left text-sm hover:bg-secondary transition-colors flex items-center gap-2" @click="downloadTopicMd">
                <span class="text-muted-foreground font-mono text-xs">.md</span>
                topic.md
              </button>
              <button class="w-full px-3 py-2 text-left text-sm hover:bg-secondary transition-colors flex items-center gap-2" @click="downloadReferenceBib">
                <span class="text-muted-foreground font-mono text-xs">.bib</span>
                reference.bib
              </button>
            </div>
          </div>
        </div>
      </div>
    </header>

    <!-- Loading -->
    <div v-if="isLoading" class="flex items-center justify-center py-32 text-muted-foreground text-sm">
      Loading project...
    </div>

    <main v-else-if="project" class="max-w-[1100px] mx-auto px-6">
      <!-- Running: Progress Panel -->
      <div v-if="isRunning || progressLogs.length > 0" class="my-6">
        <!-- Progress Bar -->
        <div class="border border-border rounded-xl bg-card p-5 mb-4">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <span v-if="isRunning" class="relative flex h-2 w-2">
                <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                <span class="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
              </span>
              <span class="text-sm font-medium">
                {{ isRunning ? '正在执行...' : project?.status === 'completed' ? '已完成' : '已停止' }}
              </span>
            </div>
            <span class="text-xs text-muted-foreground tabular-nums">
              {{ completedNodes.size }}/{{ pipelineStages.length }} 阶段
            </span>
          </div>

          <!-- Progress Bar -->
          <div class="progress-bar-track">
            <div
              class="progress-bar-fill"
              :class="{ 'progress-bar-failed': project?.status === 'failed' }"
              :style="{ width: Math.round((completedNodes.size / pipelineStages.length) * 100) + '%' }"
            ></div>
          </div>

          <!-- Current Stage -->
          <div class="flex items-center justify-between mt-3">
            <div class="flex items-center gap-2 text-sm">
              <template v-if="currentProgressNode">
                <span>{{ pipelineStages.find(s => s.key === currentProgressNode)?.icon }}</span>
                <span class="font-medium">{{ pipelineStages.find(s => s.key === currentProgressNode)?.label }}</span>
              </template>
              <template v-else-if="project?.status === 'completed'">
                <span>✅</span>
                <span class="font-medium">全部完成</span>
              </template>
            </div>
            <span class="text-xs text-muted-foreground">
              {{ progressMessage || '' }}
            </span>
          </div>
        </div>

        <!-- Log Panel (collapsible) -->
        <details class="border border-border rounded-xl bg-card overflow-hidden">
          <summary class="px-5 py-3 text-sm font-medium cursor-pointer hover:bg-muted/50 transition-colors">
            执行日志 ({{ progressLogs.length }})
          </summary>
          <div class="max-h-64 overflow-y-auto space-y-1 font-mono text-xs text-muted-foreground px-5 pb-4">
            <div v-for="(log, i) in progressLogs" :key="i" class="flex gap-2 py-1 border-b border-border/50 last:border-0">
              <span class="shrink-0 tabular-nums text-muted-foreground/60">{{ log.time }}</span>
              <span v-if="log.node" class="shrink-0 text-foreground/40">[{{ log.node }}]</span>
              <span class="text-foreground/70">{{ log.message }}</span>
            </div>
            <div v-if="progressLogs.length === 0" class="text-center py-4 text-muted-foreground/50">
              等待日志...
            </div>
          </div>
        </details>
      </div>

      <!-- Not started yet -->
      <div v-if="project.status === 'created'" class="my-12 text-center">
        <p class="text-muted-foreground mb-4">This project is ready to start.</p>
        <Button @click="startPipeline" :disabled="isStarting" size="lg">
          {{ isStarting ? 'Starting...' : 'Start Pipeline' }}
        </Button>
      </div>

      <!-- ============================================ -->
      <!-- Single-page Nature article layout            -->
      <!-- ============================================ -->
      <template v-if="hasReview">
        <div class="flex gap-8 py-6">
          <!-- Main Article Column -->
          <article class="flex-1 min-w-0 max-w-[780px]">
            <!-- Article Header -->
            <header class="mb-6">
              <h1 class="text-[1.65rem] md:text-[1.85rem] font-bold leading-snug tracking-tight text-foreground mb-3">
                {{ outline?.title || project.query }}
              </h1>
              <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span>{{ totalWordCount.toLocaleString() }} words</span>
                <span class="text-muted-foreground/30">·</span>
                <span>{{ sections.length }} sections</span>
                <span class="text-muted-foreground/30">·</span>
                <span>{{ evidenceCards.length }} evidence cards</span>
                <span v-if="uniqueClusters > 0" class="text-muted-foreground/30">·</span>
                <span v-if="uniqueClusters > 0">{{ uniqueClusters }} clusters</span>
                <span class="text-muted-foreground/30">·</span>
                <span>{{ project.created_at ? new Date(project.created_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }) : '' }}</span>
              </div>
            </header>

            <!-- Abstract -->
            <div v-if="articleAbstract" class="mb-8 pl-4 border-l-[3px] border-foreground/10">
              <h2 class="text-[0.65rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-1.5">Abstract</h2>
              <p class="text-[0.875rem] leading-[1.8] text-foreground/80">
                {{ articleAbstract }}
              </p>
            </div>

            <Separator class="mb-8" />

            <!-- Article Body -->
            <div class="nature-article">
              <section
                v-for="(section, idx) in sections"
                :key="section.id"
                :id="`section-${idx}`"
                class="mb-10 scroll-mt-20"
              >
                <h2 class="nature-section-heading">
                  <a :href="`#section-${idx}`" class="section-anchor" @click.prevent="scrollToSection(idx)">
                    <span class="section-num">{{ idx + 1 }}</span>
                    {{ getSectionTitle(section, idx) }}
                  </a>
                </h2>
                <div
                  class="nature-prose"
                  v-html="renderSection(section.content)"
                ></div>
              </section>
            </div>

            <!-- References Section (inline at bottom) -->
            <Separator class="my-10" />
            <section id="references" class="mb-16 scroll-mt-20">
              <h2 class="text-lg font-semibold text-foreground tracking-tight mb-6">References</h2>
              <ol class="space-y-4">
                <li
                  v-for="(ref, idx) in references"
                  :key="`${ref.paper_id || idx}-${ref.new_number || idx}`"
                  :id="`ref-${idx + 1}`"
                  class="ref-card scroll-mt-20"
                >
                  <div class="flex gap-3">
                    <span class="ref-num">{{ idx + 1 }}</span>
                    <div class="flex-1 min-w-0 space-y-1.5">
                      <p v-if="ref.title" class="text-[0.8125rem] font-medium text-foreground leading-relaxed">
                        {{ ref.title }}
                      </p>
                      <div class="flex flex-wrap gap-x-3 gap-y-1 text-[0.6875rem] text-muted-foreground">
                        <span v-if="ref.authors"><b class="text-foreground/40">Authors:</b> {{ ref.authors }}</span>
                        <span v-if="ref.venue"><b class="text-foreground/40">Venue:</b> {{ ref.venue }}</span>
                        <span v-if="ref.year"><b class="text-foreground/40">Year:</b> {{ ref.year }}</span>
                        <span v-if="ref.doi"><b class="text-foreground/40">DOI:</b> {{ ref.doi }}</span>
                      </div>
                    </div>
                  </div>
                </li>
              </ol>
            </section>
          </article>

          <!-- Sidebar: TOC -->
          <aside class="hidden md:block w-[220px] lg:w-[240px] shrink-0">
            <div class="sticky top-16 space-y-6">
              <!-- Table of Contents -->
              <div>
                <h3 class="text-[0.6rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-2.5">Contents</h3>
                <nav class="space-y-px">
                  <a
                    v-for="item in tocItems"
                    :key="item.idx"
                    :href="`#section-${item.idx}`"
                    class="toc-link"
                    :class="{ 'toc-active': activeSection === item.idx }"
                    @click.prevent="scrollToSection(item.idx)"
                  >
                    <span class="toc-num">{{ item.idx + 1 }}</span>
                    {{ item.title }}
                  </a>
                  <a
                    href="#references"
                    class="toc-link"
                    :class="{ 'toc-active': activeSection === -2 }"
                    @click.prevent="scrollToReferences"
                  >
                    <span class="toc-num">R</span>
                    References
                  </a>
                </nav>
              </div>

            </div>
          </aside>
        </div>
      </template>

      <!-- Empty state for completed but no content -->
      <div v-else-if="project.status === 'completed'" class="text-center py-20">
        <div class="text-muted-foreground/60 mb-2">
          <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="mx-auto"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
        </div>
        <p class="text-foreground font-medium">No review content yet</p>
        <p class="text-sm text-muted-foreground mt-1">The pipeline completed but no sections were generated.</p>
      </div>
    </main>
  </div>
</template>

<style scoped>
/* ============================================ */
/* Nature-style section headings                */
/* ============================================ */
.nature-section-heading {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--foreground);
  margin-bottom: 0.75rem;
  letter-spacing: -0.01em;
  line-height: 1.35;
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}

.section-num {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--muted-foreground);
  opacity: 0.5;
  min-width: 1.25rem;
}

.section-anchor {
  color: inherit;
  text-decoration: none;
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  transition: opacity 0.15s;
}

.section-anchor:hover {
  opacity: 0.75;
}

.section-anchor:hover .section-num {
  opacity: 0.8;
}

/* ============================================ */
/* Nature-style prose rendering                 */
/* ============================================ */
.nature-prose :deep(h1) {
  font-size: 1.375rem;
  font-weight: 700;
  margin-top: 2rem;
  margin-bottom: 0.625rem;
  color: var(--foreground);
  letter-spacing: -0.02em;
  line-height: 1.3;
}

.nature-prose :deep(h2) {
  font-size: 1.125rem;
  font-weight: 600;
  margin-top: 1.5rem;
  margin-bottom: 0.5rem;
  color: var(--foreground);
  letter-spacing: -0.01em;
  line-height: 1.35;
}

.nature-prose :deep(h3) {
  font-size: 1rem;
  font-weight: 600;
  margin-top: 1.25rem;
  margin-bottom: 0.375rem;
  color: var(--foreground);
}

.nature-prose :deep(p) {
  font-size: 0.875rem;
  line-height: 1.85;
  margin-bottom: 0.875rem;
  color: var(--foreground);
  text-align: justify;
}

.nature-prose :deep(ul),
.nature-prose :deep(ol) {
  font-size: 0.875rem;
  line-height: 1.75;
  margin-bottom: 0.875rem;
  padding-left: 1.5em;
  color: var(--foreground);
}

.nature-prose :deep(li) {
  margin-bottom: 0.25rem;
}

.nature-prose :deep(strong) {
  font-weight: 600;
  color: var(--foreground);
}

.nature-prose :deep(em) {
  font-style: italic;
}

.nature-prose :deep(blockquote) {
  border-left: 2px solid var(--border);
  padding-left: 1rem;
  margin: 1rem 0;
  color: var(--muted-foreground);
  font-style: italic;
  font-size: 0.875rem;
}

.nature-prose :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 1.25rem 0;
  font-size: 0.8125rem;
}

.nature-prose :deep(th) {
  background: var(--muted);
  font-weight: 600;
  text-align: left;
  padding: 0.5rem 0.625rem;
  border: 1px solid var(--border);
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--muted-foreground);
}

.nature-prose :deep(td) {
  padding: 0.375rem 0.625rem;
  border: 1px solid var(--border);
  vertical-align: top;
}

.nature-prose :deep(tr:nth-child(even)) {
  background: var(--muted);
}

.nature-prose :deep(hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: 1.5rem 0;
}

.nature-prose :deep(a) {
  color: var(--foreground);
  text-decoration: underline;
  text-underline-offset: 2px;
  text-decoration-color: var(--border);
}

.nature-prose :deep(a:hover) {
  text-decoration-color: var(--foreground);
}

.nature-prose :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.8em;
  background: var(--muted);
  padding: 0.1em 0.35em;
  border-radius: 3px;
}

.nature-prose :deep(pre) {
  background: var(--muted);
  padding: 0.875rem;
  border-radius: 6px;
  overflow-x: auto;
  margin: 1rem 0;
  border: 1px solid var(--border);
}

.nature-prose :deep(pre code) {
  background: transparent;
  padding: 0;
  font-size: 0.8rem;
  line-height: 1.6;
}

.nature-prose :deep(img) {
  max-width: 100%;
  border-radius: 6px;
  margin: 0.75rem 0;
}

/* Citation superscript links */
.nature-prose :deep(sup.cite-ref) {
  font-size: 0.7em;
  line-height: 0;
  position: relative;
  vertical-align: baseline;
  top: -0.45em;
}

.nature-prose :deep(sup.cite-ref a) {
  color: var(--foreground);
  text-decoration: none;
  font-weight: 500;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.nature-prose :deep(sup.cite-ref a:hover) {
  opacity: 1;
  text-decoration: underline;
}

/* ============================================ */
/* Table of Contents sidebar                    */
/* ============================================ */
.toc-link {
  display: flex;
  align-items: baseline;
  gap: 0.375rem;
  padding: 0.25rem 0;
  font-size: 0.75rem;
  line-height: 1.45;
  color: var(--muted-foreground);
  text-decoration: none;
  transition: color 0.15s;
  border-left: 2px solid transparent;
  padding-left: 0.5rem;
}

.toc-link:hover {
  color: var(--foreground);
  border-left-color: var(--border);
}

.toc-active {
  color: var(--foreground);
  font-weight: 500;
  border-left-color: var(--foreground);
  background: var(--muted);
  border-radius: 0 4px 4px 0;
}

.toc-num {
  font-family: var(--font-mono);
  font-size: 0.65rem;
  opacity: 0.45;
  min-width: 1rem;
  flex-shrink: 0;
}

/* ============================================ */
/* Reference cards                              */
/* ============================================ */
.ref-card {
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--border);
}

.ref-card:last-child {
  border-bottom: none;
}

.ref-num {
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  color: var(--muted-foreground);
  opacity: 0.45;
  min-width: 1.5rem;
  text-align: right;
  flex-shrink: 0;
  padding-top: 0.125rem;
}

.ref-quote {
  border-left: 2px solid var(--border);
  padding-left: 0.625rem;
  font-style: italic;
}

/* ============================================ */
/* Pipeline progress bar                        */
/* ============================================ */
.progress-bar-track {
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: var(--muted);
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  border-radius: 3px;
  background: oklch(0.65 0.15 145);
  transition: width 0.6s ease;
}

.progress-bar-failed {
  background: oklch(0.65 0.15 25);
}

.stage-icon {
  font-size: 0.875rem;
}
</style>
