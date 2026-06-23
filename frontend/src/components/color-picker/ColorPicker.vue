<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Pipette, Check } from 'lucide-vue-next'
import type { ColorPickerProps } from './types'

const props = withDefaults(defineProps<ColorPickerProps>(), {
  modelValue: '#000000',
  format: 'hex',
  showAlpha: false,
  showPresets: true,
  showInput: true,
  showEyeDropper: false,
  disabled: false,
  presets: () => [
    '#000000',
    '#ffffff',
    '#ef4444',
    '#f97316',
    '#f59e0b',
    '#84cc16',
    '#22c55e',
    '#14b8a6',
    '#06b6d4',
    '#3b82f6',
    '#6366f1',
    '#8b5cf6',
    '#a855f7',
    '#d946ef',
    '#ec4899',
    '#f43f5e',
  ],
  onUpdate: undefined,
  onChange: undefined,
})

const { t } = useI18n()

const isOpen = ref(false)
const currentColor = ref(props.modelValue)
const hexInput = ref(props.modelValue)

// 计算颜色值
const colorValue = computed(() => {
  return currentColor.value
})

// 处理颜色变化
function handleColorChange(event: Event) {
  const target = event.target as HTMLInputElement
  currentColor.value = target.value
  hexInput.value = target.value
  emitChange()
}

// 处理十六进制输入
function handleHexInput(event: Event) {
  const target = event.target as HTMLInputElement
  let value = target.value

  // 确保以 # 开头
  if (!value.startsWith('#')) {
    value = '#' + value
  }

  // 验证十六进制颜色
  if (/^#[0-9A-Fa-f]{6}$/.test(value)) {
    currentColor.value = value
    emitChange()
  }

  hexInput.value = value
}

// 选择预设颜色
function selectPreset(color: string) {
  currentColor.value = color
  hexInput.value = color
  emitChange()
}

// 触发变化事件
function emitChange() {
  props.onUpdate?.(currentColor.value)
  props.onChange?.(currentColor.value)
}

// 监听 modelValue 变化
watch(
  () => props.modelValue,
  (newValue) => {
    if (newValue !== currentColor.value) {
      currentColor.value = newValue
      hexInput.value = newValue
    }
  }
)
</script>

<template>
  <Popover v-model:open="isOpen">
    <PopoverTrigger as-child>
      <Button
        variant="outline"
        class="w-10 h-10 p-0"
        :disabled="disabled"
      >
        <div
          class="w-6 h-6 rounded border"
          :style="{ backgroundColor: colorValue }"
        />
      </Button>
    </PopoverTrigger>
    <PopoverContent class="w-64">
      <div class="space-y-4">
        <!-- 颜色选择器 -->
        <div class="flex items-center gap-2">
          <input
            type="color"
            :value="currentColor"
            class="w-full h-32 rounded cursor-pointer"
            :disabled="disabled"
            @input="handleColorChange"
          />
        </div>

        <!-- 十六进制输入 -->
        <div v-if="showInput" class="flex items-center gap-2">
          <span class="text-sm font-medium w-8">HEX</span>
          <Input
            :value="hexInput"
            :disabled="disabled"
            class="flex-1"
            @input="handleHexInput"
          />
        </div>

        <!-- 预设颜色 -->
        <div v-if="showPresets" class="space-y-2">
          <span class="text-sm font-medium">{{ t('colorPicker.presets') }}</span>
          <div class="grid grid-cols-8 gap-1">
            <button
              v-for="color in presets"
              :key="color"
              class="w-6 h-6 rounded border cursor-pointer hover:scale-110 transition-transform"
              :class="{ 'ring-2 ring-primary': currentColor === color }"
              :style="{ backgroundColor: color }"
              :disabled="disabled"
              @click="selectPreset(color)"
            >
              <Check
                v-if="currentColor === color"
                class="h-3 w-3 text-white mx-auto"
              />
            </button>
          </div>
        </div>

        <!-- 取色器按钮 -->
        <Button
          v-if="showEyeDropper"
          variant="outline"
          size="sm"
          class="w-full"
          :disabled="disabled"
        >
          <Pipette class="h-4 w-4 mr-2" />
          {{ t('colorPicker.eyeDropper') }}
        </Button>
      </div>
    </PopoverContent>
  </Popover>
</template>
