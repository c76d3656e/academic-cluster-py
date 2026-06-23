<script setup lang="ts">
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import type { StatusChipProps } from './types'

const props = withDefaults(defineProps<StatusChipProps>(), {
  variant: 'default',
  size: 'md',
  dot: false,
  icon: undefined,
  label: undefined,
  color: undefined,
  backgroundColor: undefined,
})

// 计算样式
const chipStyle = computed(() => {
  const style: Record<string, string> = {}

  if (props.color) {
    style.color = props.color
  }

  if (props.backgroundColor) {
    style.backgroundColor = props.backgroundColor
  }

  return style
})

// 计算类名
const chipClass = computed(() => {
  const classes: string[] = []

  switch (props.size) {
    case 'sm':
      classes.push('text-xs px-2 py-0.5')
      break
    case 'md':
      classes.push('text-sm px-2.5 py-1')
      break
    case 'lg':
      classes.push('text-base px-3 py-1.5')
      break
  }

  return classes.join(' ')
})

// 计算显示文本
const displayText = computed(() => {
  return props.label || props.status
})
</script>

<template>
  <Badge
    :variant="variant"
    :class="chipClass"
    :style="chipStyle"
  >
    <span v-if="dot" class="w-2 h-2 rounded-full mr-1.5" :style="{ backgroundColor: color || 'currentColor' }" />
    <span v-if="icon" class="mr-1.5">{{ icon }}</span>
    {{ displayText }}
  </Badge>
</template>
