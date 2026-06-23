<script setup lang="ts">
import { computed } from 'vue'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type { TooltipProps } from './types'

const props = withDefaults(defineProps<TooltipProps>(), {
  side: 'top',
  align: 'center',
  delay: 300,
  disabled: false,
  variant: 'default',
})

// 计算变体样式
const variantClass = computed(() => {
  switch (props.variant) {
    case 'info':
      return 'bg-blue-500 text-white'
    case 'success':
      return 'bg-green-500 text-white'
    case 'warning':
      return 'bg-yellow-500 text-black'
    case 'error':
      return 'bg-red-500 text-white'
    default:
      return 'bg-primary text-primary-foreground'
  }
})
</script>

<template>
  <TooltipProvider :delay-duration="delay">
    <Tooltip :disabled="disabled">
      <TooltipTrigger as-child>
        <slot />
      </TooltipTrigger>
      <TooltipContent
        :side="side"
        :align="align"
        :class="variantClass"
      >
        {{ content }}
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
