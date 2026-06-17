<script setup lang="ts">
import { shallowRef, ref, onMounted } from 'vue'
import { useI18n } from '@/i18n'
import { formatTokens } from '@/lib/utils'
import { adminApi, type AdminOverview, type SourceConfigItem } from '@/api/admin'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

const { t } = useI18n()

const overview = shallowRef<AdminOverview | null>(null)
const sources = ref<SourceConfigItem[]>([])
const isLoading = shallowRef(true)

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
</script>

<template>
  <div class="p-4 md:p-8">
    <h2 class="text-heading font-medium tracking-tight mb-6 md:mb-8">{{ t('admin.systemOverview') }}</h2>

    <div v-if="isLoading" class="text-center py-16 text-muted-foreground">{{ t('common.loading') }}</div>

    <template v-else>
      <!-- Stats Cards -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-5 mb-8">
        <Card class="border border-border shadow-[var(--shadow-sm)]">
          <CardHeader class="pb-2">
            <CardTitle class="text-caption text-muted-foreground font-normal">{{ t('admin.totalUsers') }}</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-2xl font-semibold tracking-tight">{{ overview?.total_users || 0 }}</p>
            <p class="text-[0.65rem] text-muted-foreground mt-0.5">{{ t('admin.activeUsers', { count: overview?.active_users || 0 }) }}</p>
          </CardContent>
        </Card>
        <Card class="border border-border shadow-[var(--shadow-sm)]">
          <CardHeader class="pb-2">
            <CardTitle class="text-caption text-muted-foreground font-normal">{{ t('admin.totalProjects') }}</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-2xl font-semibold tracking-tight">{{ overview?.total_projects || 0 }}</p>
            <p class="text-[0.65rem] text-muted-foreground mt-0.5">{{ t('admin.runningProjects', { count: overview?.running_projects || 0 }) }}</p>
          </CardContent>
        </Card>
        <Card class="border border-border shadow-[var(--shadow-sm)]">
          <CardHeader class="pb-2">
            <CardTitle class="text-caption text-muted-foreground font-normal">{{ t('admin.llmCalls') }}</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-2xl font-semibold tracking-tight">{{ overview?.total_llm_calls || 0 }}</p>
            <p class="text-[0.65rem] text-muted-foreground mt-0.5">{{ t('admin.totalTokens', { count: formatTokens(overview?.total_tokens || 0) }) }}</p>
          </CardContent>
        </Card>
        <Card class="border border-border shadow-[var(--shadow-sm)]">
          <CardHeader class="pb-2">
            <CardTitle class="text-caption text-muted-foreground font-normal">{{ t('admin.totalCost') }}</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-2xl font-semibold tracking-tight">${{ (overview?.total_cost || 0).toFixed(2) }}</p>
            <p class="text-[0.65rem] text-muted-foreground mt-0.5">{{ t('admin.totalRuns', { count: overview?.total_runs || 0 }) }}</p>
          </CardContent>
        </Card>
      </div>

      <!-- Provider Status -->
      <Card class="border border-border shadow-[var(--shadow-sm)] mb-6">
        <CardHeader>
          <CardTitle class="text-base">{{ t('admin.providerStatus') }}</CardTitle>
        </CardHeader>
        <CardContent>
          <div v-if="!overview?.providers || overview.providers.length === 0" class="text-sm text-muted-foreground">
            {{ t('admin.noProviderConfig') }}
          </div>
          <div v-else class="space-y-2">
            <div
              v-for="p in overview.providers"
              :key="p.id"
              class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 rounded-lg border border-border"
            >
              <div class="flex items-center gap-3 min-w-0">
                <Badge :variant="p.status === 'healthy' ? 'default' : p.status === 'error' ? 'destructive' : 'outline'" class="text-[0.65rem] shrink-0">
                  {{ p.status }}
                </Badge>
                <span class="text-sm font-medium truncate">{{ p.name }}</span>
              </div>
              <div class="text-xs text-muted-foreground shrink-0">
                {{ t('admin.callsCount', { count: p.total_calls, cost: p.total_cost.toFixed(4) }) }}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <!-- Data Sources -->
      <Card class="border border-border shadow-[var(--shadow-sm)] mb-6">
        <CardHeader>
          <CardTitle class="text-base">{{ t('admin.dataSourceConfig') }}</CardTitle>
        </CardHeader>
        <CardContent>
          <div v-if="sources.length === 0" class="text-sm text-muted-foreground">{{ t('common.loading') }}</div>
          <div v-else class="space-y-2">
            <div
              v-for="s in sources"
              :key="s.key"
              class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 py-2 border-b border-border last:border-0"
            >
              <div class="min-w-0">
                <p class="text-sm font-medium truncate">{{ s.label }}</p>
                <p class="text-[0.65rem] text-muted-foreground">{{ s.description }}</p>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <span class="text-xs font-mono text-muted-foreground truncate max-w-[160px]">{{ s.value || t('common.unset') }}</span>
                <Badge :variant="s.is_set ? 'default' : 'outline'" class="text-[0.65rem] shrink-0">
                  {{ s.is_set ? t('common.configured') : t('common.unconfigured') }}
                </Badge>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <!-- Recent Activity -->
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader>
          <CardTitle class="text-base">{{ t('admin.recentActivity') }}</CardTitle>
        </CardHeader>
        <CardContent>
          <div v-if="!overview?.recent_activities || overview.recent_activities.length === 0" class="text-sm text-muted-foreground">
            {{ t('admin.noActivity') }}
          </div>
          <div v-else class="space-y-2">
            <div
              v-for="a in overview.recent_activities"
              :key="a.id"
              class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 py-2 border-b border-border last:border-0"
            >
              <div class="flex items-center gap-3 min-w-0">
                <Badge variant="outline" class="text-[0.65rem] shrink-0">{{ a.action }}</Badge>
                <span class="text-sm text-muted-foreground truncate">{{ a.resource_type || '' }}</span>
              </div>
              <span class="text-xs text-muted-foreground shrink-0">
                {{ a.created_at ? new Date(a.created_at).toLocaleString() : '' }}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>
    </template>
  </div>
</template>
