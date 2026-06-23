<script setup lang="ts">
import { computed } from 'vue'
import type { PopoverProps } from './types'

const props = withDefaults(defineProps<PopoverProps>(), {
  open: false,
  disabled: false,
})

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const isOpen = computed({
  get: () => props.open,
  set: (value) => emit('update:open', value),
})
</script>

<template>
  <div class="relative inline-block">
    <slot :is-open="isOpen" :toggle="() => isOpen = !isOpen" />
  </div>
</template>
