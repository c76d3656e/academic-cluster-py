<script setup lang="ts">
import { computed } from 'vue'
import type { ProgressProps } from './types'

const props = withDefaults(defineProps<ProgressProps>(), {
  modelValue: 0,
  max: 100,
  variant: 'default',
  size: 'md',
  showValue: false,
})

const percentage = computed(() => {
  if (props.max === 0) return 0
  return Math.min(100, Math.max(0, (props.modelValue / props.max) * 100))
})

const barClass = computed(() => [
  'h-full w-full flex-1 bg-primary transition-all',
  {
    'bg-primary': props.variant === 'default',
    'bg-green-500': props.variant === 'success',
    'bg-yellow-500': props.variant === 'warning',
    'bg-red-500': props.variant === 'error',
  },
])

const trackClass = computed(() => [
  'relative h-2 w-full overflow-hidden rounded-full bg-primary/20',
  {
    'h-1': props.size === 'sm',
    'h-2': props.size === 'md',
    'h-3': props.size === 'lg',
  },
])
</script>

<template>
  <div class="flex items-center gap-2">
    <div :class="trackClass">
      <div
        :class="barClass"
        :style="{ width: `${percentage}%` }"
      />
    </div>
    <span v-if="showValue" class="text-sm text-muted-foreground">
      {{ Math.round(percentage) }}%
    </span>
  </div>
</template>
