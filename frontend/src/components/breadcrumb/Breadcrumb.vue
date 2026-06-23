<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import { RouterLink } from 'vue-router'
import { ChevronRight, Home } from 'lucide-vue-next'
import type { BreadcrumbProps, BreadcrumbItem } from './types'

const props = withDefaults(defineProps<BreadcrumbProps>(), {
  separator: '/',
  maxItems: 5,
  showHome: true,
  homeLabel: 'Home',
  homeHref: '/',
})

const { t } = useI18n()

// 计算显示的项目
const displayItems = computed(() => {
  const items = [...props.items]

  // 如果显示首页，添加到开头
  if (props.showHome) {
    items.unshift({
      label: props.homeLabel,
      href: props.homeHref,
      icon: 'home',
    })
  }

  // 如果项目数量超过最大值，进行截断
  if (items.length > props.maxItems) {
    const firstItem = items[0]
    const lastItems = items.slice(-2)
    return [firstItem, { label: '...', href: undefined }, ...lastItems]
  }

  return items
})

// 获取图标组件
function getIconComponent(icon?: string) {
  if (icon === 'home') return Home
  return null
}
</script>

<template>
  <nav aria-label="Breadcrumb" class="flex items-center space-x-1 text-sm text-muted-foreground">
    <template v-for="(item, index) in displayItems" :key="index">
      <!-- 分隔符 -->
      <ChevronRight
        v-if="index > 0"
        class="h-4 w-4"
      />

      <!-- 面包屑项目 -->
      <div class="flex items-center gap-1">
        <!-- 图标 -->
        <component
          v-if="item.icon"
          :is="getIconComponent(item.icon)"
          class="h-4 w-4"
        />

        <!-- 链接或文本 -->
        <RouterLink
          v-if="item.href && !item.current"
          :to="item.href"
          class="hover:text-foreground transition-colors"
        >
          {{ item.label }}
        </RouterLink>
        <span
          v-else
          :class="{ 'text-foreground font-medium': item.current }"
        >
          {{ item.label }}
        </span>
      </div>
    </template>
  </nav>
</template>
