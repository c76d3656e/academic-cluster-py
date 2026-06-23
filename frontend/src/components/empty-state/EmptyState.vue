<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Inbox, Search, FileText, Users, Settings } from 'lucide-vue-next'
import type { EmptyStateProps } from './types'

const props = withDefaults(defineProps<EmptyStateProps>(), {
  description: undefined,
  icon: undefined,
  action: undefined,
  secondaryAction: undefined,
  image: undefined,
  size: 'md',
})

const { t } = useI18n()

// 获取图标组件
const iconComponent = computed(() => {
  switch (props.icon) {
    case 'inbox':
      return Inbox
    case 'search':
      return Search
    case 'file':
      return FileText
    case 'users':
      return Users
    case 'settings':
      return Settings
    default:
      return Inbox
  }
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

// 计算图标尺寸
const iconSize = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'h-8 w-8'
    case 'md':
      return 'h-12 w-12'
    case 'lg':
      return 'h-16 w-16'
    default:
      return 'h-12 w-12'
  }
})
</script>

<template>
  <Card>
    <CardContent :class="sizeClass">
      <div class="flex flex-col items-center justify-center text-center">
        <!-- 图片 -->
        <img
          v-if="image"
          :src="image"
          :alt="title"
          class="mb-4 max-w-[200px] max-h-[200px] object-contain"
        />

        <!-- 图标 -->
        <div
          v-else-if="icon"
          class="mb-4 flex items-center justify-center w-16 h-16 rounded-full bg-muted"
        >
          <component
            :is="iconComponent"
            :class="iconSize"
            class="text-muted-foreground"
          />
        </div>

        <!-- 标题 -->
        <h3 class="text-lg font-semibold mb-2">{{ title }}</h3>

        <!-- 描述 -->
        <p
          v-if="description"
          class="text-sm text-muted-foreground max-w-md mb-6"
        >
          {{ description }}
        </p>

        <!-- 操作按钮 -->
        <div class="flex items-center gap-3">
          <Button
            v-if="action"
            @click="action.onClick"
          >
            {{ action.label }}
          </Button>
          <Button
            v-if="secondaryAction"
            variant="outline"
            @click="secondaryAction.onClick"
          >
            {{ secondaryAction.label }}
          </Button>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
