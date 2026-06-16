<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { projectsApi, type Project } from '@/api/projects'
import { consoleApi } from '@/api/console'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const router = useRouter()
const projects = ref<Project[]>([])
const total = ref(0)
const isLoading = ref(true)
const actionLoading = ref<string | null>(null)

onMounted(async () => {
  await loadProjects()
})

async function loadProjects() {
  isLoading.value = true
  try {
    const data = await projectsApi.listProjects()
    projects.value = data.projects
    total.value = data.total
  } catch {
    // ignore
  } finally {
    isLoading.value = false
  }
}

function getStatusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'completed') return 'default'
  if (status.startsWith('running')) return 'secondary'
  if (status === 'failed') return 'destructive'
  return 'outline'
}

function isRunning(status: string): boolean {
  return status.startsWith('running')
}

function showResume(status: string): boolean {
  return status === 'interrupted' || status === 'failed'
}

async function handlePause(projectId: string) {
  actionLoading.value = projectId
  try {
    await consoleApi.controlPipeline(projectId, 'pause')
    await loadProjects()
  } catch {
    alert('暂停失败')
  } finally {
    actionLoading.value = null
  }
}

async function handleResume(projectId: string) {
  actionLoading.value = projectId
  try {
    await consoleApi.controlPipeline(projectId, 'resume')
    await loadProjects()
  } catch {
    alert('恢复失败')
  } finally {
    actionLoading.value = null
  }
}

async function handleDelete(projectId: string, name: string) {
  if (!confirm(`确定删除项目「${name}」及其全部调用记录？此操作不可撤销。`)) return
  actionLoading.value = projectId
  try {
    await projectsApi.deleteProject(projectId)
    projects.value = projects.value.filter(p => p.id !== projectId)
    total.value--
  } catch {
    alert('删除失败')
  } finally {
    actionLoading.value = null
  }
}
</script>

<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">我的项目</h2>
        <p class="text-sm text-muted-foreground mt-1">共 {{ total }} 个项目</p>
      </div>
      <router-link to="/projects/new">
        <Button>新建项目</Button>
      </router-link>
    </div>

    <div v-if="isLoading" class="text-center py-16 text-muted-foreground">加载中...</div>

    <div v-else-if="projects.length === 0" class="text-center py-16">
      <p class="text-muted-foreground mb-5 text-body">暂无项目</p>
      <router-link to="/projects/new">
        <Button variant="outline">创建第一个项目</Button>
      </router-link>
    </div>

    <Card v-else class="border border-border shadow-[var(--shadow-sm)]">
      <CardContent class="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>名称</TableHead>
              <TableHead>查询词</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>创建时间</TableHead>
              <TableHead>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="p in projects" :key="p.id">
              <TableCell class="font-medium">{{ p.name }}</TableCell>
              <TableCell class="text-muted-foreground max-w-[200px] truncate">{{ p.query }}</TableCell>
              <TableCell>
                <Badge :variant="getStatusVariant(p.status)" class="text-[0.65rem]">
                  {{ p.status }}
                </Badge>
              </TableCell>
              <TableCell class="text-muted-foreground text-sm">
                {{ p.created_at ? new Date(p.created_at).toLocaleDateString() : '-' }}
              </TableCell>
              <TableCell class="space-x-2">
                <Button variant="ghost" size="sm" @click="router.push(`/projects/${p.id}`)">
                  查看
                </Button>
                <Button
                  v-if="isRunning(p.status)"
                  variant="ghost"
                  size="sm"
                  :disabled="actionLoading === p.id"
                  @click="handlePause(p.id)"
                >
                  {{ actionLoading === p.id ? '处理中...' : '暂停' }}
                </Button>
                <Button
                  v-if="showResume(p.status)"
                  variant="ghost"
                  size="sm"
                  :disabled="actionLoading === p.id"
                  @click="handleResume(p.id)"
                >
                  {{ actionLoading === p.id ? '处理中...' : '恢复' }}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  class="text-destructive hover:text-destructive"
                  :disabled="actionLoading === p.id"
                  @click="handleDelete(p.id, p.name)"
                >
                  {{ actionLoading === p.id ? '处理中...' : '删除' }}
                </Button>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  </div>
</template>
