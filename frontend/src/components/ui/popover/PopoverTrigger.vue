<script setup lang="ts">
import type { PopoverTriggerProps } from './types'

const props = withDefaults(defineProps<PopoverTriggerProps>(), {
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
