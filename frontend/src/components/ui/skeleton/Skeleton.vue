<script setup lang="ts">
import type { SkeletonProps } from './types'

const props = withDefaults(defineProps<SkeletonProps>(), {
  variant: 'default',
  width: undefined,
  height: undefined,
})
</script>

<template>
  <div
    :class="[
      'animate-pulse rounded-md bg-muted',
      {
        'h-4 w-full': variant === 'text',
        'h-4 w-4': variant === 'circle',
        'h-6 w-6': variant === 'avatar',
        'h-48 w-full': variant === 'image',
      },
    ]"
    :style="{
      width: width ? `${width}px` : undefined,
      height: height ? `${height}px` : undefined,
    }"
  />
</template>
