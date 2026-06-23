<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SliderProps } from './types'

const props = withDefaults(defineProps<SliderProps>(), {
  modelValue: 0,
  min: 0,
  max: 100,
  step: 1,
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: number | number[]]
}>()

const isDragging = ref(false)
const sliderRef = ref<HTMLDivElement>()

const percentage = computed(() => {
  if (Array.isArray(props.modelValue)) {
    return props.modelValue.map((v) => {
      if (props.max === props.min) return 0
      return ((v - props.min) / (props.max - props.min)) * 100
    })
  }
  if (props.max === props.min) return 0
  return ((props.modelValue - props.min) / (props.max - props.min)) * 100
})

const thumbStyle = computed(() => {
  if (Array.isArray(percentage.value)) {
    return percentage.value.map((p) => ({ left: `${p}%` }))
  }
  return { left: `${percentage.value}%` }
})

const trackFillStyle = computed(() => {
  if (Array.isArray(percentage.value)) {
    const min = Math.min(...percentage.value)
    const max = Math.max(...percentage.value)
    return { left: `${min}%`, width: `${max - min}%` }
  }
  return { width: `${percentage.value}%` }
})

function handleMouseDown(e: MouseEvent) {
  if (props.disabled) return
  isDragging.value = true
  updateValue(e)

  const handleMouseMove = (e: MouseEvent) => {
    if (isDragging.value) {
      updateValue(e)
    }
  }

  const handleMouseUp = () => {
    isDragging.value = false
    document.removeEventListener('mousemove', handleMouseMove)
    document.removeEventListener('mouseup', handleMouseUp)
  }

  document.addEventListener('mousemove', handleMouseMove)
  document.addEventListener('mouseup', handleMouseUp)
}

function updateValue(e: MouseEvent) {
  if (!sliderRef.value) return

  const rect = sliderRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const pct = Math.max(0, Math.min(1, x / rect.width))
  const rawValue = props.min + pct * (props.max - props.min)
  const steppedValue = Math.round(rawValue / props.step) * props.step
  const clampedValue = Math.max(props.min, Math.min(props.max, steppedValue))

  if (Array.isArray(props.modelValue)) {
    // For range slider, update the closest thumb
    const distances = props.modelValue.map((v) => Math.abs(v - clampedValue))
    const closestIndex = distances.indexOf(Math.min(...distances))
    const newValue = [...props.modelValue]
    newValue[closestIndex] = clampedValue
    emit('update:modelValue', newValue)
  } else {
    emit('update:modelValue', clampedValue)
  }
}
</script>

<template>
  <div
    ref="sliderRef"
    class="relative flex w-full touch-none select-none items-center"
    :class="{ 'opacity-50 cursor-not-allowed': disabled, 'cursor-pointer': !disabled }"
    @mousedown="handleMouseDown"
  >
    <div class="relative h-2 w-full grow overflow-hidden rounded-full bg-secondary">
      <div
        class="absolute h-full bg-primary"
        :style="trackFillStyle"
      />
    </div>
    <template v-if="Array.isArray(thumbStyle)">
      <div
        v-for="(style, index) in thumbStyle"
        :key="index"
        class="block h-5 w-5 rounded-full border-2 border-primary bg-background ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50"
        :style="style"
        :class="{ 'cursor-grab': !disabled, 'cursor-not-allowed': disabled }"
      />
    </template>
    <div
      v-else
      class="block h-5 w-5 rounded-full border-2 border-primary bg-background ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50"
      :style="thumbStyle"
      :class="{ 'cursor-grab': !disabled, 'cursor-not-allowed': disabled }"
    />
  </div>
</template>
