<script setup lang="ts">
import { ref, computed, watch, defineComponent, h } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Check, ChevronsUpDown, X, ChevronRight, ChevronDown } from 'lucide-vue-next'
import type { TreeSelectProps, TreeSelectNode } from './types'

const props = withDefaults(defineProps<TreeSelectProps>(), {
  modelValue: undefined,
  placeholder: 'Select...',
  disabled: false,
  clearable: true,
  searchable: false,
  multiple: false,
  showPath: false,
  expandAll: false,
  defaultExpandKeys: () => [],
  onUpdate: undefined,
  onChange: undefined,
  onSearch: undefined,
})

const { t } = useI18n()

const isOpen = ref(false)
const searchQuery = ref('')
const selectedValues = ref<(string | number)[]>([])
const expandedKeys = ref<Set<string | number>>(new Set(props.defaultExpandKeys))

// 初始化选中的值
if (props.multiple && Array.isArray(props.modelValue)) {
  selectedValues.value = props.modelValue
} else if (props.modelValue !== undefined && !Array.isArray(props.modelValue)) {
  selectedValues.value = [props.modelValue]
}

// 计算显示的值
const displayValue = computed(() => {
  if (selectedValues.value.length === 0) return ''

  if (props.multiple) {
    return selectedValues.value
      .map((value) => {
        const node = findNode(props.nodes, value)
        return node?.label || value.toString()
      })
      .join(', ')
  }

  const node = findNode(props.nodes, selectedValues.value[0])
  return node?.label || ''
})

// 查找节点
function findNode(nodes: TreeSelectNode[], value: string | number): TreeSelectNode | null {
  for (const node of nodes) {
    if (node.id === value) return node
    if (node.children) {
      const found = findNode(node.children, value)
      if (found) return found
    }
  }
  return null
}

// 计算过滤后的节点
const filteredNodes = computed(() => {
  if (!searchQuery.value.trim()) return props.nodes

  const query = searchQuery.value.toLowerCase()
  const results: TreeSelectNode[] = []

  function search(nodes: TreeSelectNode[]) {
    for (const node of nodes) {
      if (node.label.toLowerCase().includes(query)) {
        results.push(node)
      }
      if (node.children) {
        search(node.children)
      }
    }
  }

  search(props.nodes)
  return results
})

// 处理节点展开/折叠
function toggleExpand(nodeId: string | number) {
  if (expandedKeys.value.has(nodeId)) {
    expandedKeys.value.delete(nodeId)
  } else {
    expandedKeys.value.add(nodeId)
  }
}

// 处理节点选择
function handleNodeSelect(node: TreeSelectNode) {
  if (node.disabled) return

  if (props.multiple) {
    const index = selectedValues.value.indexOf(node.id)
    if (index === -1) {
      selectedValues.value = [...selectedValues.value, node.id]
    } else {
      selectedValues.value = selectedValues.value.filter((v) => v !== node.id)
    }
  } else {
    selectedValues.value = [node.id]
    isOpen.value = false
  }
  emitChange()
}

// 处理清除
function handleClear() {
  selectedValues.value = []
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
    } else if (newValue !== undefined && !Array.isArray(newValue)) {
      selectedValues.value = [newValue]
    } else {
      selectedValues.value = []
    }
  }
)

// 树节点组件
const TreeNode = defineComponent({
  name: 'TreeNode',
  props: {
    node: {
      type: Object as () => TreeSelectNode,
      required: true,
    },
    level: {
      type: Number,
      required: true,
    },
    selectedValues: {
      type: Array as () => (string | number)[],
      required: true,
    },
    expandedKeys: {
      type: Object as () => Set<string | number>,
      required: true,
    },
    multiple: {
      type: Boolean,
      required: true,
    },
    showPath: {
      type: Boolean,
      required: true,
    },
  },
  emits: ['select', 'toggle-expand'],
  setup(props, { emit }) {
    const hasChildren = computed(() => {
      return props.node.children && props.node.children.length > 0
    })

    const isExpanded = computed(() => {
      return props.expandedKeys.has(props.node.id)
    })

    const isSelected = computed(() => {
      return props.selectedValues.includes(props.node.id)
    })

    const handleClick = () => {
      if (hasChildren.value) {
        emit('toggle-expand', props.node.id)
      } else {
        emit('select', props.node)
      }
    }

    const handleChildSelect = (node: TreeSelectNode) => {
      emit('select', node)
    }

    const handleChildToggleExpand = (nodeId: string | number) => {
      emit('toggle-expand', nodeId)
    }

    return () => {
      const children: any[] = []

      // 节点行
      children.push(
        h('div', {
          class: [
            'flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer hover:bg-accent',
            {
              'bg-accent': isSelected.value,
              'text-muted-foreground': props.node.disabled,
            },
          ],
          style: { paddingLeft: `${props.level * 16 + 8}px` },
          onClick: handleClick,
        }, [
          hasChildren.value && isExpanded.value
            ? h(ChevronDown, { class: 'h-4 w-4 text-muted-foreground' })
            : hasChildren.value
              ? h(ChevronRight, { class: 'h-4 w-4 text-muted-foreground' })
              : h('div', { class: 'w-4' }),
          h('span', { class: 'flex-1' }, props.node.label),
          isSelected.value ? h(Check, { class: 'h-4 w-4' }) : null,
        ])
      )

      // 子节点
      if (hasChildren.value && isExpanded.value) {
        children.push(
          h('div', {}, props.node.children?.map((child) =>
            h(TreeNode, {
              key: child.id,
              node: child,
              level: props.level + 1,
              selectedValues: props.selectedValues,
              expandedKeys: props.expandedKeys,
              multiple: props.multiple,
              showPath: props.showPath,
              onSelect: handleChildSelect,
              onToggleExpand: handleChildToggleExpand,
            })
          ))
        )
      }

      return h('div', {}, children)
    }
  },
})
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
            v-if="clearable && selectedValues.length > 0"
            class="h-4 w-4 hover:text-destructive"
            @click.stop="handleClear"
          />
          <ChevronsUpDown class="h-4 w-4 shrink-0 opacity-50" />
        </div>
      </Button>
    </PopoverTrigger>
    <PopoverContent class="w-80 p-0" align="start">
      <div class="p-2 border-b">
        <Input
          v-if="searchable"
          :placeholder="t('treeSelect.search')"
          :model-value="searchQuery"
          @update:model-value="handleSearch"
        />
      </div>
      <div class="max-h-64 overflow-auto p-2">
        <TreeNode
          v-for="node in (searchQuery ? filteredNodes : nodes)"
          :key="node.id"
          :node="node"
          :level="0"
          :selected-values="selectedValues"
          :expanded-keys="expandedKeys"
          :multiple="multiple"
          :show-path="showPath"
          @select="handleNodeSelect"
          @toggle-expand="toggleExpand"
        />
      </div>
    </PopoverContent>
  </Popover>
</template>
