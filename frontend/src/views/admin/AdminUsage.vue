<script setup lang="ts">
import { shallowRef, ref, watch, onMounted, computed } from 'vue'
import { useI18n } from '@/i18n'
import { formatTokens } from '@/lib/utils'
import { adminApi, type DailyUsage, type UsageByProvider, type LlmCallRecord } from '@/api/admin'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import UsageTrendChart from '@/components/usage/UsageTrendChart.vue'
import { callTypeBadgeClass, callTypeLabel } from '@/lib/usage-display'

const { t } = useI18n()

const days = shallowRef(7)
const trend = ref<DailyUsage[]>([])
const byProvider = ref<UsageByProvider[]>([])
const calls = ref<LlmCallRecord[]>([])
const isLoading = shallowRef(true)

async function loadAll() {
  isLoading.value = true
  try {
    const [trendData, providerData, callData] = await Promise.all([
      adminApi.getUsageTrend(days.value),
      adminApi.getUsageByProvider(days.value),
      adminApi.getRecentCalls({ limit: 50 }),
    ])
    trend.value = trendData
    byProvider.value = providerData
    calls.value = callData
  } catch {
    trend.value = []
    byProvider.value = []
    calls.value = []
  } finally {
    isLoading.value = false
  }
}

watch(days, loadAll)
onMounted(loadAll)

function formatCost(n: number): string {
  if (n >= 1) return '$' + n.toFixed(2)
  if (n >= 0.01) return '$' + n.toFixed(4)
  return '$' + n.toFixed(6)
}

const totalPromptTokens = computed(() => trend.value.reduce((s, d) => s + d.prompt_tokens, 0))
const totalCompletionTokens = computed(() => trend.value.reduce((s, d) => s + d.completion_tokens, 0))
const totalTokens = computed(() => trend.value.reduce((s, d) => s + d.total_tokens, 0))
const totalCost = computed(() => trend.value.reduce((s, d) => s + d.total_cost, 0))
const totalCalls = computed(() => trend.value.reduce((s, d) => s + d.call_count, 0))
const totalLlmTokens = computed(() => trend.value.reduce((s, d) => s + d.llm_tokens, 0))
const totalEmbeddingTokens = computed(() => trend.value.reduce((s, d) => s + d.embedding_tokens, 0))
const totalRerankTokens = computed(() => trend.value.reduce((s, d) => s + d.rerank_tokens, 0))
</script>

