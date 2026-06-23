<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CommandProps } from './types'

const props = withDefaults(defineProps<CommandProps>(), {
  filter: undefined,
})

const searchQuery = ref('')

const filteredItems = computed(() => {
  if (!props.filter) return props.items
  return props.filter(searchQuery.value)
})
</script>

<template>
  <div class="flex h-full w-full flex-col overflow-hidden rounded-md bg-popover text-popover-foreground">
    <slot :search-query="searchQuery" :filtered-items="filteredItems" />
  </div>
</template>
