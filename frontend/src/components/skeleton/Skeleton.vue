<script setup lang="ts">
import { computed } from 'vue'
import type { SkeletonProps } from './types'

const props = withDefaults(defineProps<SkeletonProps>(), {
  width: undefined,
  height: undefined,
  variant: 'text',
  animation: 'pulse',
  lines: 1,
  className: '',
})

// 计算样式
const skeletonStyle = computed(() => {
  const style: Record<string, string> = {}

  if (props.width) {
    style.width = typeof props.width === 'number' ? `${props.width}px` : props.width
  }

  if (props.height) {
    style.height = typeof props.height === 'number' ? `${props.height}px` : props.height
  }

  return style
})

// 计算类名
const skeletonClass = computed(() => {
  const classes: string[] = ['bg-muted']

  switch (props.variant) {
    case 'text':
      classes.push('h-4 w-full')
      break
    case 'circular':
      classes.push('rounded-full')
      break
    case 'rectangular':
      classes.push('rounded-none')
      break
    case 'rounded':
      classes.push('rounded-lg')
      break
  }

  switch (props.animation) {
    case 'pulse':
      classes.push('animate-pulse')
      break
    case 'wave':
      classes.push('animate-wave')
      break
    case 'none':
      break
  }

  if (props.className) {
    classes.push(props.className)
  }

  return classes.join(' ')
})
</script>

<template>
  <template v-if="variant === 'text' && lines > 1">
    <div class="space-y-2">
      <div
        v-for="i in lines"
        :key="i"
        :class="skeletonClass"
        :style="{
          ...skeletonStyle,
          width: i === lines ? '60%' : skeletonStyle.width,
        }"
      />
    </div>
  </template>
  <div
    v-else
    :class="skeletonClass"
    :style="skeletonStyle"
  />
</template>
