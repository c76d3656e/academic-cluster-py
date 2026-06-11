<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { projectsApi, type Project } from '../api/projects'
import { marked } from 'marked'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Separator } from '@/components/ui/separator'
import { toast } from 'vue-sonner'

const route = useRoute()
const router = useRouter()
const projectId = route.params.id as string

const project = ref<Project | null>(null)
const review = ref<string | null>(null)
const bibtex = ref<string | null>(null)
const isLoading = ref(true)
const isStarting = ref(false)

// SSE 进度相关
const progressLogs = ref<Array<{ time: string; node: string; message: string }>>([])
const currentProgressNode = ref('')
const progressMessage = ref('')
let eventSource: EventSource | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null

const renderedReview = computed(() => {
  if (!review.value) return ''
  return marked(review.value) as string
})

const isRunning = computed(() => {
  const s = project.value?.status || ''
  return s.startsWith('running') || s === 'running'
})

function formatTime(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function connectSSE() {
  if (eventSource) return

  const baseUrl = import.meta.env.VITE_API_URL || '/api'
  const url = `${baseUrl}/stream/${projectId}`

  eventSource = new EventSource(url)

  eventSource.addEventListener('connected', () => {
    progressLogs.value.push({ time: formatTime(), node: 'system', message: '已连接到实时进度流' })
  })

  eventSource.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data)
    currentProgressNode.value = data.node || ''
    progressMessage.value = data.message || ''

    if (data.message) {
      progressLogs.value.push({
        time: formatTime(),
        node: data.node || '',
        message: data.message,
      })
    }

    // 更新项目状态
    if (project.value && data.node) {
      project.value.status = `running:${data.node}`
    }
  })

  eventSource.addEventListener('complete', () => {
    progressLogs.value.push({ time: formatTime(), node: 'system', message: 'Pipeline 完成!' })
    if (project.value) {
      project.value.status = 'completed'
    }
    // 加载综述数据
    loadReview()
    disconnectSSE()
  })

  eventSource.addEventListener('error', (e) => {
    if (e instanceof MessageEvent) {
      try {
        const errData = JSON.parse(e.data)
        progressLogs.value.push({ time: formatTime(), node: 'error', message: `错误: ${errData.message}` })
      } catch {
        // ignore parse errors
      }
    }
  })

  eventSource.onerror = () => {
    // 连接断开，停止 SSE
    disconnectSSE()
  }
}

function disconnectSSE() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

function startStatusPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    try {
      const status = await projectsApi.getProjectStatus(projectId)
      if (project.value) {
        project.value.status = status.status
      }
      if (status.status === 'completed' || status.status === 'failed') {
        stopStatusPolling()
        loadReview()
      }
    } catch {
      // ignore
    }
  }, 5000)
}

function stopStatusPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function loadReview() {
  try {
    const reviewData = await projectsApi.getReview(projectId)
    review.value = reviewData.review
    bibtex.value = reviewData.bibtex
  } catch {
    // review 可能还没有
  }
}

onMounted(async () => {
  try {
    project.value = await projectsApi.getProject(projectId)

    // 如果正在运行，连接 SSE 并开始轮询
    if (isRunning.value) {
      connectSSE()
      startStatusPolling()
    }

    // 尝试加载已有综述
    await loadReview()
  } catch {
    router.push('/')
  } finally {
    isLoading.value = false
  }
})

onUnmounted(() => {
  disconnectSSE()
  stopStatusPolling()
})

async function startPipeline() {
  isStarting.value = true
  try {
    await projectsApi.startPipeline(projectId)
    if (project.value) {
      project.value.status = 'running'
    }
    toast.success('Pipeline 已启动')
    // 连接 SSE 监听进度
    connectSSE()
    startStatusPolling()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    toast.error(err.response?.data?.detail || '启动失败')
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
  if (status === 'completed') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'created') return '待启动'
  if (status.startsWith('running:')) {
    const node = status.replace('running:', '')
    const nodeNames: Record<string, string> = {
      search: '搜索中',
      deduplicate: '去重中',
      filter: '筛选中',
      bm25: '索引构建中',
      embedding: '向量化中',
      pgvector_knn: 'KNN 构建中',
      rerank: '重排序中',
      kg_extraction: '知识图谱提取中',
      community_detection: '社区检测中',
      visualize_community: '可视化生成中',
      evidence_cards: '证据卡片生成中',
      gap_analysis: '差距分析中',
      targeted_refine: '补充搜索中',
      outline_generation: '大纲生成中',
      user_confirm: '等待确认',
      write_review: '综述撰写中',
      coverage_audit: '覆盖审计中',
      section_revision: '章节修订中',
      artifact_registration: '产出注册中',
      finalize: '最终处理中',
    }
    return nodeNames[node] || `运行中: ${node}`
  }
  if (status === 'running') return '运行中'
  return status
}
</script>

