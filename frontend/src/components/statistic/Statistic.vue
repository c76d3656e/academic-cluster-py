<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { TrendingUp, TrendingDown, Minus, Loader2, ArrowRight } from 'lucide-vue-next'
import type { StatisticProps } from './types'

const props = withDefaults(defineProps<StatisticProps>(), {
  previousValue: undefined,
  change: undefined,
  changeLabel: undefined,
  prefix: undefined,
  suffix: undefined,
  icon: undefined,
  trend: undefined,
  format: 'number',
  precision: 0,
  loading: false,
  description: undefined,
  action: undefined,
  size: 'md',
  variant: 'default',
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

  let formatted: string

  switch (props.format) {
    case 'currency':
      formatted = new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: props.precision,
        maximumFractionDigits: props.precision,
      }).format(props.value)
      break
    case 'percentage':
      formatted = `${props.value.toFixed(props.precision)}%`
      break
    default:
      formatted = props.value.toLocaleString(undefined, {
        minimumFractionDigits: props.precision,
        maximumFractionDigits: props.precision,
      })
  }

  return formatted
})

// 格式化变化值
const formattedChange = computed(() => {
  if (props.change === undefined) return null

  const sign = props.change >= 0 ? '+' : ''
  return `${sign}${props.change.toFixed(1)}%`
})

// 计算卡片尺寸样式
const sizeClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'p-4'
    case 'md':
      return 'p-6'
    case 'lg':
      return 'p-8'
    default:
      return 'p-6'
  }
})

// 计算卡片变体样式
const variantClass = computed(() => {
  switch (props.variant) {
    case 'bordered':
      return 'border'
    case 'card':
      return 'border shadow-sm'
    default:
      return ''
  }
})
</script>

<template>
  <Card :class="[sizeClass, variantClass]">
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
      <div class="flex items-baseline gap-1">
        <span v-if="prefix" class="text-muted-foreground">{{ prefix }}</span>
        <span class="text-2xl font-bold">{{ formattedValue }}</span>
        <span v-if="suffix" class="text-muted-foreground">{{ suffix }}</span>
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
      <div v-if="description" class="text-sm text-muted-foreground mt-2">
        {{ description }}
      </div>
      <div v-if="action" class="mt-4">
        <Button variant="link" size="sm" class="h-auto p-0" @click="action.onClick">
          {{ action.label }}
          <ArrowRight class="h-4 w-4 ml-1" />
        </Button>
      </div>
    </CardContent>
  </Card>
</template>
