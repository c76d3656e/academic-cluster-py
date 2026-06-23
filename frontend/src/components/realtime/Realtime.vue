<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Activity, Play, Pause, RefreshCw, TrendingUp, TrendingDown, Minus } from 'lucide-vue-next'
import type { RealtimeProps, RealtimeMetric, RealtimeFeedItem } from './types'

const props = withDefaults(defineProps<RealtimeProps>(), {
  isLive: true,
  refreshInterval: 2000,
  onToggleLive: undefined,
  onRefresh: undefined,
})

const { t } = useI18n()

const isLive = ref(props.isLive)
const lastUpdated = ref<Date>(new Date())
const refreshTimer = ref<ReturnType<typeof setInterval> | null>(null)

// 计算指标趋势
function getTrendIcon(trend?: 'up' | 'down' | 'stable') {
  switch (trend) {
    case 'up':
      return TrendingUp
    case 'down':
      return TrendingDown
    default:
      return Minus
  }
}

function getTrendColor(trend?: 'up' | 'down' | 'stable') {
  switch (trend) {
    case 'up':
      return 'text-green-500'
    case 'down':
      return 'text-red-500'
    default:
      return 'text-muted-foreground'
  }
}

// 计算相对时间
function relativeTime(date: Date): string {
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const seconds = Math.floor(diff / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)

  if (seconds < 60) return t('realtime.justNow')
  if (minutes < 60) return t('realtime.minutesAgo', { count: minutes })
  if (hours < 24) return t('realtime.hoursAgo', { count: hours })
  return date.toLocaleDateString()
}

// 获取 feed 类型颜色
function getFeedTypeColor(type: string) {
  switch (type) {
    case 'success':
      return 'bg-green-100 text-green-800'
    case 'warning':
      return 'bg-yellow-100 text-yellow-800'
    case 'error':
      return 'bg-red-100 text-red-800'
    default:
      return 'bg-blue-100 text-blue-800'
  }
}

// 切换实时状态
function toggleLive() {
  isLive.value = !isLive.value
  props.onToggleLive?.(isLive.value)

  if (isLive.value) {
    startRefreshTimer()
  } else {
    stopRefreshTimer()
  }
}

// 刷新数据
function refresh() {
  lastUpdated.value = new Date()
  props.onRefresh?.()
}

// 启动刷新定时器
function startRefreshTimer() {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value)
  }
  refreshTimer.value = setInterval(refresh, props.refreshInterval)
}

// 停止刷新定时器
function stopRefreshTimer() {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value)
    refreshTimer.value = null
  }
}

// 监听实时状态变化
watch(isLive, (newValue) => {
  if (newValue) {
    startRefreshTimer()
  } else {
    stopRefreshTimer()
  }
})

// 组件挂载时启动定时器
onMounted(() => {
  if (isLive.value) {
    startRefreshTimer()
  }
})

// 组件卸载时清除定时器
onUnmounted(() => {
  stopRefreshTimer()
})
</script>

<template>
  <div class="space-y-6">
    <!-- 头部控制区 -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-2">
        <Activity class="h-5 w-5" />
        <h3 class="text-lg font-medium">{{ t('realtime.title') }}</h3>
        <Badge v-if="isLive" variant="default" class="animate-pulse">
          {{ t('realtime.live') }}
        </Badge>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-sm text-muted-foreground">
          {{ t('realtime.lastUpdated') }}: {{ relativeTime(lastUpdated) }}
        </span>
        <Button variant="outline" size="sm" @click="refresh">
          <RefreshCw class="h-4 w-4" />
        </Button>
        <Button variant="outline" size="sm" @click="toggleLive">
          <component :is="isLive ? Pause : Play" class="h-4 w-4" />
          {{ isLive ? t('realtime.pause') : t('realtime.resume') }}
        </Button>
      </div>
    </div>

    <!-- 指标卡片 -->
    <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <Card v-for="metric in metrics" :key="metric.label">
        <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle class="text-sm font-medium">{{ metric.label }}</CardTitle>
          <component
            :is="getTrendIcon(metric.trend)"
            :class="['h-4 w-4', getTrendColor(metric.trend)]"
          />
        </CardHeader>
        <CardContent>
          <div class="flex items-baseline gap-1">
            <span class="text-2xl font-bold">{{ metric.value.toLocaleString() }}</span>
            <span v-if="metric.unit" class="text-muted-foreground">{{ metric.unit }}</span>
          </div>
          <div v-if="metric.previousValue !== undefined" class="flex items-center gap-1 mt-1">
            <span
              class="text-xs"
              :class="metric.value >= metric.previousValue ? 'text-green-500' : 'text-red-500'"
            >
              {{ metric.value >= metric.previousValue ? '+' : '' }}
              {{ ((metric.value - metric.previousValue) / metric.previousValue * 100).toFixed(1) }}%
            </span>
            <span class="text-xs text-muted-foreground">{{ t('realtime.vsPrevious') }}</span>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 活动 Feed -->
    <Card>
      <CardHeader>
        <CardTitle class="flex items-center gap-2">
          <Activity class="h-5 w-5" />
          {{ t('realtime.activityFeed') }}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div class="space-y-4">
          <div
            v-for="item in feed"
            :key="item.id"
            class="flex items-start gap-3 p-3 rounded-lg border"
          >
            <Badge :class="getFeedTypeColor(item.type)">
              {{ item.type }}
            </Badge>
            <div class="flex-1 min-w-0">
              <div class="font-medium">{{ item.title }}</div>
              <div v-if="item.description" class="text-sm text-muted-foreground">
                {{ item.description }}
              </div>
            </div>
            <span class="text-xs text-muted-foreground whitespace-nowrap">
              {{ relativeTime(item.timestamp) }}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
