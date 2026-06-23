<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Check, ChevronsUpDown, X, Loader2 } from 'lucide-vue-next'
import type { ComboboxProps, ComboboxOption } from './types'

const props = withDefaults(defineProps<ComboboxProps>(), {
  modelValue: undefined,
  placeholder: 'Select option...',
  disabled: false,
  clearable: true,
  searchable: true,
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
const selectedValue = ref(props.modelValue)

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
  const groups: Record<string, ComboboxOption[]> = {}

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
  if (selectedValue.value === undefined) return ''
  const option = props.options.find((o) => o.value === selectedValue.value)
  return option?.label || selectedValue.value.toString()
})

// 处理选择
function handleSelect(value: string) {
  const numValue = Number(value)
  const selectedOption = props.options.find((o) => o.value === value || o.value === numValue)
  if (selectedOption) {
    selectedValue.value = selectedOption.value
  } else {
    selectedValue.value = value
  }
  isOpen.value = false
  emitChange()
}

// 处理清除
function handleClear() {
  selectedValue.value = undefined
  emitChange()
}

// 处理搜索
function handleSearch(query: string) {
  searchQuery.value = query
  props.onSearch?.(query)
}

// 触发变化事件
function emitChange() {
  if (selectedValue.value !== undefined) {
    props.onUpdate?.(selectedValue.value)
    props.onChange?.(selectedValue.value)
  }
}

// 监听 modelValue 变化
watch(
  () => props.modelValue,
  (newValue) => {
    selectedValue.value = newValue
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
            v-if="clearable && selectedValue !== undefined"
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
                @select="handleSelect(option.value.toString())"
              >
                <div class="flex items-center gap-2">
                  <Check
                    v-if="selectedValue === option.value"
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
