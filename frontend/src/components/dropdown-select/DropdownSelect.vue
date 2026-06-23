<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Check, ChevronsUpDown, X } from 'lucide-vue-next'
import type { DropdownSelectProps, DropdownSelectOption } from './types'

const props = withDefaults(defineProps<DropdownSelectProps>(), {
  modelValue: undefined,
  placeholder: 'Select option...',
  disabled: false,
  clearable: true,
  searchable: false,
  multiple: false,
  maxItems: undefined,
  showIcon: false,
  showDescription: false,
  onUpdate: undefined,
  onChange: undefined,
})

const { t } = useI18n()

const selectedValues = ref<(string | number)[]>([])

// 初始化选中的值
if (props.multiple && Array.isArray(props.modelValue)) {
  selectedValues.value = props.modelValue
} else if (props.modelValue !== undefined) {
  selectedValues.value = [props.modelValue]
}

// 计算分组选项
const groupedOptions = computed(() => {
  const groups: Record<string, DropdownSelectOption[]> = {}

  for (const option of props.options) {
    const group = option.group || ''
    if (!groups[group]) {
      groups[group] = []
    }
    groups[group].push(option)
  }

  return groups
})

// 计算显示的值
const displayValue = computed(() => {
  if (props.multiple) {
    return selectedValues.value
      .map((value) => {
        const option = props.options.find((o) => o.value === value)
        return option?.label || value.toString()
      })
      .join(', ')
  }

  const option = props.options.find((o) => o.value === selectedValues.value[0])
  return option?.label || ''
})

// 处理选择
function handleSelect(value: string) {
  if (props.multiple) {
    const numValue = Number(value)
    const selectedOption = props.options.find((o) => o.value === value || o.value === numValue)
    if (selectedOption) {
      const index = selectedValues.value.indexOf(selectedOption.value)
      if (index === -1) {
        if (props.maxItems && selectedValues.value.length >= props.maxItems) return
        selectedValues.value = [...selectedValues.value, selectedOption.value]
      } else {
        selectedValues.value = selectedValues.value.filter((v) => v !== selectedOption.value)
      }
    }
  } else {
    const numValue = Number(value)
    const selectedOption = props.options.find((o) => o.value === value || o.value === numValue)
    if (selectedOption) {
      selectedValues.value = [selectedOption.value]
    }
  }
  emitChange()
}

// 处理移除
function handleRemove(value: string | number) {
  selectedValues.value = selectedValues.value.filter((v) => v !== value)
  emitChange()
}

// 处理清除
function handleClear() {
  selectedValues.value = []
  emitChange()
}

// 触发变化事件
function emitChange() {
  const value = props.multiple ? selectedValues.value : selectedValues.value[0]
  props.onUpdate?.(value)
  props.onChange?.(value)
}

// 监听 modelValue 变化
watch(
  () => props.modelValue,
  (newValue) => {
    if (props.multiple && Array.isArray(newValue)) {
      selectedValues.value = newValue
    } else if (newValue !== undefined) {
      selectedValues.value = [newValue]
    } else {
      selectedValues.value = []
    }
  }
)
</script>

<template>
  <div class="relative">
    <Select
      :value="selectedValues[0]?.toString()"
      :disabled="disabled"
      @update:value="handleSelect"
    >
      <SelectTrigger class="w-full">
        <SelectValue :placeholder="placeholder">
          <span v-if="displayValue" class="truncate">{{ displayValue }}</span>
          <span v-else class="text-muted-foreground">{{ placeholder }}</span>
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <template v-for="(options, group) in groupedOptions" :key="group">
          <SelectGroup>
            <SelectLabel v-if="group">{{ group }}</SelectLabel>
            <SelectItem
              v-for="option in options"
              :key="option.value"
              :value="option.value.toString()"
              :disabled="option.disabled"
            >
              <div class="flex items-center gap-2">
                <span v-if="showIcon && option.icon">{{ option.icon }}</span>
                <div class="flex flex-col">
                  <span>{{ option.label }}</span>
                  <span
                    v-if="showDescription && option.description"
                    class="text-sm text-muted-foreground"
                  >
                    {{ option.description }}
                  </span>
                </div>
              </div>
            </SelectItem>
          </SelectGroup>
        </template>
      </SelectContent>
    </Select>

    <!-- 多选标签 -->
    <div
      v-if="multiple && selectedValues.length > 0"
      class="flex flex-wrap gap-1 mt-2"
    >
      <Badge
        v-for="value in selectedValues"
        :key="value"
        variant="secondary"
        class="flex items-center gap-1"
      >
        <span>{{ options.find((o) => o.value === value)?.label || value }}</span>
        <Button
          v-if="!disabled"
          variant="ghost"
          size="sm"
          class="h-3 w-3 p-0 hover:bg-transparent"
          @click="handleRemove(value)"
        >
          <X class="h-2 w-2" />
        </Button>
      </Badge>
    </div>
  </div>
</template>
