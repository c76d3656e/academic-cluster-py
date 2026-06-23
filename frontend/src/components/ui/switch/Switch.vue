<script setup lang="ts">
import { computed } from 'vue'
import type { SwitchProps } from './types'

const props = withDefaults(defineProps<SwitchProps>(), {
  modelValue: false,
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const isChecked = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const classes = computed(() => [
  'peer inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50',
  {
    'bg-primary': isChecked.value,
    'bg-input': !isChecked.value,
  },
])

const thumbClasses = computed(() => [
  'pointer-events-none block h-5 w-5 rounded-full bg-background shadow-lg ring-0 transition-transform',
  {
    'translate-x-5': isChecked.value,
    'translate-x-0': !isChecked.value,
  },
])
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="isChecked"
    :disabled="disabled"
    :class="classes"
    @click="!disabled && (isChecked = !isChecked)"
  >
    <span :class="thumbClasses" />
  </button>
</template>
