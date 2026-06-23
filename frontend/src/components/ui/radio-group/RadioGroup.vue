<script setup lang="ts">
import { computed, provide, ref } from 'vue'
import type { RadioGroupProps, RadioGroupContext } from './types'

const props = withDefaults(defineProps<RadioGroupProps>(), {
  modelValue: undefined,
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string | number]
}>()

const selectedValue = computed({
  get: () => props.modelValue,
  set: (value: string | number) => emit('update:modelValue', value),
})

const context: RadioGroupContext = {
  selectedValue,
  disabled: computed(() => props.disabled),
  select: (value: string | number) => {
    if (!props.disabled) {
      selectedValue.value = value
    }
  },
}

provide('radioGroup', context)
</script>

<template>
  <div class="grid gap-2" role="radiogroup">
    <slot />
  </div>
</template>
