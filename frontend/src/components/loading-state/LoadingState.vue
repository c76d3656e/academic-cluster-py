<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import { Card, CardContent } from '@/components/ui/card'
import { Loader2 } from 'lucide-vue-next'
import type { LoadingStateProps } from './types'

const props = withDefaults(defineProps<LoadingStateProps>(), {
  title: undefined,
  description: undefined,
  size: 'md',
  variant: 'spinner',
  overlay: false,
  fullScreen: false,
})

const { t } = useI18n()

// 计算尺寸样式
const sizeClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'py-8'
    case 'md':
      return 'py-12'
    case 'lg':
      return 'py-16'
    default:
      return 'py-12'
  }
})

// 计算图标尺寸
const iconSize = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'h-6 w-6'
    case 'md':
      return 'h-8 w-8'
    case 'lg':
      return 'h-12 w-12'
    default:
      return 'h-8 w-8'
  }
})

// 计算标题
const displayTitle = computed(() => {
  return props.title || t('loading.title')
})

// 计算描述
const displayDescription = computed(() => {
  return props.description || t('loading.description')
})
</script>

<template>
  <!-- 全屏加载 -->
  <div
    v-if="fullScreen"
    class="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm"
  >
    <div class="flex flex-col items-center gap-4">
      <Loader2 :class="iconSize" class="animate-spin text-primary" />
      <div class="text-center">
        <div class="font-medium">{{ displayTitle }}</div>
        <div v-if="displayDescription" class="text-sm text-muted-foreground">
          {{ displayDescription }}
        </div>
      </div>
    </div>
  </div>

  <!-- 覆盖层加载 -->
  <div
    v-else-if="overlay"
    class="absolute inset-0 z-10 flex items-center justify-center bg-background/80 backdrop-blur-sm"
  >
    <div class="flex flex-col items-center gap-4">
      <Loader2 :class="iconSize" class="animate-spin text-primary" />
      <div class="text-center">
        <div class="font-medium">{{ displayTitle }}</div>
        <div v-if="displayDescription" class="text-sm text-muted-foreground">
          {{ displayDescription }}
        </div>
      </div>
    </div>
  </div>

  <!-- 卡片式加载 -->
  <Card v-else>
    <CardContent :class="sizeClass">
      <div class="flex flex-col items-center justify-center text-center">
        <!-- 加载动画 -->
        <div v-if="variant === 'spinner'" class="mb-4">
          <Loader2 :class="iconSize" class="animate-spin text-primary" />
        </div>

        <div v-else-if="variant === 'dots'" class="mb-4 flex gap-1">
          <div
            v-for="i in 3"
            :key="i"
            class="w-2 h-2 rounded-full bg-primary animate-bounce"
            :style="{ animationDelay: `${(i - 1) * 0.1}s` }"
          />
        </div>

        <div v-else-if="variant === 'skeleton'" class="mb-4 w-16 h-16 rounded-full bg-muted animate-pulse" />

        <!-- 标题 -->
        <div class="font-medium mb-2">{{ displayTitle }}</div>

        <!-- 描述 -->
        <p
          v-if="displayDescription"
          class="text-sm text-muted-foreground max-w-md"
        >
          {{ displayDescription }}
        </p>
      </div>
    </CardContent>
  </Card>
</template>
