<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminApi, type AdminOverview, type SourceConfigItem } from '@/api/admin'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

const overview = ref<AdminOverview | null>(null)
const sources = ref<SourceConfigItem[]>([])
const isLoading = ref(true)

onMounted(async () => {
  try {
    const [overviewData, sourceData] = await Promise.all([
      adminApi.getOverview(),
      adminApi.getSourceConfigs(),
    ])
    overview.value = overviewData
    sources.value = sourceData
  } catch {
    // ignore
  } finally {
    isLoading.value = false
  }
})

function formatTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}
</script>

<template>
  <div class="p-8">
    <h2 class="text-heading font-medium tracking-tight mb-8">系统概览</h2>

    <div v-if="isLoading" class="text-center py-16 text-muted-foreground">加载中...</div>

    <template v-else>
      <!-- Stats Cards -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-5 mb-8">
        <Card class="border border-border shadow-[var(--shadow-sm)]">
          <CardHeader class="pb-2">
            <CardTitle class="text-caption text-muted-foreground font-normal">总用户数</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-2xl font-semibold tracking-tight">{{ overview?.total_users || 0 }}</p>
            <p class="text-[0.65rem] text-muted-foreground mt-0.5">活跃 {{ overview?.active_users || 0 }}</p>
          </CardContent>
        </Card>
        <Card class="border border-border shadow-[var(--shadow-sm)]">
          <CardHeader class="pb-2">
            <CardTitle class="text-caption text-muted-foreground font-normal">总项目数</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-2xl font-semibold tracking-tight">{{ overview?.total_projects || 0 }}</p>
            <p class="text-[0.65rem] text-muted-foreground mt-0.5">运行中 {{ overview?.running_projects || 0 }}</p>
          </CardContent>
        </Card>
        <Card class="border border-border shadow-[var(--shadow-sm)]">
          <CardHeader class="pb-2">
            <CardTitle class="text-caption text-muted-foreground font-normal">LLM 调用</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-2xl font-semibold tracking-tight">{{ overview?.total_llm_calls || 0 }}</p>
            <p class="text-[0.65rem] text-muted-foreground mt-0.5">{{ formatTokens(overview?.total_tokens || 0) }} tokens</p>
          </CardContent>
        </Card>
        <Card class="border border-border shadow-[var(--shadow-sm)]">
          <CardHeader class="pb-2">
            <CardTitle class="text-caption text-muted-foreground font-normal">总花费</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-2xl font-semibold tracking-tight">${{ (overview?.total_cost || 0).toFixed(2) }}</p>
            <p class="text-[0.65rem] text-muted-foreground mt-0.5">{{ overview?.total_runs || 0 }} 次运行</p>
          </CardContent>
        </Card>
      </div>

      <!-- Provider Status -->
      <Card class="border border-border shadow-[var(--shadow-sm)] mb-6">
        <CardHeader>
          <CardTitle class="text-base">Provider 状态</CardTitle>
        </CardHeader>
        <CardContent>
          <div v-if="!overview?.providers || overview.providers.length === 0" class="text-sm text-muted-foreground">
            暂无 Provider 配置，前往 Provider 管理添加
          </div>
          <div v-else class="space-y-2">
            <div
              v-for="p in overview.providers"
              :key="p.id"
              class="flex items-center justify-between p-3 rounded-lg border border-border"
            >
              <div class="flex items-center gap-3">
                <Badge :variant="p.status === 'healthy' ? 'default' : p.status === 'error' ? 'destructive' : 'outline'" class="text-[0.65rem]">
                  {{ p.status }}
                </Badge>
                <span class="text-sm font-medium">{{ p.name }}</span>
              </div>
              <div class="text-xs text-muted-foreground">
                {{ p.total_calls }} 次调用 · ${{ p.total_cost.toFixed(4) }}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <!-- Data Sources -->
      <Card class="border border-border shadow-[var(--shadow-sm)] mb-6">
        <CardHeader>
          <CardTitle class="text-base">数据源配置</CardTitle>
        </CardHeader>
        <CardContent>
          <div v-if="sources.length === 0" class="text-sm text-muted-foreground">加载中...</div>
          <div v-else class="space-y-2">
            <div
              v-for="s in sources"
              :key="s.key"
              class="flex items-center justify-between py-2 border-b border-border last:border-0"
            >
              <div>
                <p class="text-sm font-medium">{{ s.label }}</p>
                <p class="text-[0.65rem] text-muted-foreground">{{ s.description }}</p>
              </div>
              <div class="flex items-center gap-2">
                <span class="text-xs font-mono text-muted-foreground">{{ s.value || '未设置' }}</span>
                <Badge :variant="s.is_set ? 'default' : 'outline'" class="text-[0.65rem]">
                  {{ s.is_set ? '已配置' : '未配置' }}
                </Badge>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <!-- Recent Activity -->
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader>
          <CardTitle class="text-base">最近活动</CardTitle>
        </CardHeader>
        <CardContent>
          <div v-if="!overview?.recent_activities || overview.recent_activities.length === 0" class="text-sm text-muted-foreground">
            暂无活动记录
          </div>
          <div v-else class="space-y-2">
            <div
              v-for="a in overview.recent_activities"
              :key="a.id"
              class="flex items-center justify-between py-2 border-b border-border last:border-0"
            >
              <div class="flex items-center gap-3">
                <Badge variant="outline" class="text-[0.65rem]">{{ a.action }}</Badge>
                <span class="text-sm text-muted-foreground">{{ a.resource_type || '' }}</span>
              </div>
              <span class="text-xs text-muted-foreground">
                {{ a.created_at ? new Date(a.created_at).toLocaleString() : '' }}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>
    </template>
  </div>
</template>
