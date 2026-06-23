<script setup lang="ts">
import { computed } from 'vue'
import { Input } from '@/components/ui/input'
import { Search } from 'lucide-vue-next'
import type { CommandInputProps } from './types'

const props = withDefaults(defineProps<CommandInputProps>(), {
  modelValue: '',
  placeholder: 'Search...',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const modelValue = computed({
  get: () => props.modelValue ?? '',
  set: (value) => emit('update:modelValue', value),
})
</script>

<template>
  <div class="flex items-center border-b px-3">
    <Search class="mr-2 h-4 w-4 shrink-0 opacity-50" />
    <Input
      v-model="modelValue"
      :placeholder="placeholder"
      class="flex h-11 w-full rounded-md bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50 border-0 focus-visible:ring-0 focus-visible:ring-offset-0"
    />
  </div>
</template>
