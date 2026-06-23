<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import type { SwitchProps } from './types'

const props = withDefaults(defineProps<SwitchProps>(), {
  modelValue: false,
  disabled: false,
  size: 'md',
  label: undefined,
  description: undefined,
  required: false,
  onUpdate: undefined,
  onChange: undefined,
})

const { t } = useI18n()

const isChecked = ref(props.modelValue)

// 计算尺寸样式
const sizeClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'h-4 w-7'
    case 'md':
      return 'h-5 w-9'
    case 'lg':
      return 'h-6 w-11'
    default:
      return 'h-5 w-9'
  }
})

// 处理值变化
function handleCheckedChange(value: boolean) {
  isChecked.value = value
  emitChange()
}

// 触发变化事件
function emitChange() {
  props.onUpdate?.(isChecked.value)
  props.onChange?.(isChecked.value)
}

// 监听 modelValue 变化
watch(
  () => props.modelValue,
  (newValue) => {
    isChecked.value = newValue
  }
)
</script>

<template>
  <div class="flex items-center gap-3">
    <Switch
      :checked="isChecked"
      :disabled="disabled"
      :class="sizeClass"
      @update:checked="handleCheckedChange"
    />
    <div v-if="label || description" class="flex flex-col gap-1">
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
    </div>
  </div>
</template>
