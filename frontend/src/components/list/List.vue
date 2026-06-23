<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Checkbox } from '@/components/ui/checkbox'
import type { ListProps, ListItem } from './types'

const props = withDefaults(defineProps<ListProps>(), {
  variant: 'default',
  size: 'md',
  selectable: false,
  selectedItems: () => [],
  showIcon: true,
  showAvatar: false,
  showBadge: true,
  showDescription: true,
  onItemClick: undefined,
  onSelectionChange: undefined,
})

const { t } = useI18n()

const selectedIds = ref<(string | number)[]>(props.selectedItems)

// 计算容器样式
const containerClass = computed(() => {
  switch (props.variant) {
    case 'bordered':
      return 'border rounded-lg'
    case 'striped':
      return 'divide-y'
    default:
      return 'space-y-1'
  }
})

// 计算项目样式
const itemClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'p-2'
    case 'md':
      return 'p-3'
    case 'lg':
      return 'p-4'
    default:
      return 'p-3'
  }
})

// 处理项目点击
function handleItemClick(item: ListItem) {
  if (item.disabled) return
  props.onItemClick?.(item)
}

// 处理选择变化
function handleSelectionChange(item: ListItem, checked: boolean) {
  if (item.disabled) return

  if (checked) {
    selectedIds.value = [...selectedIds.value, item.id]
  } else {
    selectedIds.value = selectedIds.value.filter((id) => id !== item.id)
  }
  props.onSelectionChange?.(selectedIds.value)
}

// 检查项目是否被选中
function isItemSelected(item: ListItem): boolean {
  return selectedIds.value.includes(item.id)
}

// 获取用户头像首字母
function getInitials(name: string): string {
  return name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
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
  <div :class="containerClass">
    <div
      v-for="item in items"
      :key="item.id"
      :class="[
        itemClass,
        {
          'hover:bg-accent cursor-pointer': !item.disabled,
          'opacity-50 cursor-not-allowed': item.disabled,
          'bg-accent': isItemSelected(item),
        },
      ]"
      @click="handleItemClick(item)"
    >
      <div class="flex items-center gap-3">
        <!-- 复选框 -->
        <Checkbox
          v-if="selectable"
          :checked="isItemSelected(item)"
          :disabled="item.disabled"
          @update:checked="handleSelectionChange(item, $event)"
        />

        <!-- 图标 -->
        <div
          v-if="showIcon && item.icon"
          class="flex-shrink-0"
        >
          <span class="text-lg">{{ item.icon }}</span>
        </div>

        <!-- 头像 -->
        <Avatar
          v-if="showAvatar && item.avatar"
          class="h-10 w-10"
        >
          <AvatarImage :src="item.avatar" :alt="item.title" />
          <AvatarFallback>{{ getInitials(item.title) }}</AvatarFallback>
        </Avatar>

        <!-- 内容 -->
        <div class="flex-1 min-w-0">
          <div class="font-medium">{{ item.title }}</div>
          <div
            v-if="showDescription && item.description"
            class="text-sm text-muted-foreground mt-1"
          >
            {{ item.description }}
          </div>
        </div>

        <!-- 徽章 -->
        <Badge
          v-if="showBadge && item.badge !== undefined"
          variant="secondary"
        >
          {{ item.badge }}
        </Badge>
      </div>
    </div>
  </div>
</template>
