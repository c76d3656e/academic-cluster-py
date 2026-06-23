<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import type { GridProps, GridItem } from './types'

const props = withDefaults(defineProps<GridProps>(), {
  columns: 3,
  gap: 'md',
  variant: 'default',
  size: 'md',
  showImage: true,
  showIcon: true,
  showBadge: true,
  showDescription: true,
  selectable: false,
  selectedItems: () => [],
  onItemClick: undefined,
  onSelectionChange: undefined,
})

const { t } = useI18n()

const selectedIds = ref<(string | number)[]>(props.selectedItems)

// 计算网格样式
const gridClass = computed(() => {
  const classes: string[] = ['grid']

  switch (props.columns) {
    case 1:
      classes.push('grid-cols-1')
      break
    case 2:
      classes.push('grid-cols-1 md:grid-cols-2')
      break
    case 3:
      classes.push('grid-cols-1 md:grid-cols-2 lg:grid-cols-3')
      break
    case 4:
      classes.push('grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4')
      break
    case 5:
      classes.push('grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5')
      break
    case 6:
      classes.push('grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6')
      break
  }

  switch (props.gap) {
    case 'sm':
      classes.push('gap-2')
      break
    case 'md':
      classes.push('gap-4')
      break
    case 'lg':
      classes.push('gap-6')
      break
  }

  return classes.join(' ')
})

// 计算卡片样式
const cardClass = computed(() => {
  switch (props.variant) {
    case 'bordered':
      return 'border'
    case 'card':
      return 'border shadow-sm'
    default:
      return ''
  }
})

// 计算卡片尺寸
const cardSize = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'p-3'
    case 'md':
      return 'p-4'
    case 'lg':
      return 'p-6'
    default:
      return 'p-4'
  }
})

// 处理项目点击
function handleItemClick(item: GridItem) {
  if (item.disabled) return
  props.onItemClick?.(item)
}

// 处理选择变化
function handleSelectionChange(item: GridItem, checked: boolean) {
  if (item.disabled) return

  if (checked) {
    selectedIds.value = [...selectedIds.value, item.id]
  } else {
    selectedIds.value = selectedIds.value.filter((id) => id !== item.id)
  }
  props.onSelectionChange?.(selectedIds.value)
}

// 检查项目是否被选中
function isItemSelected(item: GridItem): boolean {
  return selectedIds.value.includes(item.id)
}

// 监听 selectedItems 变化
watch(
  () => props.selectedItems,
  (newValue) => {
    selectedIds.value = newValue
  }
)
</script>

<template>
  <div :class="gridClass">
    <div
      v-for="item in items"
      :key="item.id"
    >
      <Card
        :class="[
          cardClass,
          {
            'hover:shadow-md cursor-pointer': !item.disabled,
            'opacity-50 cursor-not-allowed': item.disabled,
            'ring-2 ring-primary': isItemSelected(item),
          },
        ]"
        @click="handleItemClick(item)"
      >
        <CardContent :class="cardSize">
          <!-- 复选框 -->
          <div
            v-if="selectable"
            class="absolute top-2 right-2"
          >
            <Checkbox
              :checked="isItemSelected(item)"
              :disabled="item.disabled"
              @update:checked="handleSelectionChange(item, $event)"
            />
          </div>

          <!-- 图片 -->
          <div
            v-if="showImage && item.image"
            class="mb-3 rounded-md overflow-hidden"
          >
            <img
              :src="item.image"
              :alt="item.title"
              class="w-full h-32 object-cover"
            />
          </div>

          <!-- 图标 -->
          <div
            v-if="showIcon && item.icon"
            class="mb-3"
          >
            <span class="text-2xl">{{ item.icon }}</span>
          </div>

          <!-- 内容 -->
          <div class="space-y-2">
            <div class="flex items-center justify-between">
              <CardTitle class="text-base">{{ item.title }}</CardTitle>
              <Badge
                v-if="showBadge && item.badge !== undefined"
                variant="secondary"
              >
                {{ item.badge }}
              </Badge>
            </div>
            <CardDescription
              v-if="showDescription && item.description"
              class="text-sm"
            >
              {{ item.description }}
            </CardDescription>
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
