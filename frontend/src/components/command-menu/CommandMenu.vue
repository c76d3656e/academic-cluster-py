<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from '@/i18n'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import type { CommandMenuProps, CommandMenuItem, CommandMenuGroup } from './types'

const props = withDefaults(defineProps<CommandMenuProps>(), {
  placeholder: 'Search...',
  emptyMessage: 'No results found.',
  onSelect: undefined,
  onSearch: undefined,
  open: undefined,
  onOpenChange: undefined,
})

const { t } = useI18n()

const isOpen = ref(props.open ?? false)
const query = ref('')

// 计算过滤后的分组
const filteredGroups = computed(() => {
  if (!query.value.trim()) {
    return props.groups
  }

  const lowerQuery = query.value.toLowerCase()

  return props.groups
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) =>
          item.label.toLowerCase().includes(lowerQuery) ||
          item.id.toLowerCase().includes(lowerQuery)
      ),
    }))
    .filter((group) => group.items.length > 0)
})

// 处理选择
function handleSelect(item: CommandMenuItem) {
  if (item.disabled) return

  if (item.action) {
    item.action()
  }

  props.onSelect?.(item)
  isOpen.value = false
}

// 处理搜索
function handleSearch(value: string) {
  query.value = value
  props.onSearch?.(value)
}

// 处理打开状态变化
function handleOpenChange(open: boolean) {
  isOpen.value = open
  props.onOpenChange?.(open)
  if (!open) {
    query.value = ''
  }
}

// 键盘快捷键
function handleKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault()
    handleOpenChange(!isOpen.value)
  }
}

// 监听 open 属性变化
watch(
  () => props.open,
  (newOpen) => {
    if (newOpen !== undefined) {
      isOpen.value = newOpen
    }
  }
)

// 注册全局键盘事件
onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <CommandDialog :open="isOpen" @update:open="handleOpenChange">
    <CommandInput
      :placeholder="placeholder"
      :model-value="query"
      @update:model-value="handleSearch"
    />
    <CommandList>
      <CommandEmpty>{{ emptyMessage }}</CommandEmpty>

      <template v-for="group in filteredGroups" :key="group.id">
        <CommandGroup :heading="group.label">
          <CommandItem
            v-for="item in group.items"
            :key="item.id"
            :value="item.id"
            :disabled="item.disabled"
            @select="handleSelect(item)"
          >
            <div class="flex items-center gap-2">
              <span v-if="item.icon">{{ item.icon }}</span>
              <span>{{ item.label }}</span>
              <span
                v-if="item.shortcut"
                class="ml-auto text-xs text-muted-foreground"
              >
                {{ item.shortcut }}
              </span>
            </div>
          </CommandItem>
        </CommandGroup>
        <CommandSeparator />
      </template>
    </CommandList>
  </CommandDialog>
</template>
