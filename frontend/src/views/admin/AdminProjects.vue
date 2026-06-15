<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { adminApi, type ProjectAdmin } from '@/api/admin'
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
const projects = ref<ProjectAdmin[]>([])
const total = ref(0)
const isLoading = ref(true)
const deletingId = ref<string | null>(null)

onMounted(async () => {
  await loadProjects()
})

async function loadProjects() {
  isLoading.value = true
  try {
    const data = await adminApi.listAllProjects({ skip: 0, limit: 200 })
    projects.value = data.projects
    total.value = data.total
  } catch {
    // ignore
  } finally {
    isLoading.value = false
  }
}

async function handleDelete(id: string, name: string) {
  if (!confirm(`确定删除项目「${name}」？此操作不可撤销。`)) return
  deletingId.value = id
  try {
    await adminApi.deleteProject(id)
    projects.value = projects.value.filter(p => p.id !== id)
    total.value--
  } catch (e) {
    alert('删除失败')
  } finally {
    deletingId.value = null
  }
}

function getStatusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'completed') return 'default'
  if (status.startsWith('running')) return 'secondary'
  if (status === 'failed') return 'destructive'
  return 'outline'
}
</script>

<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">项目管理</h2>
        <p class="text-sm text-muted-foreground mt-1">共 {{ total }} 个项目</p>
      </div>
    </div>

    <div v-if="isLoading" class="text-center py-16 text-muted-foreground">加载中...</div>

    <Card v-else class="border border-border shadow-[var(--shadow-sm)]">
      <CardContent class="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>名称</TableHead>
              <TableHead>查询词</TableHead>
              <TableHead>用户</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>创建时间</TableHead>
              <TableHead>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="p in projects" :key="p.id">
              <TableCell class="font-medium">{{ p.name }}</TableCell>
              <TableCell class="text-muted-foreground max-w-[200px] truncate">{{ p.query }}</TableCell>
              <TableCell class="text-muted-foreground text-sm">{{ p.user_email || '-' }}</TableCell>
              <TableCell>
                <Badge :variant="getStatusVariant(p.status)" class="text-[0.65rem]">
                  {{ p.status }}
                </Badge>
              </TableCell>
              <TableCell class="text-muted-foreground">
                {{ p.created_at ? new Date(p.created_at).toLocaleDateString() : '-' }}
              </TableCell>
              <TableCell class="space-x-2">
                <Button variant="ghost" size="sm" @click="router.push(`/projects/${p.id}`)">
                  查看
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  class="text-destructive hover:text-destructive"
                  :disabled="deletingId === p.id"
                  @click="handleDelete(p.id, p.name)"
                >
                  {{ deletingId === p.id ? '删除中...' : '删除' }}
                </Button>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  </div>
</template>
