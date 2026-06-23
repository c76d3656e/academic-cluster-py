<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { TrendingUp, TrendingDown, Minus, Loader2 } from 'lucide-vue-next'
import type { StatCardProps } from './types'

const props = withDefaults(defineProps<StatCardProps>(), {
  previousValue: undefined,
  change: undefined,
  changeLabel: undefined,
  icon: undefined,
  trend: undefined,
  format: 'number',
  loading: false,
})

const { t } = useI18n()

// 计算趋势图标
const trendIcon = computed(() => {
  switch (props.trend) {
    case 'up':
      return TrendingUp
    case 'down':
      return TrendingDown
    default:
      return Minus
  }
})

// 计算趋势颜色
const trendColor = computed(() => {
  switch (props.trend) {
    case 'up':
      return 'text-green-500'
    case 'down':
      return 'text-red-500'
    default:
      return 'text-muted-foreground'
  }
})

// 格式化数值
const formattedValue = computed(() => {
  if (typeof props.value === 'string') return props.value

  switch (props.format) {
    case 'currency':
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
      }).format(props.value)
    case 'percentage':
      return `${props.value}%`
    default:
      return props.value.toLocaleString()
  }
})

// 格式化变化值
const formattedChange = computed(() => {
  if (props.change === undefined) return null

  const sign = props.change >= 0 ? '+' : ''
  return `${sign}${props.change}%`
})
</script>

<template>
  <Card>
    <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
      <CardTitle class="text-sm font-medium">{{ title }}</CardTitle>
      <div v-if="loading" class="animate-spin">
        <Loader2 class="h-4 w-4 text-muted-foreground" />
      </div>
      <div v-else-if="trend" :class="trendColor">
        <component :is="trendIcon" class="h-4 w-4" />
      </div>
    </CardHeader>
    <CardContent>
      <div class="flex items-baseline gap-2">
        <span class="text-2xl font-bold">{{ formattedValue }}</span>
        <span v-if="previousValue" class="text-sm text-muted-foreground">
          / {{ formattedValue }}
        </span>
      </div>
      <div v-if="formattedChange || changeLabel" class="flex items-center gap-2 mt-1">
        <Badge
          v-if="formattedChange"
          variant="secondary"
          :class="{
            'bg-green-100 text-green-800': change && change >= 0,
            'bg-red-100 text-red-800': change && change < 0,
          }"
        >
          {{ formattedChange }}
        </Badge>
        <span v-if="changeLabel" class="text-xs text-muted-foreground">
          {{ changeLabel }}
        </span>
      </div>
    </CardContent>
  </Card>
</template>
