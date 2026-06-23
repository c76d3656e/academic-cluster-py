<script setup lang="ts">
import { computed } from 'vue'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import type { CommandDialogProps } from './types'

const props = withDefaults(defineProps<CommandDialogProps>(), {
  open: false,
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
  <Dialog v-model:open="isOpen">
    <DialogContent class="overflow-hidden p-0 shadow-lg">
      <slot />
    </DialogContent>
  </Dialog>
</template>
