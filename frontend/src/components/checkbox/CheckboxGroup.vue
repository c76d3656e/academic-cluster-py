<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import type { CheckboxGroupProps, CheckboxOption } from './types'

const props = withDefaults(defineProps<CheckboxGroupProps>(), {
  modelValue: () => [],
  disabled: false,
  orientation: 'vertical',
  size: 'md',
  label: undefined,
  description: undefined,
  required: false,
  onUpdate: undefined,
  onChange: undefined,
})

const { t } = useI18n()

const selectedValues = ref<(string | number)[]>(props.modelValue)

// 计算容器样式
const containerClass = computed(() => {
  return props.orientation === 'horizontal' ? 'flex flex-wrap gap-4' : 'space-y-2'
})

// 计算尺寸样式
const sizeClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'h-4 w-4'
    case 'md':
      return 'h-5 w-5'
    case 'lg':
      return 'h-6 w-6'
    default:
      return 'h-5 w-5'
  }
})

// 处理复选框变化
function handleCheckboxChange(optionValue: string | number, checked: boolean) {
  if (checked) {
    selectedValues.value = [...selectedValues.value, optionValue]
  } else {
    selectedValues.value = selectedValues.value.filter((v) => v !== optionValue)
  }
  emitChange()
}

// 触发变化事件
function emitChange() {
  props.onUpdate?.(selectedValues.value)
  props.onChange?.(selectedValues.value)
}

// 监听 modelValue 变化
watch(
  () => props.modelValue,
  (newValue) => {
    selectedValues.value = newValue
  }
)
</script>

<template>
  <div class="space-y-2">
    <Label
      v-if="label"
      class="text-sm font-medium"
      :class="{ 'text-muted-foreground': disabled }"
    >
      {{ label }}
      <span v-if="required" class="text-destructive">*</span>
    </Label>
    <p
      v-if="description"
      class="text-sm text-muted-foreground"
    >
      {{ description }}
    </p>
    <div :class="containerClass">
      <div
        v-for="option in options"
        :key="option.value"
        class="flex items-center gap-2"
      >
        <Checkbox
          :checked="selectedValues.includes(option.value)"
          :disabled="option.disabled || disabled"
          :class="sizeClass"
          @update:checked="handleCheckboxChange(option.value, $event)"
        />
        <div class="flex flex-col gap-1">
          <Label
            class="text-sm font-medium"
            :class="{
              'text-muted-foreground': option.disabled || disabled,
              'cursor-pointer': !option.disabled && !disabled,
            }"
          >
            {{ option.label }}
          </Label>
          <p
            v-if="option.description"
            class="text-sm text-muted-foreground"
          >
            {{ option.description }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
