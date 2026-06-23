<script setup lang="ts">
import type { TooltipContentProps } from './types'

const props = withDefaults(defineProps<TooltipContentProps>(), {
  side: 'top',
  align: 'center',
})
</script>

<template>
  <div
    class="z-50 overflow-hidden rounded-md border bg-popover px-3 py-1.5 text-sm text-popover-foreground shadow-md animate-in fade-in-0 zoom-in-95"
  >
    <slot />
  </div>
</template>
