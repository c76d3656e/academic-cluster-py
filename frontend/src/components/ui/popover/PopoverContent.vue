<script setup lang="ts">
import type { PopoverContentProps } from './types'

const props = withDefaults(defineProps<PopoverContentProps>(), {
  align: 'center',
  side: 'bottom',
  sideOffset: 4,
})
</script>

<template>
  <div
    class="z-50 w-72 rounded-md border bg-popover p-4 text-popover-foreground shadow-md outline-none"
    :class="{
      'left-0': align === 'start',
      'right-0': align === 'end',
      'left-1/2 -translate-x-1/2': align === 'center',
    }"
  >
    <slot />
  </div>
</template>
