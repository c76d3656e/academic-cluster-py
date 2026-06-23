<script setup lang="ts">
import type { CommandListProps } from './types'

const props = withDefaults(defineProps<CommandListProps>(), {
  maxHeight: '300px',
})
</script>

<template>
  <div
    class="max-h-[300px] overflow-y-auto overflow-x-hidden"
    :style="{ maxHeight }"
  >
    <slot />
  </div>
</template>
