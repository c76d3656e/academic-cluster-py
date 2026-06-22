<script setup lang="ts">
import { shallowRef, ref, watch, onMounted, computed } from 'vue'
import { useI18n } from '@/i18n'
import { formatTokens } from '@/lib/utils'
import { consoleApi, type ConsoleUsageTrend, type ConsoleLlmCall } from '@/api/console'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import UsageTrendChart from '@/components/usage/UsageTrendChart.vue'
import { callTypeBadgeClass, callTypeLabel } from '@/lib/usage-display'
import { useFeatures } from '@/composables/useFeatures'

const { t } = useI18n()
const { features, loadFeatures } = useFeatures()
const featureEnabled = ref(false)
const featureLoading = ref(true)

onMounted(async () => {
  await loadFeatures()
  featureEnabled.value = features.value.show_usage ?? false
  featureLoading.value = false
  if (featureEnabled.value) {
    loadTrend()
    loadCalls()
  }
})

const days = shallowRef(7)
const granularity = shallowRef<'day' | 'hour'>('day')
const trend = ref<ConsoleUsageTrend[]>([])
const calls = ref<ConsoleLlmCall[]>([])
const isLoadingTrend = shallowRef(true)
const isLoadingCalls = shallowRef(true)

async function loadTrend() {
  isLoadingTrend.value = true
  try {
    trend.value = await consoleApi.getUsageTrend(days.value, granularity.value)
  } catch {
    trend.value = []
  } finally {
    isLoadingTrend.value = false
  }
}

async function loadCalls() {
  isLoadingCalls.value = true
  try {
    calls.value = await consoleApi.getMyCalls({ limit: 50 })
  } catch {
    calls.value = []
  } finally {
    isLoadingCalls.value = false
  }
}

watch(granularity, loadTrend)
watch(days, loadTrend)

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
    <!-- Feature disabled state -->
    <div v-if="featureLoading" class="flex items-center justify-center py-16">
      <div class="text-muted-foreground text-sm">{{ t('common.loading') }}</div>
    </div>
    <div v-else-if="!featureEnabled" class="flex flex-col items-center justify-center py-16 gap-4">
      <div class="text-4xl opacity-20">&#x26A0;</div>
      <div class="text-center">
        <h3 class="text-lg font-medium text-foreground mb-1">{{ t('console.featureDisabled') }}</h3>
        <p class="text-sm text-muted-foreground">{{ t('console.usageDisabledHint') }}</p>
      </div>
    </div>

    <template v-else>
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-8">
        <div>
          <h2 class="text-heading font-medium tracking-tight">{{ t('console.myUsage') }}</h2>
          <p class="text-sm text-muted-foreground mt-1">{{ t('console.tokenConsumption') }}</p>
        </div>
        <div class="flex gap-2 items-center flex-wrap">
          <button
            v-for="d in [1, 7, 30]"
            :key="d"
            class="px-3 py-1.5 text-xs rounded-md transition-colors"
            :class="days === d
              ? 'bg-foreground text-background'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted'"
            @click="days = d"
          >
            {{ d }}{{ t('common.days') }}
          </button>
          <span class="w-px h-4 bg-border mx-1" />
          <button
            v-for="g in ([['day', t('common.byDay')], ['hour', t('common.byHour')]] as const)"
            :key="g[0]"
            class="px-3 py-1.5 text-xs rounded-md transition-colors"
            :class="granularity === g[0]
              ? 'bg-foreground text-background'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted'"
            @click="granularity = g[0] as any"
          >
            {{ g[1] }}
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
        :loading="isLoadingTrend"
      />

      <!-- Recent calls table -->
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader>
          <CardTitle class="text-sm font-medium">{{ t('console.recentCalls') }}</CardTitle>
        </CardHeader>
        <CardContent class="p-0">
          <div v-if="isLoadingCalls" class="text-center py-8 text-muted-foreground text-sm">{{ t('common.loading') }}</div>
          <div v-else-if="calls.length === 0" class="text-center py-8 text-muted-foreground text-sm">{{ t('console.noCallRecords') }}</div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b border-border">
                  <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('common.time') }}</th>
                  <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('console.projectColumn') }}</th>
                  <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('console.typeColumn') }}</th>
                  <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('console.inputColumn') }}</th>
                  <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('console.outputColumn') }}</th>
                  <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('console.costColumn') }}</th>
                  <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('console.latencyColumn') }}</th>
                  <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">{{ t('console.statusColumn') }}</th>
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
                  <td class="py-3 px-4">
                    <span
                      class="inline-flex h-5 items-center rounded-full border px-2 text-[0.65rem] font-medium"
                      :class="callTypeBadgeClass[c.call_type] || 'border-border bg-muted text-muted-foreground'"
                    >
                      {{ callTypeLabel[c.call_type] || c.call_type }}
                    </span>
                  </td>
                  <td class="py-3 px-4 text-right font-mono text-xs">{{ formatTokens(c.prompt_tokens) }}</td>
                  <td class="py-3 px-4 text-right font-mono text-xs">{{ formatTokens(c.completion_tokens) }}</td>
                  <td class="py-3 px-4 text-right font-mono text-xs">
                    <div>{{ formatCost(c.cost) }}</div>
                    <div class="text-[0.65rem] text-muted-foreground">
                      {{ c.input_price_per_m != null || c.output_price_per_m != null ? `${formatCost(c.input_price_per_m || 0)}/${formatCost(c.output_price_per_m || 0)}` : '-' }}
                    </div>
                  </td>
                  <td class="py-3 px-4 text-right text-xs text-muted-foreground">{{ c.latency_ms }}ms</td>
                  <td class="py-3 px-4">
                    <div class="flex flex-col gap-1">
                      <Badge :variant="c.status === 'success' ? 'default' : 'destructive'" class="text-[0.65rem] w-fit">
                        {{ c.status }}
                      </Badge>
                      <span v-if="c.error_message" class="text-[0.65rem] text-muted-foreground line-clamp-2">
                        {{ c.error_message }}
                      </span>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </template>
  </div>
</template>
