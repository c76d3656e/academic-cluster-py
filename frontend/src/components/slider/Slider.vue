<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Slider } from '@/components/ui/slider'
import { Badge } from '@/components/ui/badge'
import type { SliderProps } from './types'

const props = withDefaults(defineProps<SliderProps>(), {
  modelValue: 0,
  min: 0,
  max: 100,
  step: 1,
  disabled: false,
  showValue: true,
  showTicks: false,
  showTooltip: true,
  orientation: 'horizontal',
  range: false,
  marks: undefined,
  formatValue: undefined,
  onUpdate: undefined,
  onChange: undefined,
})

const { t } = useI18n()

const currentValue = ref(props.modelValue)

// 计算显示的值
const displayValue = computed(() => {
  if (Array.isArray(currentValue.value)) {
    return currentValue.value.map((v) => formatValue(v))
  }
  return formatValue(currentValue.value)
})

// 格式化值
function formatValue(value: number): string {
  if (props.formatValue) {
    return props.formatValue(value)
  }
  return value.toString()
}

// 处理值变化
function handleValueChange(value: number | number[]) {
  currentValue.value = value
  emitChange()
}

// 触发变化事件
function emitChange() {
  props.onUpdate?.(currentValue.value)
  props.onChange?.(currentValue.value)
}

// 计算刻度位置
const tickPositions = computed(() => {
  if (!props.showTicks) return []

  const positions: { value: number; position: number }[] = []
  const range = props.max - props.min
  const tickCount = Math.floor(range / props.step)

  for (let i = 0; i <= tickCount; i++) {
    const value = props.min + i * props.step
    const position = (value / range) * 100
    positions.push({ value, position })
  }

  return positions
})

// 计算标记位置
const markPositions = computed(() => {
  if (!props.marks) return []

  return props.marks.map((mark) => ({
    ...mark,
    position: ((mark.value - props.min) / (props.max - props.min)) * 100,
  }))
})

// 监听 modelValue 变化
watch(
  () => props.modelValue,
  (newValue) => {
    currentValue.value = newValue
  }
)
</script>

<template>
  <div class="relative">
    <!-- 滑块容器 -->
    <div
      class="relative"
      :class="{
        'h-64 w-6': orientation === 'vertical',
        'w-full': orientation === 'horizontal',
      }"
    >
      <!-- 滑块 -->
      <Slider
        :model-value="currentValue"
        :min="min"
        :max="max"
        :step="step"
        :disabled="disabled"
        :orientation="orientation"
        @update:model-value="handleValueChange"
      />

      <!-- 刻度 -->
      <div
        v-if="showTicks"
        class="absolute"
        :class="{
          'left-0 right-0 top-full mt-1': orientation === 'horizontal',
          'top-0 bottom-0 left-full ml-1': orientation === 'vertical',
        }"
      >
        <div
          v-for="tick in tickPositions"
          :key="tick.value"
          class="absolute text-xs text-muted-foreground"
          :class="{
            'transform -translate-x-1/2': orientation === 'horizontal',
            'transform -translate-y-1/2': orientation === 'vertical',
          }"
          :style="{
            left: orientation === 'horizontal' ? `${tick.position}%` : undefined,
            top: orientation === 'vertical' ? `${tick.position}%` : undefined,
          }"
        >
          {{ formatValue(tick.value) }}
        </div>
      </div>

      <!-- 标记 -->
      <div
        v-if="marks"
        class="absolute"
        :class="{
          'left-0 right-0 top-full mt-4': orientation === 'horizontal',
          'top-0 bottom-0 left-full ml-4': orientation === 'vertical',
        }"
      >
        <div
          v-for="mark in markPositions"
          :key="mark.value"
          class="absolute text-sm"
          :class="{
            'transform -translate-x-1/2': orientation === 'horizontal',
            'transform -translate-y-1/2': orientation === 'vertical',
          }"
          :style="{
            left: orientation === 'horizontal' ? `${mark.position}%` : undefined,
            top: orientation === 'vertical' ? `${mark.position}%` : undefined,
          }"
        >
          {{ mark.label }}
        </div>
      </div>
    </div>

    <!-- 当前值 -->
    <div
      v-if="showValue"
      class="mt-2 text-center"
    >
      <Badge variant="secondary">
        {{ displayValue }}
      </Badge>
    </div>
  </div>
</template>
