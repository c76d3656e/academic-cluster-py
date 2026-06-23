<script setup lang="ts">
import { computed } from 'vue'
import type { CheckboxProps } from './types'

const props = withDefaults(defineProps<CheckboxProps>(), {
  modelValue: false,
  disabled: false,
  indeterminate: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const isChecked = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const classes = computed(() => [
  'peer h-4 w-4 shrink-0 rounded-sm border border-primary ring-offset-background',
  {
    'bg-primary text-primary-foreground': isChecked.value,
    'opacity-50 cursor-not-allowed': props.disabled,
    'cursor-pointer': !props.disabled,
  },
])
</script>

<template>
  <button
    type="button"
    role="checkbox"
    :aria-checked="isChecked"
    :disabled="disabled"
    :class="classes"
    @click="!disabled && (isChecked = !isChecked)"
  >
    <svg
      v-if="isChecked"
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      class="h-4 w-4"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
    <svg
      v-else-if="indeterminate"
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      class="h-4 w-4"
    >
      <line x1="5" x2="19" y1="12" y2="12" />
    </svg>
  </button>
</template>