<template>
  <div class="min-h-screen bg-muted/30">
    <header class="bg-background border-b sticky top-0 z-10">
      <div class="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3">
        <router-link to="/">
          <Button variant="ghost" size="sm">&larr; 返回</Button>
        </router-link>
        <h1 class="text-lg font-semibold truncate">{{ project?.name || '加载中...' }}</h1>
        <Badge v-if="project" :variant="getStatusVariant(project.status)" class="shrink-0">
          {{ getStatusLabel(project.status) }}
        </Badge>
      </div>
    </header>

    <div v-if="isLoading" class="text-center py-12 text-muted-foreground">加载中...</div>

    <main v-else-if="project" class="max-w-7xl mx-auto px-4 py-8">
      <!-- 操作栏 -->
      <div v-if="project.status === 'created'" class="mb-6">
        <Button @click="startPipeline" :disabled="isStarting" variant="default">
          {{ isStarting ? '启动中...' : '启动 Pipeline' }}
        </Button>
      </div>

      <!-- 实时进度面板 -->
      <Card v-if="isRunning || progressLogs.length > 0" class="mb-6">
        <CardHeader>
          <CardTitle class="flex items-center gap-2">
            <span v-if="isRunning" class="relative flex h-2 w-2">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
              <span class="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
            </span>
            实时进度
          </CardTitle>
        </CardHeader>
        <CardContent>
          <!-- 当前状态 -->
          <div v-if="isRunning && progressMessage" class="mb-3 p-3 bg-blue-50 dark:bg-blue-950 rounded-lg border border-blue-200 dark:border-blue-800">
            <p class="text-sm font-medium text-blue-700 dark:text-blue-300">
              {{ progressMessage }}
            </p>
          </div>

          <!-- 进度日志 -->
          <div class="max-h-64 overflow-y-auto space-y-1 font-mono text-xs">
            <div
              v-for="(log, i) in progressLogs"
              :key="i"
              class="flex gap-2 py-1 border-b border-muted last:border-0"
            >
              <span class="text-muted-foreground shrink-0">{{ log.time }}</span>
              <span v-if="log.node" class="text-blue-600 dark:text-blue-400 shrink-0">[{{ log.node }}]</span>
              <span>{{ log.message }}</span>
            </div>
          </div>
        </CardContent>
      </Card>

      <!-- Tabs -->
      <Tabs default-value="overview" class="w-full">
        <TabsList>
          <TabsTrigger value="overview">概览</TabsTrigger>
          <TabsTrigger value="review">综述</TabsTrigger>
          <TabsTrigger value="bibtex">参考文献</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <Card>
            <CardHeader>
              <CardTitle>项目信息</CardTitle>
            </CardHeader>
            <CardContent class="space-y-4">
              <div>
                <p class="text-sm text-muted-foreground">研究主题</p>
                <p class="mt-1">{{ project.query }}</p>
              </div>
              <Separator />
              <div v-if="project.description">
                <p class="text-sm text-muted-foreground">描述</p>
                <p class="mt-1">{{ project.description }}</p>
                <Separator class="mt-4" />
              </div>
              <div>
                <p class="text-sm text-muted-foreground">状态</p>
                <p class="mt-1">{{ getStatusLabel(project.status) }}</p>
              </div>
              <Separator />
              <div v-if="project.created_at">
                <p class="text-sm text-muted-foreground">创建时间</p>
                <p class="mt-1">{{ new Date(project.created_at).toLocaleString() }}</p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="review">
          <Card>
            <CardHeader>
              <CardTitle>综述</CardTitle>
            </CardHeader>
            <CardContent>
              <div v-if="review" class="prose max-w-none" v-html="renderedReview"></div>
              <div v-else class="text-center py-12 text-muted-foreground">
                <p>综述内容尚未生成</p>
                <p class="text-sm mt-2">请先启动 Pipeline 并等待完成</p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="bibtex">
          <Card>
            <CardHeader>
              <CardTitle>参考文献</CardTitle>
            </CardHeader>
            <CardContent>
              <div v-if="bibtex">
                <pre class="bg-muted p-4 rounded-lg text-sm overflow-x-auto whitespace-pre-wrap">{{ bibtex }}</pre>
              </div>
              <div v-else class="text-center py-12 text-muted-foreground">
                <p>参考文献尚未生成</p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </main>
  </div>
</template>
