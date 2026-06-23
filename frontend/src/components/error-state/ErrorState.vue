<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { AlertCircle, RefreshCw, ArrowLeft, ChevronDown, ChevronUp } from 'lucide-vue-next'
import type { ErrorStateProps } from './types'

const props = withDefaults(defineProps<ErrorStateProps>(), {
  title: undefined,
  description: undefined,
  error: undefined,
  retry: undefined,
  retryLabel: undefined,
  backLabel: undefined,
  backTo: undefined,
  size: 'md',
  showDetails: false,
})

const { t } = useI18n()

const isRetrying = ref(false)
const isDetailsOpen = ref(false)

// 计算错误信息
const errorMessage = computed(() => {
  if (!props.error) return null

  if (typeof props.error === 'string') {
    return props.error
  }

  return props.error.message || t('error.unknown')
})

// 计算标题
const displayTitle = computed(() => {
  return props.title || t('error.title')
})

// 计算描述
const displayDescription = computed(() => {
  return props.description || t('error.description')
})

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

// 重试操作
async function handleRetry() {
  if (!props.retry || isRetrying.value) return

  isRetrying.value = true
  try {
    await props.retry()
  } finally {
    isRetrying.value = false
  }
}

// 切换详情显示
function toggleDetails() {
  isDetailsOpen.value = !isDetailsOpen.value
}
</script>

<template>
  <Card>
    <CardContent :class="sizeClass">
      <div class="flex flex-col items-center justify-center text-center">
        <!-- 错误图标 -->
        <div class="mb-4 flex items-center justify-center w-16 h-16 rounded-full bg-destructive/10">
          <AlertCircle class="h-8 w-8 text-destructive" />
        </div>

        <!-- 标题 -->
        <h3 class="text-lg font-semibold mb-2">{{ displayTitle }}</h3>

        <!-- 描述 -->
        <p class="text-sm text-muted-foreground max-w-md mb-6">
          {{ displayDescription }}
        </p>

        <!-- 错误详情 -->
        <div v-if="error && showDetails" class="w-full max-w-md mb-6">
          <Button
            variant="ghost"
            size="sm"
            class="w-full"
            @click="toggleDetails"
          >
            <span>{{ t('error.details') }}</span>
            <component
              :is="isDetailsOpen ? ChevronUp : ChevronDown"
              class="h-4 w-4 ml-2"
            />
          </Button>

          <div
            v-if="isDetailsOpen"
            class="mt-2 p-3 bg-muted rounded-lg text-sm text-left font-mono"
          >
            {{ errorMessage }}
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="flex items-center gap-3">
          <Button
            v-if="retry"
            :disabled="isRetrying"
            @click="handleRetry"
          >
            <RefreshCw
              class="h-4 w-4 mr-2"
              :class="{ 'animate-spin': isRetrying }"
            />
            {{ retryLabel || t('error.retry') }}
          </Button>
          <Button
            v-if="backTo"
            variant="outline"
            as-child
          >
            <router-link :to="backTo">
              <ArrowLeft class="h-4 w-4 mr-2" />
              {{ backLabel || t('error.back') }}
            </router-link>
          </Button>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
