<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { adminApi, type DailyUsage, type UsageByProvider, type LlmCallRecord } from '@/api/admin'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import UsageTrendChart from '@/components/usage/UsageTrendChart.vue'
import { callTypeBadgeClass, callTypeLabel } from '@/lib/usage-display'

const days = ref(7)
const trend = ref<DailyUsage[]>([])
const byProvider = ref<UsageByProvider[]>([])
const calls = ref<LlmCallRecord[]>([])
const isLoading = ref(true)

async function loadAll() {
  isLoading.value = true
  try {
    const [t, p, c] = await Promise.all([
      adminApi.getUsageTrend(days.value),
      adminApi.getUsageByProvider(days.value),
      adminApi.getRecentCalls({ limit: 50 }),
    ])
    trend.value = t
    byProvider.value = p
    calls.value = c
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

function formatTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

function formatCost(n: number): string {
  if (n >= 1) return '$' + n.toFixed(2)
  if (n >= 0.01) return '$' + n.toFixed(4)
  return '$' + n.toFixed(6)
}

// 汇总统计
const totalPromptTokens = computed(() => trend.value.reduce((s, d) => s + d.prompt_tokens, 0))
const totalCompletionTokens = computed(() => trend.value.reduce((s, d) => s + d.completion_tokens, 0))
const totalTokens = computed(() => trend.value.reduce((s, d) => s + d.total_tokens, 0))
const totalCost = computed(() => trend.value.reduce((s, d) => s + d.total_cost, 0))
const totalCalls = computed(() => trend.value.reduce((s, d) => s + d.call_count, 0))
const totalLlmTokens = computed(() => trend.value.reduce((s, d) => s + d.llm_tokens, 0))
const totalEmbeddingTokens = computed(() => trend.value.reduce((s, d) => s + d.embedding_tokens, 0))
const totalRerankTokens = computed(() => trend.value.reduce((s, d) => s + d.rerank_tokens, 0))

// 堆叠柱状图计算
</script>

<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">用量分析</h2>
        <p class="text-sm text-muted-foreground mt-1">全系统 Token 消耗与成本统计</p>
      </div>
      <div class="flex gap-2">
        <button
          v-for="d in [7, 30]"
          :key="d"
          @click="days = d"
          class="px-3 py-1.5 text-xs rounded-md transition-colors"
          :class="days === d
            ? 'bg-foreground text-background'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted'"
        >
          {{ d }}天
        </button>
      </div>
    </div>

    <!-- Summary cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">总 Tokens</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-xl font-semibold tracking-tight">{{ formatTokens(totalTokens) }}</p>
          <p class="text-[0.65rem] text-muted-foreground mt-0.5">
            输入 {{ formatTokens(totalPromptTokens) }} / 输出 {{ formatTokens(totalCompletionTokens) }}
          </p>
        </CardContent>
      </Card>
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">总费用</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-xl font-semibold tracking-tight">{{ formatCost(totalCost) }}</p>
        </CardContent>
      </Card>
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">调用次数</CardTitle>
        </CardHeader>
        <CardContent>
          <p class="text-xl font-semibold tracking-tight">{{ totalCalls }}</p>
        </CardContent>
      </Card>
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader class="pb-2">
          <CardTitle class="text-caption text-muted-foreground font-normal">模型类型</CardTitle>
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
        <CardTitle class="text-sm font-medium">Provider x Model 统计</CardTitle>
      </CardHeader>
      <CardContent class="p-0">
        <div v-if="isLoading" class="text-center py-8 text-muted-foreground text-sm">加载中...</div>
        <div v-else-if="byProvider.length === 0" class="text-center py-8 text-muted-foreground text-sm">暂无数据</div>
        <table v-else class="w-full text-sm">
          <thead>
            <tr class="border-b border-border">
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">类型</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">Provider</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">模型</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">调用次数</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">输入</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">输出</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">总 Token</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">费用</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">平均延迟</th>
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
      </CardContent>
    </Card>

    <!-- Recent calls -->
    <Card class="border border-border shadow-[var(--shadow-sm)]">
      <CardHeader>
        <CardTitle class="text-sm font-medium">近期调用记录</CardTitle>
      </CardHeader>
      <CardContent class="p-0">
        <div v-if="isLoading" class="text-center py-8 text-muted-foreground text-sm">加载中...</div>
        <div v-else-if="calls.length === 0" class="text-center py-8 text-muted-foreground text-sm">暂无调用记录</div>
        <table v-else class="w-full text-sm">
          <thead>
            <tr class="border-b border-border">
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">时间</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">项目</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">节点</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">用户</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">类型</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">Provider</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">模型</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">输入</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">输出</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">费用</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">延迟</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">状态</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">日志</th>
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
                  <span class="text-muted-foreground">等待中...</span>
                </template>
                <template v-else>
                  <span class="text-muted-foreground">-</span>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </CardContent>
    </Card>
  </div>
</template>