<template>
  <div class="p-4 md:p-8">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">{{ t('admin.usageAnalysis') }}</h2>
        <p class="text-sm text-muted-foreground mt-1">{{ t('admin.usageAnalysisDesc') }}</p>
      </div>
      <div class="flex gap-2 shrink-0">
        <button
          v-for="d in [7, 30]"
          :key="d"
          @click="days = d"
          class="px-3 py-1.5 text-xs rounded-md transition-colors"
          :class="days === d
            ? 'bg-foreground text-background'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted'"
        >
          {{ d }}{{ t('common.days') }}
        </button>
      </div>
    </div>

    <!-- Summary cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">{{ t('console.totalTokens') }}</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-xl font-semibold tracking-tight">{{ formatTokens(totalTokens) }}</p>
          <p class="text-[0.65rem] text-muted-foreground mt-0.5">
            {{ t('console.promptInput', { input: formatTokens(totalPromptTokens), output: formatTokens(totalCompletionTokens) }) }}
          </p>
        </CardContent>
      </Card>
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">{{ t('console.totalCost') }}</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-xl font-semibold tracking-tight">{{ formatCost(totalCost) }}</p>
        </CardContent>
      </Card>
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">{{ t('console.callCount') }}</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-xl font-semibold tracking-tight">{{ totalCalls }}</p>
        </CardContent>
      </Card>
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">{{ t('console.modelType') }}</CardTitle>
        </CardHeader>
        <CardContent>
          <div class="flex flex-col gap-0.5 text-[0.7rem]">
            <span>LLM: {{ formatTokens(totalLlmTokens) }}</span>
            <span>Embedding: {{ formatTokens(totalEmbeddingTokens) }}</span>
            <span>Rerank: {{ formatTokens(totalRerankTokens) }}</span>
          </div>
        </CardContent>
      </Card>
    </div>

    <UsageTrendChart
      :trend="trend"
      :loading="isLoading"
    />

    <!-- Provider x Model table -->
    <Card class="border border-border shadow-[var(--shadow-sm)] mb-6">
      <CardHeader>
        <CardTitle class="text-sm font-medium">{{ t('admin.providerModelStats') }}</CardTitle>
      </CardHeader>
      <CardContent class="p-0">
        <div v-if="isLoading" class="text-center py-8 text-muted-foreground text-sm">{{ t('common.loading') }}</div>
        <div v-else-if="byProvider.length === 0" class="text-center py-8 text-muted-foreground text-sm">{{ t('admin.noData') }}</div>
        <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-border">
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.typeLabel') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.providerLabel') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.modelLabel') }}</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.callsLabel') }}</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.inputLabel') }}</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.outputLabel') }}</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.totalTokenLabel') }}</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.costLabel') }}</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.avgLatency') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(r, i) in byProvider"
              :key="i"
              class="border-b border-border last:border-0 hover:bg-muted/50 transition-colors"
            >
              <td class="py-3 px-4">
                <span
                  class="inline-flex h-5 items-center rounded-full border px-2 text-[0.65rem] font-medium"
                  :class="callTypeBadgeClass[r.call_type || ''] || 'border-border bg-muted text-muted-foreground'"
                >
                  {{ callTypeLabel[r.call_type || ''] || r.call_type }}
                </span>
              </td>
              <td class="py-3 px-4 font-medium">{{ r.provider_name }}</td>
              <td class="py-3 px-4 font-mono text-xs text-muted-foreground">{{ r.model_name }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs">{{ r.call_count }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs">{{ formatTokens(r.total_prompt_tokens) }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs">{{ formatTokens(r.total_completion_tokens) }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs">{{ formatTokens(r.total_tokens) }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs">{{ formatCost(r.total_cost) }}</td>
              <td class="py-3 px-4 text-right text-xs text-muted-foreground">{{ r.avg_latency_ms ? r.avg_latency_ms.toFixed(0) + 'ms' : '-' }}</td>
            </tr>
          </tbody>
        </table>
        </div>
      </CardContent>
    </Card>

    <!-- Recent calls -->
    <Card class="border border-border shadow-[var(--shadow-sm)]">
      <CardHeader>
        <CardTitle class="text-sm font-medium">{{ t('admin.recentCallsTitle') }}</CardTitle>
      </CardHeader>
      <CardContent class="p-0">
        <div v-if="isLoading" class="text-center py-8 text-muted-foreground text-sm">{{ t('common.loading') }}</div>
        <div v-else-if="calls.length === 0" class="text-center py-8 text-muted-foreground text-sm">{{ t('console.noCallRecords') }}</div>
        <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-border">
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('common.time') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('console.projectColumn') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('common.node') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('project.user') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.typeLabel') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.providerLabel') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.modelLabel') }}</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.inputLabel') }}</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.outputLabel') }}</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('admin.costLabel') }}</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('common.latency') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('common.status') }}</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('common.log') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="c in calls"
              :key="c.id"
              class="border-b border-border last:border-0 hover:bg-muted/50 transition-colors"
            >
              <td class="py-3 px-4 text-xs text-muted-foreground">
                {{ c.created_at ? new Date(c.created_at).toLocaleString() : '-' }}
              </td>
              <td class="py-3 px-4 text-muted-foreground text-xs">
                <div class="flex flex-col">
                  <span class="font-medium text-foreground">{{ c.project_name || '-' }}</span>
                  <span class="text-[0.65rem]">{{ c.project_id || '' }}</span>
                </div>
              </td>
              <td class="py-3 px-4 text-muted-foreground text-xs">
                <div class="flex flex-col">
                  <span class="font-medium text-foreground">{{ c.node_name || '-' }}</span>
                  <span class="text-[0.65rem]">{{ c.node_execution_id || '' }}</span>
                </div>
              </td>
              <td class="py-3 px-4 text-muted-foreground text-xs">
                <div class="flex flex-col">
                  <span class="font-medium text-foreground">{{ c.user_email || '-' }}</span>
                  <span class="text-[0.65rem]">{{ c.user_id || '' }}</span>
                </div>
              </td>
              <td class="py-3 px-4">
                <span
                  class="inline-flex h-5 items-center rounded-full border px-2 text-[0.65rem] font-medium"
                  :class="callTypeBadgeClass[c.call_type || ''] || 'border-border bg-muted text-muted-foreground'"
                >
                  {{ callTypeLabel[c.call_type || ''] || c.call_type }}
                </span>
              </td>
              <td class="py-3 px-4 text-muted-foreground">{{ c.provider_name }}</td>
              <td class="py-3 px-4 font-mono text-xs text-muted-foreground">{{ c.model_name }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs">{{ formatTokens(c.prompt_tokens ?? 0) }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs">{{ formatTokens(c.completion_tokens ?? 0) }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs">{{ formatCost(c.cost) }}</td>
              <td class="py-3 px-4 text-right text-xs text-muted-foreground">{{ c.latency_ms }}ms</td>
              <td class="py-3 px-4">
                <Badge :variant="c.status === 'success' ? 'default' : 'destructive'" class="text-[0.65rem]">
                  {{ c.status }}
                </Badge>
              </td>
              <td class="py-3 px-4 text-xs max-w-[240px] break-words whitespace-pre-wrap" :title="c.error_message || ''">
                <template v-if="c.status === 'error' && c.error_message">
                  <span class="text-destructive">{{ c.error_message }}</span>
                </template>
                <template v-else-if="c.status === 'running'">
                  <span class="text-muted-foreground">{{ t('admin.waiting') }}</span>
                </template>
                <template v-else>
                  <span class="text-muted-foreground">-</span>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
