<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { consoleApi, type ConsoleOverview as ConsoleOverviewData } from '@/api/console'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

const router = useRouter()
const { user } = useAuth()

const overview = ref<ConsoleOverviewData | null>(null)
const isLoading = ref(true)

onMounted(async () => {
  try {
    overview.value = await consoleApi.getOverview()
  } catch {
    // ignore
  } finally {
    isLoading.value = false
  }
})

function getStatusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'completed': return 'default'
    case 'running': return 'secondary'
    case 'failed': return 'destructive'
    default: return 'outline'
  }
}
</script>

<template>
  <div class="p-8">
    <!-- Welcome -->
    <div class="mb-8">
      <h2 class="text-heading font-medium tracking-tight">欢迎回来</h2>
      <p class="text-sm text-muted-foreground mt-1">{{ user?.full_name || user?.email }}</p>
    </div>

    <!-- Stats -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-5 mb-8">
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">我的项目</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-2xl font-semibold tracking-tight">{{ overview?.project_count ?? 0 }}</p>
        </CardContent>
      </Card>
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">运行中</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-2xl font-semibold tracking-tight">{{ overview?.running_projects ?? 0 }}</p>
        </CardContent>
      </Card>
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">总论文数</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-2xl font-semibold tracking-tight">{{ overview?.total_papers ?? 0 }}</p>
        </CardContent>
      </Card>
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">Token 消耗</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-2xl font-semibold tracking-tight">{{ (overview?.total_tokens ?? 0).toLocaleString() }}</p>
          <p class="text-[0.65rem] text-muted-foreground mt-0.5">费用 ${{ (overview?.total_cost ?? 0).toFixed(4) }}</p>
        </CardContent>
      </Card>
    </div>

    <!-- Recent Projects -->
    <div class="mb-8">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-base font-medium">最近项目</h3>
        <router-link to="/console/projects">
          <Button variant="ghost" size="sm">查看全部</Button>
        </router-link>
      </div>

      <div v-if="isLoading" class="text-center py-8 text-muted-foreground text-sm">加载中...</div>

      <div v-else-if="!overview || overview.recent_projects.length === 0" class="text-center py-8">
        <p class="text-muted-foreground text-sm mb-4">暂无项目</p>
        <router-link to="/projects/new">
          <Button size="sm">创建第一个项目</Button>
        </router-link>
      </div>

      <div v-else class="space-y-2">
        <div
          v-for="project in overview.recent_projects"
          :key="project.id"
          class="flex items-center justify-between p-3 rounded-lg border border-border hover:bg-muted/50 cursor-pointer transition-colors"
          @click="router.push(`/projects/${project.id}`)"
        >
          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium truncate">{{ project.name }}</p>
          </div>
          <div class="flex items-center gap-3 shrink-0 ml-4">
            <Badge :variant="getStatusVariant(project.status)" class="text-[0.65rem]">
              {{ project.status }}
            </Badge>
            <span class="text-caption text-muted-foreground">
              {{ project.created_at ? new Date(project.created_at).toLocaleDateString() : '' }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Quick Actions -->
    <div>
      <h3 class="text-base font-medium mb-4">快捷操作</h3>
      <div class="flex gap-3">
        <router-link to="/projects/new">
          <Button>新建项目</Button>
        </router-link>
        <router-link to="/console/usage">
          <Button variant="outline">查看用量</Button>
        </router-link>
        <router-link to="/console/recharge">
          <Button variant="outline" disabled>充值（暂未开放）</Button>
        </router-link>
      </div>
    </div>
  </div>
</template>
