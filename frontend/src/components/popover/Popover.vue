<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import type { PopoverProps } from './types'

const props = withDefaults(defineProps<PopoverProps>(), {
  side: 'bottom',
  align: 'center',
  modal: false,
  disabled: false,
  open: undefined,
  onOpenChange: undefined,
})

const isOpen = ref(props.open ?? false)

// 监听 open 属性变化
watch(
  () => props.open,
  (newOpen) => {
    if (newOpen !== undefined) {
      isOpen.value = newOpen
    }
  }
)

// 处理打开状态变化
function handleOpenChange(open: boolean) {
  isOpen.value = open
  props.onOpenChange?.(open)
}
</script>

<template>
  <Popover :open="isOpen" @update:open="handleOpenChange">
    <PopoverTrigger as-child :disabled="disabled">
      <slot name="trigger" />
    </PopoverTrigger>
    <PopoverContent
      :side="side"
      :align="align"
      :modal="modal"
    >
      <slot />
    </PopoverContent>
  </Popover>
</template>
