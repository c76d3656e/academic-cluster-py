<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import {
  Tabs as TabsRoot,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import type { TabsProps, TabItem } from './types'

const props = withDefaults(defineProps<TabsProps>(), {
  defaultTab: undefined,
  onChange: undefined,
  variant: 'default',
  size: 'md',
  fullWidth: false,
})

const { t } = useI18n()

const activeTab = ref(props.defaultTab || props.items[0]?.id)

// 计算标签列表样式
const tabsListClass = computed(() => {
  const classes: string[] = []

  switch (props.variant) {
    case 'pills':
      classes.push('bg-muted p-1 rounded-lg')
      break
    case 'underline':
      classes.push('border-b')
      break
  }

  if (props.fullWidth) {
    classes.push('w-full')
  }

  return classes.join(' ')
})

// 计算标签触发器样式
const tabsTriggerClass = computed(() => {
  const classes: string[] = []

  switch (props.variant) {
    case 'pills':
      classes.push('rounded-md')
      break
    case 'underline':
      classes.push('rounded-none border-b-2 border-transparent')
      break
  }

  switch (props.size) {
    case 'sm':
      classes.push('text-xs px-2 py-1')
      break
    case 'md':
      classes.push('text-sm px-3 py-1.5')
      break
    case 'lg':
      classes.push('text-base px-4 py-2')
      break
  }

  if (props.fullWidth) {
    classes.push('flex-1')
  }

  return classes.join(' ')
})

// 处理标签切换
function handleTabChange(tabId: string | number) {
  const tabIdStr = String(tabId)
  activeTab.value = tabIdStr
  props.onChange?.(tabIdStr)
}

// 监听默认标签变化
watch(
  () => props.defaultTab,
  (newTab) => {
    if (newTab) {
      activeTab.value = newTab
    }
  }
)
</script>

<template>
  <TabsRoot v-model="activeTab" @update:model-value="handleTabChange">
    <TabsList :class="tabsListClass">
      <TabsTrigger
        v-for="item in items"
        :key="item.id"
        :value="item.id"
        :disabled="item.disabled"
        :class="tabsListClass"
      >
        <div class="flex items-center gap-2">
          <span v-if="item.icon">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
          <Badge
            v-if="item.badge !== undefined"
            variant="secondary"
            class="ml-1"
          >
            {{ item.badge }}
          </Badge>
        </div>
      </TabsTrigger>
    </TabsList>

    <TabsContent
      v-for="item in items"
      :key="item.id"
      :value="item.id"
    >
      <slot :name="item.id" :tab="item">
        <component v-if="item.content" :is="item.content" />
      </slot>
    </TabsContent>
  </TabsRoot>
</template>
