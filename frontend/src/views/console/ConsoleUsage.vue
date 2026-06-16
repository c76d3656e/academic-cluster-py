<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { consoleApi, type ConsoleUsageTrend, type ConsoleLlmCall } from '@/api/console'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

const days = ref(7)
const granularity = ref<'day' | 'hour'>('day')
const trend = ref<ConsoleUsageTrend[]>([])
const calls = ref<ConsoleLlmCall[]>([])
const isLoadingTrend = ref(true)
const isLoadingCalls = ref(true)
const trendMode = ref<'tokens' | 'cost'>('tokens')

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

watch(granularity, loadTrend)

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

watch(days, loadTrend)

onMounted(() => {
  loadTrend()
  loadCalls()
})

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
const maxBarValue = computed(() => {
  if (trendMode.value === 'tokens') {
    return Math.max(...trend.value.map(d => d.llm_tokens + d.embedding_tokens + d.rerank_tokens), 1)
  }
  return Math.max(...trend.value.map(d => d.llm_cost + d.embedding_cost + d.rerank_cost), 0.0001)
})

function barHeight(value: number): string {
  const h = Math.max((value / maxBarValue.value) * 160, 0)
  return h + 'px'
}

const callTypeLabel: Record<string, string> = {
  llm: 'LLM',
  embedding: 'Embedding',
  rerank: 'Rerank',
}


</script>

