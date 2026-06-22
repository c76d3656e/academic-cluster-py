<script setup lang="ts">
import { computed, ref } from 'vue'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { callTypeChartClass, callTypeValueClass } from '@/lib/usage-display'

export interface UsageTrendPoint {
  date: string
  llm_tokens: number
  embedding_tokens: number
  rerank_tokens: number
  llm_cost: number
  embedding_cost: number
  rerank_cost: number
}

const props = withDefaults(defineProps<{
  trend: UsageTrendPoint[]
  loading?: boolean
  title?: string
  loadingText?: string
  emptyText?: string
}>(), {
  loading: false,
  title: '消耗趋势',
  loadingText: '加载中...',
  emptyText: '暂无数据',
})

const trendMode = ref<'tokens' | 'cost'>('tokens')
const hoveredTrend = ref<UsageTrendPoint | null>(null)
const trendTooltipPosition = ref({ x: 0, y: 0 })

const maxBarValue = computed(() => {
  if (trendMode.value === 'tokens') {
    return Math.max(...props.trend.map(d => d.llm_tokens + d.embedding_tokens + d.rerank_tokens), 1)
  }
  return Math.max(...props.trend.map(d => d.llm_cost + d.embedding_cost + d.rerank_cost), 0.0001)
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

function barHeight(value: number): string {
  const h = Math.max((value / maxBarValue.value) * 200, 0)
  return h + 'px'
}

function showTrendTooltip(event: MouseEvent, item: UsageTrendPoint) {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  hoveredTrend.value = item
  trendTooltipPosition.value = {
    x: rect.left + rect.width / 2,
    y: rect.top - 12,
  }
}

function hideTrendTooltip() {
  hoveredTrend.value = null
}

function segmentValue(item: UsageTrendPoint, type: 'llm' | 'embedding' | 'rerank'): number {
  return trendMode.value === 'tokens' ? item[`${type}_tokens`] : item[`${type}_cost`]
}
</script>

<template>
  <Card class="border border-border shadow-[var(--shadow-sm)] mb-6">
    <CardHeader class="flex flex-row items-center justify-between">
      <CardTitle class="text-sm font-medium">{{ title }}</CardTitle>
      <div class="flex gap-1">
        <button
          v-for="mode in ([['tokens', 'Token'], ['cost', '费用']] as const)"
          :key="mode[0]"
          class="px-2 py-1 text-[0.65rem] rounded transition-colors"
          :class="trendMode === mode[0]
            ? 'bg-foreground text-background'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted'"
          @click="trendMode = mode[0]"
        >
          {{ mode[1] }}
        </button>
      </div>
    </CardHeader>
    <CardContent>
      <div v-if="loading" class="h-64 flex items-center justify-center text-muted-foreground text-sm">
        {{ loadingText }}
      </div>
      <div v-else-if="trend.length === 0" class="h-64 flex items-center justify-center text-muted-foreground text-sm">
        {{ emptyText }}
      </div>
      <div v-else>
        <div class="flex gap-4 mb-3 text-[0.65rem] text-muted-foreground">
          <span class="flex items-center gap-1"><span class="inline-block w-2.5 h-2.5 rounded-sm" :class="callTypeChartClass.llm" />LLM</span>
          <span class="flex items-center gap-1"><span class="inline-block w-2.5 h-2.5 rounded-sm" :class="callTypeChartClass.embedding" />Embedding</span>
          <span class="flex items-center gap-1"><span class="inline-block w-2.5 h-2.5 rounded-sm" :class="callTypeChartClass.rerank" />Rerank</span>
        </div>
        <div class="h-56 flex items-end gap-1">
          <div
            v-for="d in trend"
            :key="d.date"
            class="flex-1 flex flex-col items-center justify-end h-full"
            @mouseenter="showTrendTooltip($event, d)"
            @mouseleave="hideTrendTooltip"
          >
            <div class="w-full max-w-[40px] flex flex-col-reverse">
              <div
                class="w-full rounded-b-sm transition-all"
                :class="callTypeChartClass.llm"
                :style="{ height: barHeight(segmentValue(d, 'llm')) }"
              />
              <div
                class="w-full transition-all"
                :class="callTypeChartClass.embedding"
                :style="{ height: barHeight(segmentValue(d, 'embedding')) }"
              />
              <div
                class="w-full rounded-t-sm transition-all"
                :class="callTypeChartClass.rerank"
                :style="{ height: barHeight(segmentValue(d, 'rerank')) }"
              />
            </div>
            <span class="text-[0.55rem] text-muted-foreground mt-1">{{ d.date.slice(5) }}</span>
          </div>
        </div>
      </div>
    </CardContent>
  </Card>

  <Teleport to="body">
    <div
      v-if="hoveredTrend"
      class="pointer-events-none fixed z-50 min-w-48 rounded-lg border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-xl"
      :style="{
        left: trendTooltipPosition.x + 'px',
        top: trendTooltipPosition.y + 'px',
        transform: 'translate(-50%, -100%)',
      }"
    >
      <div class="mb-1 font-medium text-foreground">{{ hoveredTrend.date }}</div>
      <div v-if="trendMode === 'tokens'" class="space-y-1 text-muted-foreground">
        <div class="flex justify-between gap-6">
          <span>LLM</span>
          <span class="font-medium" :class="callTypeValueClass.llm">{{ formatTokens(hoveredTrend.llm_tokens) }}</span>
        </div>
        <div class="flex justify-between gap-6">
          <span>Embedding</span>
          <span class="font-medium" :class="callTypeValueClass.embedding">{{ formatTokens(hoveredTrend.embedding_tokens) }}</span>
        </div>
        <div class="flex justify-between gap-6">
          <span>Rerank</span>
          <span class="font-medium" :class="callTypeValueClass.rerank">{{ formatTokens(hoveredTrend.rerank_tokens) }}</span>
        </div>
        <div class="mt-1 border-t border-border pt-1 font-medium text-foreground">
          Total: {{ formatTokens(hoveredTrend.llm_tokens + hoveredTrend.embedding_tokens + hoveredTrend.rerank_tokens) }}
        </div>
      </div>
      <div v-else class="space-y-1 text-muted-foreground">
        <div class="flex justify-between gap-6">
          <span>LLM</span>
          <span class="font-medium" :class="callTypeValueClass.llm">{{ formatCost(hoveredTrend.llm_cost) }}</span>
        </div>
        <div class="flex justify-between gap-6">
          <span>Embedding</span>
          <span class="font-medium" :class="callTypeValueClass.embedding">{{ formatCost(hoveredTrend.embedding_cost) }}</span>
        </div>
        <div class="flex justify-between gap-6">
          <span>Rerank</span>
          <span class="font-medium" :class="callTypeValueClass.rerank">{{ formatCost(hoveredTrend.rerank_cost) }}</span>
        </div>
        <div class="mt-1 border-t border-border pt-1 font-medium text-foreground">
          Total: {{ formatCost(hoveredTrend.llm_cost + hoveredTrend.embedding_cost + hoveredTrend.rerank_cost) }}
        </div>
      </div>
    </div>
  </Teleport>
</template>
