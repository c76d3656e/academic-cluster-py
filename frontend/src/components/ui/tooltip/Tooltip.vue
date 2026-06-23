<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TooltipProps } from './types'

const props = withDefaults(defineProps<TooltipProps>(), {
  content: '',
  placement: 'top',
  disabled: false,
  delay: 200,
})

const isVisible = ref(false)
const timeoutId = ref<number | null>(null)

const tooltipClass = computed(() => {
  const base = 'absolute z-50 px-3 py-1.5 text-xs leading-none rounded-md bg-popover text-popover-foreground border shadow-md whitespace-nowrap pointer-events-none'

  switch (props.placement) {
    case 'top':
      return `${base} bottom-full left-1/2 -translate-x-1/2 mb-2`
    case 'bottom':
      return `${base} top-full left-1/2 -translate-x-1/2 mt-2`
    case 'left':
      return `${base} right-full top-1/2 -translate-y-1/2 mr-2`
    case 'right':
      return `${base} left-full top-1/2 -translate-y-1/2 ml-2`
    default:
      return base
  }
})

function showTooltip() {
  if (props.disabled) return
  if (timeoutId.value) {
    clearTimeout(timeoutId.value)
  }
  timeoutId.value = window.setTimeout(() => {
    isVisible.value = true
  }, props.delay)
}

function hideTooltip() {
  if (timeoutId.value) {
    clearTimeout(timeoutId.value)
    timeoutId.value = null
  }
  isVisible.value = false
}
</script>

<template>
  <div
    class="relative inline-flex"
    @mouseenter="showTooltip"
    @mouseleave="hideTooltip"
    @focus="showTooltip"
    @blur="hideTooltip"
  >
    <slot />
    <Teleport to="body">
      <div
        v-if="isVisible && content"
        :class="tooltipClass"
      >
        {{ content }}
      </div>
    </Teleport>
  </div>
</template>