<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h2 class="text-heading font-medium tracking-tight">我的用量</h2>
        <p class="text-sm text-muted-foreground mt-1">Token 消耗与调用记录</p>
      </div>
      <div class="flex gap-2 items-center">
        <button
          v-for="d in [1, 7, 30]"
          :key="d"
          @click="days = d"
          class="px-3 py-1.5 text-xs rounded-md transition-colors"
          :class="days === d
            ? 'bg-foreground text-background'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted'"
        >
          {{ d }}天
        </button>
        <span class="w-px h-4 bg-border mx-1"></span>
        <button
          v-for="g in ([['day', '按日'], ['hour', '按小时']] as const)"
          :key="g[0]"
          @click="granularity = g[0] as any"
          class="px-3 py-1.5 text-xs rounded-md transition-colors"
          :class="granularity === g[0]
            ? 'bg-foreground text-background'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted'"
        >
          {{ g[1] }}
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

    <!-- Trend chart with stacked bars -->
    <Card class="border border-border shadow-[var(--shadow-sm)] mb-6">
      <CardHeader class="flex flex-row items-center justify-between">
        <CardTitle class="text-sm font-medium">消耗趋势</CardTitle>
        <div class="flex gap-1">
          <button
            v-for="mode in ([['tokens', 'Token'], ['cost', '费用']] as const)"
            :key="mode[0]"
            @click="trendMode = mode[0] as any"
            class="px-2 py-1 text-[0.65rem] rounded transition-colors"
            :class="trendMode === mode[0]
              ? 'bg-foreground text-background'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted'"
          >
            {{ mode[1] }}
          </button>
        </div>
      </CardHeader>
      <CardContent>
        <div v-if="isLoadingTrend" class="h-52 flex items-center justify-center text-muted-foreground text-sm">
          加载中...
        </div>
        <div v-else-if="trend.length === 0" class="h-52 flex items-center justify-center text-muted-foreground text-sm">
          暂无数据
        </div>
        <div v-else>
          <!-- Legend -->
          <div class="flex gap-4 mb-3 text-[0.65rem] text-muted-foreground">
            <span class="flex items-center gap-1"><span class="inline-block w-2.5 h-2.5 rounded-sm bg-foreground/80"></span>LLM</span>
            <span class="flex items-center gap-1"><span class="inline-block w-2.5 h-2.5 rounded-sm bg-blue-400/80"></span>Embedding</span>
            <span class="flex items-center gap-1"><span class="inline-block w-2.5 h-2.5 rounded-sm bg-amber-400/80"></span>Rerank</span>
          </div>
          <!-- Stacked bars -->
          <div class="h-44 flex items-end gap-1">
            <div
              v-for="d in trend"
              :key="d.date"
              class="flex-1 flex flex-col items-center justify-end h-full group relative"
            >
              <!-- Tooltip -->
              <div class="absolute bottom-full mb-2 hidden group-hover:block z-10 bg-popover border border-border rounded-md px-2.5 py-1.5 text-[0.6rem] whitespace-nowrap shadow-md">
                <div class="font-medium mb-0.5">{{ d.date }}</div>
                <div v-if="trendMode === 'tokens'">
                  <div>LLM: {{ formatTokens(d.llm_tokens) }}</div>
                  <div>Embedding: {{ formatTokens(d.embedding_tokens) }}</div>
                  <div>Rerank: {{ formatTokens(d.rerank_tokens) }}</div>
                  <div class="font-medium mt-0.5">总计: {{ formatTokens(d.llm_tokens + d.embedding_tokens + d.rerank_tokens) }}</div>
                </div>
                <div v-else>
                  <div>LLM: {{ formatCost(d.llm_cost) }}</div>
                  <div>Embedding: {{ formatCost(d.embedding_cost) }}</div>
                  <div>Rerank: {{ formatCost(d.rerank_cost) }}</div>
                  <div class="font-medium mt-0.5">总计: {{ formatCost(d.llm_cost + d.embedding_cost + d.rerank_cost) }}</div>
                </div>
              </div>
              <!-- Stacked segments -->
              <div class="w-full max-w-[40px] flex flex-col-reverse">
                <div
                  class="w-full rounded-b-sm bg-foreground/80 transition-all"
                  :style="{ height: barHeight(trendMode === 'tokens' ? d.llm_tokens : d.llm_cost) }"
                />
                <div
                  class="w-full bg-blue-400/80 transition-all"
                  :style="{ height: barHeight(trendMode === 'tokens' ? d.embedding_tokens : d.embedding_cost) }"
                />
                <div
                  class="w-full rounded-t-sm bg-amber-400/80 transition-all"
                  :style="{ height: barHeight(trendMode === 'tokens' ? d.rerank_tokens : d.rerank_cost) }"
                />
              </div>
              <span class="text-[0.55rem] text-muted-foreground mt-1">{{ d.date.slice(5) }}</span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- Recent calls table -->
    <Card class="border border-border shadow-[var(--shadow-sm)]">
      <CardHeader>
        <CardTitle class="text-sm font-medium">近期调用记录</CardTitle>
      </CardHeader>
      <CardContent class="p-0">
        <div v-if="isLoadingCalls" class="text-center py-8 text-muted-foreground text-sm">加载中...</div>
        <div v-else-if="calls.length === 0" class="text-center py-8 text-muted-foreground text-sm">暂无调用记录</div>
        <table v-else class="w-full text-sm">
          <thead>
            <tr class="border-b border-border">
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">时间</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">项目</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">节点</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">类型</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">Provider</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">模型</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">请求模型</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">输入</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">输出</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">费用</th>
              <th class="text-right py-3 px-4 text-caption text-muted-foreground font-normal">延迟</th>
              <th class="text-left py-3 px-4 text-caption text-muted-foreground font-normal">状态</th>
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
              <td class="py-3 px-4">
                <Badge
                  :variant="c.call_type === 'llm' ? 'default' : 'secondary'"
                  class="text-[0.6rem]"
                >
                  {{ callTypeLabel[c.call_type] || c.call_type }}
                </Badge>
              </td>
              <td class="py-3 px-4 text-muted-foreground text-xs">{{ c.provider_name }}</td>
              <td class="py-3 px-4 text-muted-foreground font-mono text-xs">{{ c.model_name }}</td>
              <td class="py-3 px-4 text-muted-foreground font-mono text-xs">{{ c.requested_model || '-' }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs">{{ formatTokens(c.prompt_tokens) }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs">{{ formatTokens(c.completion_tokens) }}</td>
              <td class="py-3 px-4 text-right font-mono text-xs">{{ formatCost(c.cost) }}</td>
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
      </CardContent>
    </Card>
  </div>
</template>
