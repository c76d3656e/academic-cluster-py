<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from '@/i18n'
import { Skeleton } from '@/components/ui/skeleton'
import { ImageIcon } from 'lucide-vue-next'
import type { ImageProps } from './types'

const props = withDefaults(defineProps<ImageProps>(), {
  width: undefined,
  height: undefined,
  objectFit: 'cover',
  loading: 'lazy',
  placeholder: undefined,
  fallback: undefined,
  rounded: false,
  bordered: false,
  zoomable: false,
  preview: false,
  onLoad: undefined,
  onError: undefined,
})

const { t } = useI18n()

const isLoaded = ref(false)
const isError = ref(false)
const isZoomed = ref(false)

// 计算容器样式
const containerStyle = computed(() => {
  const style: Record<string, string> = {}

  if (props.width) {
    style.width = typeof props.width === 'number' ? `${props.width}px` : props.width
  }

  if (props.height) {
    style.height = typeof props.height === 'number' ? `${props.height}px` : props.height
  }

  return style
})

// 计算图像样式
const imageStyle = computed(() => {
  return {
    objectFit: props.objectFit,
  }
})

// 计算容器类名
const containerClass = computed(() => {
  const classes: string[] = ['relative overflow-hidden']

  if (props.rounded === true) {
    classes.push('rounded-lg')
  } else if (props.rounded === 'sm') {
    classes.push('rounded-sm')
  } else if (props.rounded === 'md') {
    classes.push('rounded-md')
  } else if (props.rounded === 'lg') {
    classes.push('rounded-lg')
  } else if (props.rounded === 'full') {
    classes.push('rounded-full')
  }

  if (props.bordered) {
    classes.push('border border-muted')
  }

  if (props.zoomable) {
    classes.push('cursor-zoom-in')
  }

  return classes.join(' ')
})

// 计算图像类名
const imageClass = computed(() => {
  const classes: string[] = ['w-full h-full transition-opacity duration-300']

  if (isLoaded.value) {
    classes.push('opacity-100')
  } else {
    classes.push('opacity-0')
  }

  if (props.zoomable && isZoomed.value) {
    classes.push('scale-150')
  }

  return classes.join(' ')
})

// 处理图像加载
function handleLoad() {
  isLoaded.value = true
  props.onLoad?.()
}

// 处理图像错误
function handleError(event: Event) {
  isError.value = true
  props.onError?.(event)
}

// 切换缩放状态
function toggleZoom() {
  if (props.zoomable) {
    isZoomed.value = !isZoomed.value
  }
}

// 处理图像点击
function handleClick() {
  if (props.preview) {
    // 这里可以打开图像预览对话框
    // 为了简化，这里只是切换缩放状态
    toggleZoom()
  } else if (props.zoomable) {
    toggleZoom()
  }
}
</script>

<template>
  <div
    :class="containerClass"
    :style="containerStyle"
    @click="handleClick"
  >
    <!-- 加载占位符 -->
    <div
      v-if="!isLoaded && !isError"
      class="absolute inset-0 flex items-center justify-center bg-muted"
    >
      <Skeleton v-if="!placeholder" class="w-full h-full" />
      <img
        v-else
        :src="placeholder"
        :alt="alt"
        class="w-full h-full object-cover"
      />
    </div>

    <!-- 错误状态 -->
    <div
      v-if="isError"
      class="absolute inset-0 flex flex-col items-center justify-center bg-muted text-muted-foreground"
    >
      <ImageIcon class="h-8 w-8 mb-2" />
      <span class="text-sm">{{ t('image.loadError') }}</span>
      <img
        v-if="fallback"
        :src="fallback"
        :alt="alt"
        class="w-full h-full object-cover mt-2"
      />
    </div>

    <!-- 图像 -->
    <img
      :src="src"
      :alt="alt"
      :loading="loading"
      :style="imageStyle"
      :class="imageClass"
      @load="handleLoad"
      @error="handleError"
    />
  </div>
</template>
