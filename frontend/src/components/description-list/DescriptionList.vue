<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Copy, Check } from 'lucide-vue-next'
import { ref } from 'vue'
import type { DescriptionListProps, DescriptionItem } from './types'

const props = withDefaults(defineProps<DescriptionListProps>(), {
  variant: 'default',
  size: 'md',
  columns: 1,
  labelWidth: '120px',
  showCopy: true,
  onCopy: undefined,
})

const { t } = useI18n()

const copiedIndex = ref<number | null>(null)

// 计算可见项目
const visibleItems = computed(() => {
  return props.items.filter((item) => !item.hidden)
})

// 计算网格样式
const gridClass = computed(() => {
  switch (props.columns) {
    case 1:
      return 'grid-cols-1'
    case 2:
      return 'grid-cols-1 md:grid-cols-2'
    case 3:
      return 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3'
    default:
      return 'grid-cols-1'
  }
})

// 计算尺寸样式
const sizeClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'text-sm'
    case 'md':
      return 'text-base'
    case 'lg':
      return 'text-lg'
    default:
      return 'text-base'
  }
})

// 计算变体样式
const variantClass = computed(() => {
  switch (props.variant) {
    case 'bordered':
      return 'border rounded-lg'
    case 'striped':
      return 'divide-y'
    default:
      return ''
  }
})

// 格式化值
function formatValue(item: DescriptionItem): string {
  if (item.formatter) {
    return item.formatter(item.value)
  }

  if (item.value === null || item.value === undefined) {
    return '-'
  }

  if (typeof item.value === 'boolean') {
    return item.value ? t('common.yes') : t('common.no')
  }

  if (item.value instanceof Date) {
    return item.value.toLocaleString()
  }

  return String(item.value)
}

// 复制值
async function copyValue(value: string, index: number) {
  try {
    await navigator.clipboard.writeText(value)
    copiedIndex.value = index
    setTimeout(() => {
      copiedIndex.value = null
    }, 2000)
    props.onCopy?.(value)
  } catch (error) {
    console.error('Failed to copy:', error)
  }
}
</script>

<template>
  <div :class="[gridClass, variantClass, sizeClass]">
    <div
      v-for="(item, index) in visibleItems"
      :key="index"
      class="flex items-start gap-4 py-3"
      :class="{
        'px-4': variant === 'bordered',
        'even:bg-muted/50 px-4': variant === 'striped',
      }"
    >
      <!-- 标签 -->
      <div
        class="flex-shrink-0 font-medium text-muted-foreground"
        :style="{ width: labelWidth }"
      >
        <div class="flex items-center gap-2">
          <span v-if="item.icon">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </div>
      </div>

      <!-- 值 -->
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2">
          <span class="break-words">{{ formatValue(item) }}</span>
          <Button
            v-if="showCopy && item.copyable && item.value !== null && item.value !== undefined"
            variant="ghost"
            size="sm"
            class="h-6 w-6 p-0 flex-shrink-0"
            @click="copyValue(formatValue(item), index)"
          >
            <Check v-if="copiedIndex === index" class="h-3 w-3 text-green-500" />
            <Copy v-else class="h-3 w-3" />
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>
