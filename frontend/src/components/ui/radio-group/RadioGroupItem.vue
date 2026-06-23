<script setup lang="ts">
import { computed, inject } from 'vue'
import type { RadioGroupItemProps, RadioGroupContext } from './types'

const props = withDefaults(defineProps<RadioGroupItemProps>(), {
  disabled: false,
})

const context = inject<RadioGroupContext>('radioGroup')

const isSelected = computed(() => {
  return context?.selectedValue.value === props.value
})

const isDisabled = computed(() => {
  return props.disabled || context?.disabled.value
})

const classes = computed(() => [
  'aspect-square h-4 w-4 rounded-full border border-primary text-primary ring-offset-background focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50',
  {
    'bg-primary': isSelected.value,
    'cursor-pointer': !isDisabled.value,
    'cursor-not-allowed opacity-50': isDisabled.value,
  },
])

function handleClick() {
  if (!isDisabled.value) {
    context?.select(props.value)
  }
}
</script>

<template>
  <button
    type="button"
    role="radio"
    :aria-checked="isSelected"
    :disabled="isDisabled"
    :class="classes"
    @click="handleClick"
  >
    <svg
      v-if="isSelected"
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      class="h-2.5 w-2.5 fill-current text-current"
    >
      <circle cx="12" cy="12" r="10" />
    </svg>
  </button>
</template>
