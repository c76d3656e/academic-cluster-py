<script setup lang="ts">
import type { TooltipProviderProps } from './types'

const props = withDefaults(defineProps<TooltipProviderProps>(), {
  delayDuration: 200,
})
</script>

<template>
  <slot />
</template>
