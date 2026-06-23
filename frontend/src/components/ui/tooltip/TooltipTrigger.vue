<script setup lang="ts">
import type { TooltipTriggerProps } from './types'

const props = withDefaults(defineProps<TooltipTriggerProps>(), {
  asChild: false,
})
</script>

<template>
  <div v-if="asChild">
    <slot />
  </div>
  <button v-else>
    <slot />
  </button>
</template>
