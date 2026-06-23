<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import { Loader2 } from 'lucide-vue-next'
import type { SpinnerProps } from './types'

const props = withDefaults(defineProps<SpinnerProps>(), {
  size: 'md',
  variant: 'default',
  label: undefined,
  showLabel: false,
  overlay: false,
  fullScreen: false,
})

const { t } = useI18n()

// 计算尺寸样式
const sizeClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'h-4 w-4'
    case 'md':
      return 'h-6 w-6'
    case 'lg':
      return 'h-8 w-8'
    case 'xl':
      return 'h-12 w-12'
    default:
      return 'h-6 w-6'
  }
})

// 计算变体样式
const variantClass = computed(() => {
  switch (props.variant) {
    case 'primary':
      return 'text-primary'
    case 'secondary':
      return 'text-secondary'
    case 'muted':
      return 'text-muted-foreground'
    default:
      return 'text-foreground'
  }
})

// 计算标签
const displayLabel = computed(() => {
  return props.label || t('spinner.loading')
})
</script>

<template>
  <!-- 全屏加载 -->
  <div
    v-if="fullScreen"
    class="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm"
  >
    <div class="flex flex-col items-center gap-4">
      <Loader2 :class="[sizeClass, variantClass]" class="animate-spin" />
      <span v-if="showLabel" class="text-sm text-muted-foreground">
        {{ displayLabel }}
      </span>
    </div>
  </div>

  <!-- 覆盖层加载 -->
  <div
    v-else-if="overlay"
    class="absolute inset-0 z-10 flex items-center justify-center bg-background/80 backdrop-blur-sm"
  >
    <div class="flex flex-col items-center gap-4">
      <Loader2 :class="[sizeClass, variantClass]" class="animate-spin" />
      <span v-if="showLabel" class="text-sm text-muted-foreground">
        {{ displayLabel }}
      </span>
    </div>
  </div>

  <!-- 内联加载 -->
  <div v-else class="flex items-center gap-2">
    <Loader2 :class="[sizeClass, variantClass]" class="animate-spin" />
    <span v-if="showLabel" class="text-sm text-muted-foreground">
      {{ displayLabel }}
    </span>
  </div>
</template>
