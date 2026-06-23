<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import AvatarComponent from './Avatar.vue'
import type { AvatarGroupProps, AvatarProps } from './types'

const props = withDefaults(defineProps<AvatarGroupProps>(), {
  max: 5,
  size: 'md',
  spacing: 'normal',
  showCount: true,
})

const { t } = useI18n()

// 计算显示的头像
const displayAvatars = computed(() => {
  if (props.avatars.length <= props.max) {
    return props.avatars
  }

  return props.avatars.slice(0, props.max)
})

// 计算剩余数量
const remainingCount = computed(() => {
  return Math.max(0, props.avatars.length - props.max)
})

// 计算间距样式
const spacingClass = computed(() => {
  switch (props.spacing) {
    case 'tight':
      return '-space-x-2'
    case 'normal':
      return '-space-x-3'
    case 'loose':
      return '-space-x-4'
    default:
      return '-space-x-3'
  }
})

// 计算尺寸样式
const sizeClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'h-6 w-6 text-xs'
    case 'md':
      return 'h-8 w-8 text-sm'
    case 'lg':
      return 'h-10 w-10 text-base'
    case 'xl':
      return 'h-12 w-12 text-lg'
    default:
      return 'h-8 w-8 text-sm'
  }
})
</script>

<template>
  <div class="flex items-center" :class="spacingClass">
    <!-- 头像列表 -->
    <AvatarComponent
      v-for="(avatar, index) in displayAvatars"
      :key="index"
      :src="avatar.src"
      :alt="avatar.alt"
      :fallback="avatar.fallback"
      :size="size"
      :shape="avatar.shape"
      :status="avatar.status"
      :border="true"
      class="relative"
    />

    <!-- 剩余数量 -->
    <div
      v-if="remainingCount > 0 && showCount"
      :class="[
        sizeClass,
        'rounded-full bg-muted flex items-center justify-center text-muted-foreground font-medium border-2 border-background',
      ]"
    >
      +{{ remainingCount }}
    </div>
  </div>
</template>
