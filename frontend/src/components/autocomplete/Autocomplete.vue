<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from '@/i18n'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Check, ChevronsUpDown, X, Loader2 } from 'lucide-vue-next'
import type { AutocompleteProps, AutocompleteOption } from './types'

const props = withDefaults(defineProps<AutocompleteProps>(), {
  modelValue: undefined,
  placeholder: 'Search...',
  disabled: false,
  clearable: true,
  searchable: true,
  multiple: false,
  maxItems: undefined,
  loading: false,
  noResultsText: 'No results found.',
  filterFunction: undefined,
  onUpdate: undefined,
  onChange: undefined,
  onSearch: undefined,
})

const { t } = useI18n()

const isOpen = ref(false)
const searchQuery = ref('')
const selectedValues = ref<(string | number)[]>([])

// 初始化选中的值
if (props.multiple && Array.isArray(props.modelValue)) {
  selectedValues.value = props.modelValue
} else if (props.modelValue !== undefined) {
  selectedValues.value = [props.modelValue]
}

// 计算过滤后的选项
const filteredOptions = computed(() => {
  if (!searchQuery.value.trim()) {
    return props.options
  }

  if (props.filterFunction) {
    return props.options.filter((option) => props.filterFunction!(option, searchQuery.value))
  }

  const query = searchQuery.value.toLowerCase()
  return props.options.filter(
    (option) =>
      option.label.toLowerCase().includes(query) ||
      option.value.toString().toLowerCase().includes(query)
  )
})

// 计算分组选项
const groupedOptions = computed(() => {
  const groups: Record<string, AutocompleteOption[]> = {}

  for (const option of filteredOptions.value) {
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
function handleSelect(value: string | number) {
  if (props.multiple) {
    const index = selectedValues.value.indexOf(value)
    if (index === -1) {
      if (props.maxItems && selectedValues.value.length >= props.maxItems) return
      selectedValues.value = [...selectedValues.value, value]
    } else {
      selectedValues.value = selectedValues.value.filter((v) => v !== value)
    }
  } else {
    selectedValues.value = [value]
    isOpen.value = false
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

// 处理搜索
function handleSearch(query: string) {
  searchQuery.value = query
  props.onSearch?.(query)
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
  <Popover v-model:open="isOpen">
    <PopoverTrigger as-child>
      <Button
        variant="outline"
        role="combobox"
        :aria-expanded="isOpen"
        class="w-full justify-between"
        :disabled="disabled"
      >
        <span class="truncate">
          {{ displayValue || placeholder }}
        </span>
        <div class="flex items-center gap-1">
          <Loader2 v-if="loading" class="h-4 w-4 animate-spin" />
          <X
            v-if="clearable && selectedValues.length > 0"
            class="h-4 w-4 hover:text-destructive"
            @click.stop="handleClear"
          />
          <ChevronsUpDown class="h-4 w-4 shrink-0 opacity-50" />
        </div>
      </Button>
    </PopoverTrigger>
    <PopoverContent class="w-full p-0" align="start">
      <Command>
        <CommandInput
          v-if="searchable"
          :placeholder="placeholder"
          :model-value="searchQuery"
          @update:model-value="handleSearch"
        />
        <CommandList>
          <CommandEmpty>{{ noResultsText }}</CommandEmpty>
          <template v-for="(options, group) in groupedOptions" :key="group">
            <CommandGroup v-if="group" :heading="group">
              <CommandItem
                v-for="option in options"
                :key="option.value"
                :value="option.value.toString()"
                :disabled="option.disabled"
                @select="handleSelect(option.value)"
              >
                <div class="flex items-center gap-2">
                  <Check
                    v-if="selectedValues.includes(option.value)"
                    class="h-4 w-4"
                  />
                  <span>{{ option.label }}</span>
                  <span
                    v-if="option.description"
                    class="text-sm text-muted-foreground"
                  >
                    {{ option.description }}
                  </span>
                </div>
              </CommandItem>
            </CommandGroup>
          </template>
        </CommandList>
      </Command>
    </PopoverContent>
  </Popover>
</template>
