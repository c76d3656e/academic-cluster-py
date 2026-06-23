<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Check, ChevronsUpDown, X, ChevronRight } from 'lucide-vue-next'
import type { CascaderProps, CascaderOption } from './types'

const props = withDefaults(defineProps<CascaderProps>(), {
  modelValue: () => [],
  placeholder: 'Select...',
  disabled: false,
  clearable: true,
  searchable: false,
  changeOnSelect: false,
  showPath: true,
  expandTrigger: 'click',
  onUpdate: undefined,
  onChange: undefined,
  onSearch: undefined,
})

const { t } = useI18n()

const isOpen = ref(false)
const searchQuery = ref('')
const selectedPath = ref<(string | number)[]>(props.modelValue)
const activePath = ref<(string | number)[]>([])

// 计算显示的值
const displayValue = computed(() => {
  if (selectedPath.value.length === 0) return ''

  const labels: string[] = []
  let currentOptions = props.options

  for (const value of selectedPath.value) {
    const option = currentOptions.find((o) => o.value === value)
    if (option) {
      labels.push(option.label)
      currentOptions = option.children || []
    }
  }

  return labels.join(' / ')
})

// 计算当前级别的选项
const currentLevelOptions = computed(() => {
  let currentOptions = props.options

  for (const value of activePath.value) {
    const option = currentOptions.find((o) => o.value === value)
    if (option && option.children) {
      currentOptions = option.children
    }
  }

  return currentOptions
})

// 计算过滤后的选项（搜索模式）
const filteredOptions = computed(() => {
  if (!searchQuery.value.trim()) return props.options

  const query = searchQuery.value.toLowerCase()
  const results: CascaderOption[] = []

  function search(options: CascaderOption[], path: CascaderOption[] = []) {
    for (const option of options) {
      const currentPath = [...path, option]
      if (option.label.toLowerCase().includes(query)) {
        results.push(option)
      }
      if (option.children) {
        search(option.children, currentPath)
      }
    }
  }

  search(props.options)
  return results
})

// 处理选项点击
function handleOptionClick(option: CascaderOption) {
  if (option.disabled) return

  if (option.children && option.children.length > 0) {
    // 展开子菜单
    const index = activePath.value.indexOf(option.value)
    if (index === -1) {
      activePath.value = [...activePath.value, option.value]
    } else {
      activePath.value = activePath.value.slice(0, index + 1)
    }

    if (props.changeOnSelect) {
      selectedPath.value = [...activePath.value]
      emitChange()
    }
  } else {
    // 选择叶子节点
    selectedPath.value = [...activePath.value, option.value]
    isOpen.value = false
    emitChange()
  }
}

// 处理鼠标悬停
function handleOptionHover(option: CascaderOption) {
  if (props.expandTrigger === 'hover' && option.children && option.children.length > 0) {
    const index = activePath.value.indexOf(option.value)
    if (index === -1) {
      activePath.value = [...activePath.value, option.value]
    }
  }
}

// 处理清除
function handleClear() {
  selectedPath.value = []
  activePath.value = []
  emitChange()
}

// 处理搜索
function handleSearch(query: string | number) {
  const queryString = String(query)
  searchQuery.value = queryString
  props.onSearch?.(queryString)
}

// 触发变化事件
function emitChange() {
  props.onUpdate?.(selectedPath.value)
  props.onChange?.(selectedPath.value)
}

// 监听 modelValue 变化
watch(
  () => props.modelValue,
  (newValue) => {
    selectedPath.value = newValue
    activePath.value = newValue.slice(0, -1)
  }
)

// 辅助函数：获取子选项
function getChildren(value: string | number, index: number): CascaderOption[] {
  let currentOptions = props.options

  for (let i = 0; i <= index; i++) {
    const pathValue = activePath.value[i]
    const option = currentOptions.find((o) => o.value === pathValue)
    if (option && option.children) {
      currentOptions = option.children
    } else {
      return []
    }
  }

  return currentOptions
}
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
          <X
            v-if="clearable && selectedPath.length > 0"
            class="h-4 w-4 hover:text-destructive"
            @click.stop="handleClear"
          />
          <ChevronsUpDown class="h-4 w-4 shrink-0 opacity-50" />
        </div>
      </Button>
    </PopoverTrigger>
    <PopoverContent class="w-auto p-0" align="start">
      <div class="flex">
        <!-- 搜索框 -->
        <div v-if="searchable" class="p-2 border-b">
          <Input
            :placeholder="t('cascader.search')"
            :model-value="searchQuery"
            @update:model-value="handleSearch"
          />
        </div>

        <!-- 选项面板 -->
        <div class="flex">
          <!-- 当前级别选项 -->
          <div class="w-48 max-h-64 overflow-auto border-r">
            <div
              v-for="option in (searchQuery ? filteredOptions : currentLevelOptions)"
              :key="option.value"
              class="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-accent"
              :class="{
                'bg-accent': selectedPath.includes(option.value),
                'text-muted-foreground': option.disabled,
              }"
              @click="handleOptionClick(option)"
              @mouseenter="handleOptionHover(option)"
            >
              <span>{{ option.label }}</span>
              <ChevronRight
                v-if="option.children && option.children.length > 0"
                class="h-4 w-4 text-muted-foreground"
              />
              <Check
                v-else-if="selectedPath.includes(option.value)"
                class="h-4 w-4"
              />
            </div>
          </div>

          <!-- 子级别选项 -->
          <template v-for="(value, index) in activePath" :key="value">
            <div
              v-if="getChildren(value, index).length > 0"
              class="w-48 max-h-64 overflow-auto border-r"
            >
              <div
                v-for="option in getChildren(value, index)"
                :key="option.value"
                class="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-accent"
                :class="{
                  'bg-accent': selectedPath.includes(option.value),
                  'text-muted-foreground': option.disabled,
                }"
                @click="handleOptionClick(option)"
                @mouseenter="handleOptionHover(option)"
              >
                <span>{{ option.label }}</span>
                <ChevronRight
                  v-if="option.children && option.children.length > 0"
                  class="h-4 w-4 text-muted-foreground"
                />
                <Check
                  v-else-if="selectedPath.includes(option.value)"
                  class="h-4 w-4"
                />
              </div>
            </div>
          </template>
        </div>
      </div>
    </PopoverContent>
  </Popover>
</template>
