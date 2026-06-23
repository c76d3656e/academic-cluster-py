<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { CheckCircle, XCircle, AlertCircle, Info, Circle } from 'lucide-vue-next'
import type { TimelineProps, TimelineItem } from './types'

const props = withDefaults(defineProps<TimelineProps>(), {
  variant: 'default',
  showConnector: true,
  showTimestamp: true,
  showUser: true,
  reverse: false,
})

const { t } = useI18n()

// 计算排序后的项目
const sortedItems = computed(() => {
  const items = [...props.items]
  if (props.reverse) {
    items.reverse()
  }
  return items
})

// 获取状态图标
function getStatusIcon(status?: string) {
  switch (status) {
    case 'success':
      return CheckCircle
    case 'error':
      return XCircle
    case 'warning':
      return AlertCircle
    case 'info':
      return Info
    default:
      return Circle
  }
}

// 获取状态颜色
function getStatusColor(status?: string) {
  switch (status) {
    case 'success':
      return 'text-green-500'
    case 'error':
      return 'text-red-500'
    case 'warning':
      return 'text-yellow-500'
    case 'info':
      return 'text-blue-500'
    default:
      return 'text-muted-foreground'
  }
}

// 获取状态背景颜色
function getStatusBgColor(status?: string) {
  switch (status) {
    case 'success':
      return 'bg-green-100'
    case 'error':
      return 'bg-red-100'
    case 'warning':
      return 'bg-yellow-100'
    case 'info':
      return 'bg-blue-100'
    default:
      return 'bg-muted'
  }
}

// 格式化时间戳
function formatTimestamp(timestamp: Date | string): string {
  const date = new Date(timestamp)
  return date.toLocaleString()
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
</script>

<template>
  <div class="relative">
    <div
      v-for="(item, index) in sortedItems"
      :key="item.id"
      class="relative flex gap-4"
      :class="{
        'pb-8': index < sortedItems.length - 1,
      }"
    >
      <!-- 连接线 -->
      <div
        v-if="showConnector && index < sortedItems.length - 1"
        class="absolute left-4 top-8 w-0.5 h-full"
        :class="getStatusColor(item.status)"
      />

      <!-- 图标 -->
      <div class="relative z-10">
        <div
          class="flex items-center justify-center w-8 h-8 rounded-full"
          :class="getStatusBgColor(item.status)"
        >
          <component
            :is="getStatusIcon(item.status)"
            class="h-4 w-4"
            :class="getStatusColor(item.status)"
          />
        </div>
      </div>

      <!-- 内容 -->
      <div class="flex-1 min-w-0">
        <!-- 标题和时间戳 -->
        <div class="flex items-start justify-between gap-2">
          <div>
            <div class="font-medium">{{ item.title }}</div>
            <div
              v-if="item.description && variant !== 'compact'"
              class="text-sm text-muted-foreground mt-1"
            >
              {{ item.description }}
            </div>
          </div>
          <div
            v-if="showTimestamp"
            class="text-xs text-muted-foreground whitespace-nowrap"
          >
            {{ formatTimestamp(item.timestamp) }}
          </div>
        </div>

        <!-- 用户信息 -->
        <div
          v-if="showUser && item.user && variant === 'detailed'"
          class="flex items-center gap-2 mt-2"
        >
          <Avatar class="h-6 w-6">
            <AvatarImage v-if="item.user.avatar" :src="item.user.avatar" />
            <AvatarFallback class="text-xs">
              {{ getInitials(item.user.name) }}
            </AvatarFallback>
          </Avatar>
          <span class="text-sm text-muted-foreground">{{ item.user.name }}</span>
        </div>

        <!-- 元数据 -->
        <div
          v-if="item.metadata && variant === 'detailed'"
          class="flex flex-wrap gap-2 mt-2"
        >
          <Badge
            v-for="(value, key) in item.metadata"
            :key="key"
            variant="secondary"
            class="text-xs"
          >
            {{ key }}: {{ value }}
          </Badge>
        </div>
      </div>
    </div>
  </div>
</template>
