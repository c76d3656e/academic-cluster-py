<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import type { ProgressProps } from './types'

const props = withDefaults(defineProps<ProgressProps>(), {
  max: 100,
  size: 'md',
  variant: 'default',
  showValue: true,
  showLabel: false,
  label: undefined,
  indeterminate: false,
  striped: false,
  animated: false,
  format: undefined,
})

const { t } = useI18n()

// 计算百分比
const percentage = computed(() => {
  if (props.indeterminate) return 0
  return Math.min(100, Math.max(0, (props.value / props.max) * 100))
})

// 计算显示的值
const displayValue = computed(() => {
  if (props.format) {
    return props.format(props.value, props.max)
  }
  return `${Math.round(percentage.value)}%`
})

// 计算尺寸样式
const sizeClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'h-1'
    case 'md':
      return 'h-2'
    case 'lg':
      return 'h-3'
    default:
      return 'h-2'
  }
})

// 计算变体样式
const variantClass = computed(() => {
  switch (props.variant) {
    case 'success':
      return 'bg-green-500'
    case 'warning':
      return 'bg-yellow-500'
    case 'error':
      return 'bg-red-500'
    default:
      return 'bg-primary'
  }
})
</script>

<template>
  <div class="space-y-2">
    <!-- 标签 -->
    <div
      v-if="showLabel && label"
      class="flex items-center justify-between"
    >
      <span class="text-sm font-medium">{{ label }}</span>
      <span v-if="showValue" class="text-sm text-muted-foreground">
        {{ displayValue }}
      </span>
    </div>

    <!-- 进度条 -->
    <div class="relative">
      <Progress
        :value="percentage"
        :class="[sizeClass, variantClass]"
        :indeterminate="indeterminate"
      />

      <!-- 条纹效果 -->
      <div
        v-if="striped"
        class="absolute inset-0 bg-stripe"
        :class="{ 'animate-stripe': animated }"
      />
    </div>

    <!-- 值 -->
    <div
      v-if="showValue && !showLabel"
      class="flex items-center justify-end"
    >
      <Badge variant="secondary">
        {{ displayValue }}
      </Badge>
    </div>
  </div>
</template>

<style scoped>
.bg-stripe {
  background-image: linear-gradient(
    45deg,
    rgba(255, 255, 255, 0.15) 25%,
    transparent 25%,
    transparent 50%,
    rgba(255, 255, 255, 0.15) 50%,
    rgba(255, 255, 255, 0.15) 75%,
    transparent 75%,
    transparent
  );
  background-size: 1rem 1rem;
}

.animate-stripe {
  animation: stripe 1s linear infinite;
}

@keyframes stripe {
  from {
    background-position: 1rem 0;
  }
  to {
    background-position: 0 0;
  }
}
</style>
