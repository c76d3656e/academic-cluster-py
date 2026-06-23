<script setup lang="ts">
import { computed } from 'vue'
import type { CommandItemProps } from './types'

const props = withDefaults(defineProps<CommandItemProps>(), {
  disabled: false,
  selected: false,
})

const emit = defineEmits<{
  select: [value: string]
}>()

const classes = computed(() => [
  'relative flex cursor-default select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none',
  {
    'bg-accent text-accent-foreground': props.selected,
    'pointer-events-none opacity-50': props.disabled,
    'hover:bg-accent hover:text-accent-foreground cursor-pointer': !props.disabled,
  },
])
</script>

<template>
  <div
    :class="classes"
    @click="!disabled && emit('select', value)"
  >
    <slot />
  </div>
</template>
