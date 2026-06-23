<script setup lang="ts">
import type { CommandGroupProps } from './types'

const props = defineProps<CommandGroupProps>()
</script>

<template>
  <div class="overflow-hidden p-1 text-foreground">
    <div v-if="heading" class="px-2 py-1.5 text-xs font-medium text-muted-foreground">
      {{ heading }}
    </div>
    <slot />
  </div>
</template>
