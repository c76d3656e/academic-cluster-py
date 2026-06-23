<script setup lang="ts">
import { computed } from 'vue'
import {
  Avatar as AvatarRoot,
  AvatarFallback,
  AvatarImage,
} from '@/components/ui/avatar'
import type { AvatarProps } from './types'

const props = withDefaults(defineProps<AvatarProps>(), {
  src: undefined,
  alt: '',
  fallback: '',
  size: 'md',
  shape: 'circle',
  status: undefined,
  border: false,
  className: '',
})

// 计算尺寸样式
const sizeClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'h-8 w-8 text-xs'
    case 'md':
      return 'h-10 w-10 text-sm'
    case 'lg':
      return 'h-12 w-12 text-base'
    case 'xl':
      return 'h-16 w-16 text-lg'
    default:
      return 'h-10 w-10 text-sm'
  }
})

// 计算形状样式
const shapeClass = computed(() => {
  return props.shape === 'square' ? 'rounded-lg' : 'rounded-full'
})

// 计算边框样式
const borderClass = computed(() => {
  return props.border ? 'ring-2 ring-background' : ''
})

// 计算状态颜色
const statusColor = computed(() => {
  switch (props.status) {
    case 'online':
      return 'bg-green-500'
    case 'offline':
      return 'bg-gray-400'
    case 'away':
      return 'bg-yellow-500'
    case 'busy':
      return 'bg-red-500'
    default:
      return ''
  }
})

// 计算首字母
const initials = computed(() => {
  if (props.fallback) return props.fallback
  if (!props.alt) return '?'

  return props.alt
    .split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
})
</script>

<template>
  <div class="relative inline-block">
    <AvatarRoot
      :class="[sizeClass, shapeClass, borderClass, className]"
    >
      <AvatarImage v-if="src" :src="src" :alt="alt" />
      <AvatarFallback :class="shapeClass">
        {{ initials }}
      </AvatarFallback>
    </AvatarRoot>

    <!-- 状态指示器 -->
    <div
      v-if="status"
      class="absolute bottom-0 right-0 w-3 h-3 rounded-full border-2 border-background"
      :class="statusColor"
    />
  </div>
</template>
