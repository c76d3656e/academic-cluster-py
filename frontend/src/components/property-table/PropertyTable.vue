<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from '@/i18n'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Copy, Check, Pencil, ExternalLink } from 'lucide-vue-next'
import type { PropertyTableProps, PropertyItem } from './types'

const props = withDefaults(defineProps<PropertyTableProps>(), {
  title: undefined,
  variant: 'default',
  size: 'md',
  showCopy: true,
  showEdit: false,
  editable: false,
  onCopy: undefined,
  onEdit: undefined,
})

const { t } = useI18n()

const copiedKey = ref<string | null>(null)
const editingKey = ref<string | null>(null)
const editingValue = ref<string>('')

// 计算可见项目
const visibleItems = computed(() => {
  return props.items.filter((item) => !item.hidden)
})

// 计算表格样式
const tableClass = computed(() => {
  switch (props.variant) {
    case 'bordered':
      return 'border rounded-lg'
    case 'compact':
      return 'text-sm'
    default:
      return ''
  }
})

// 计算单元格样式
const cellClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'py-2 px-3'
    case 'md':
      return 'py-3 px-4'
    case 'lg':
      return 'py-4 px-5'
    default:
      return 'py-3 px-4'
  }
})

// 格式化值
function formatValue(item: PropertyItem): string {
  if (item.formatter) {
    return item.formatter(item.value)
  }

  if (item.value === null || item.value === undefined) {
    return '-'
  }

  if (typeof item.value === 'boolean') {
    return item.value ? t('common.yes') : t('common.no')
  }

  if (Array.isArray(item.value)) {
    return item.value.join(', ')
  }

  if (typeof item.value === 'object') {
    return JSON.stringify(item.value, null, 2)
  }

  return String(item.value)
}

// 复制值
async function copyValue(value: string, key: string) {
  try {
    await navigator.clipboard.writeText(value)
    copiedKey.value = key
    setTimeout(() => {
      copiedKey.value = null
    }, 2000)
    props.onCopy?.(value)
  } catch (error) {
    console.error('Failed to copy:', error)
  }
}

// 开始编辑
function startEdit(item: PropertyItem) {
  if (!props.editable || !item.editable) return

  editingKey.value = item.key
  editingValue.value = formatValue(item)
}

// 取消编辑
function cancelEdit() {
  editingKey.value = null
  editingValue.value = ''
}

// 保存编辑
function saveEdit(key: string) {
  props.onEdit?.(key, editingValue.value)
  editingKey.value = null
  editingValue.value = ''
}
</script>

<template>
  <div>
    <div v-if="title" class="text-lg font-semibold mb-4">{{ title }}</div>
    <Table :class="tableClass">
      <TableHeader>
        <TableRow>
          <TableHead :class="cellClass" class="w-1/3">{{ t('propertyTable.label') }}</TableHead>
          <TableHead :class="cellClass">{{ t('propertyTable.value') }}</TableHead>
          <TableHead v-if="showCopy || showEdit" :class="cellClass" class="w-20">
            {{ t('propertyTable.actions') }}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow
          v-for="item in visibleItems"
          :key="item.key"
        >
          <TableCell :class="cellClass" class="font-medium">
            <div class="flex items-center gap-2">
              <span>{{ item.label }}</span>
              <Badge v-if="item.type === 'badge'" :variant="item.badgeVariant || 'default'">
                {{ formatValue(item) }}
              </Badge>
            </div>
          </TableCell>
          <TableCell :class="cellClass">
            <!-- 编辑模式 -->
            <div v-if="editingKey === item.key" class="flex items-center gap-2">
              <Input
                v-model="editingValue"
                class="flex-1"
                @keyup="(e: KeyboardEvent) => { if (e.key === 'Enter') saveEdit(item.key); if (e.key === 'Escape') cancelEdit() }"
              />
              <Button size="sm" @click="saveEdit(item.key)">
                {{ t('common.save') }}
              </Button>
              <Button variant="outline" size="sm" @click="cancelEdit">
                {{ t('common.cancel') }}
              </Button>
            </div>

            <!-- 显示模式 -->
            <div v-else class="flex items-center gap-2">
              <span v-if="item.type === 'link' && item.link">
                <a
                  :href="item.link"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-primary hover:underline flex items-center gap-1"
                >
                  {{ formatValue(item) }}
                  <ExternalLink class="h-3 w-3" />
                </a>
              </span>
              <span v-else-if="item.type === 'badge'">
                <!-- Badge 已在标签列显示 -->
              </span>
              <span v-else class="break-words">{{ formatValue(item) }}</span>
            </div>
          </TableCell>
          <TableCell v-if="showCopy || showEdit" :class="cellClass">
            <div class="flex items-center gap-1">
              <Button
                v-if="showCopy && item.copyable"
                variant="ghost"
                size="sm"
                class="h-8 w-8 p-0"
                @click="copyValue(formatValue(item), item.key)"
              >
                <Check v-if="copiedKey === item.key" class="h-4 w-4 text-green-500" />
                <Copy v-else class="h-4 w-4" />
              </Button>
              <Button
                v-if="showEdit && item.editable && editingKey !== item.key"
                variant="ghost"
                size="sm"
                class="h-8 w-8 p-0"
                @click="startEdit(item)"
              >
                <Pencil class="h-4 w-4" />
              </Button>
            </div>
          </TableCell>
        </TableRow>
      </TableBody>
    </Table>
  </div>
</template>
