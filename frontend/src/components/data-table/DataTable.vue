<script setup lang="ts" generic="T">
import { ref, computed, watch } from 'vue'
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
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Search,
  Loader2,
} from 'lucide-vue-next'
import type { DataTableProps, Column, SortState, PaginationState } from './types'

const props = withDefaults(defineProps<DataTableProps<T>>(), {
  isLoading: false,
  totalCount: 0,
  pagination: () => ({ pageIndex: 0, pageSize: 10 }),
  sorting: () => [],
  filters: () => [],
  search: '',
  onPaginationChange: undefined,
  onSortingChange: undefined,
  onFiltersChange: undefined,
  onSearchChange: undefined,
  onRowClick: undefined,
  selectable: false,
  selectedRows: () => [],
  onSelectionChange: undefined,
})

const { t } = useI18n()

const searchInput = ref(props.search)

// 计算总页数
const totalPages = computed(() => {
  if (!props.totalCount) return 0
  return Math.ceil(props.totalCount / props.pagination.pageSize)
})

// 计算当前页的起始和结束索引
const startIndex = computed(() => {
  return props.pagination.pageIndex * props.pagination.pageSize
})

const endIndex = computed(() => {
  return Math.min(startIndex.value + props.pagination.pageSize, props.totalCount)
})

// 获取列的排序状态
function getSortState(columnId: string): 'asc' | 'desc' | null {
  const sort = props.sorting.find((s) => s.id === columnId)
  if (!sort) return null
  return sort.desc ? 'desc' : 'asc'
}

// 切换排序
function toggleSort(columnId: string) {
  const currentSort = props.sorting.find((s) => s.id === columnId)
  let newSorting: SortState[]

  if (!currentSort) {
    newSorting = [{ id: columnId, desc: false }]
  } else if (!currentSort.desc) {
    newSorting = [{ id: columnId, desc: true }]
  } else {
    newSorting = []
  }

  props.onSortingChange?.(newSorting)
}

// 处理搜索
function handleSearch() {
  props.onSearchChange?.(searchInput.value)
}

// 处理分页
function goToPage(pageIndex: number) {
  props.onPaginationChange?.({
    ...props.pagination,
    pageIndex: Math.max(0, Math.min(pageIndex, totalPages.value - 1)),
  })
}

function goToFirstPage() {
  goToPage(0)
}

function goToPreviousPage() {
  goToPage(props.pagination.pageIndex - 1)
}

function goToNextPage() {
  goToPage(props.pagination.pageIndex + 1)
}

function goToLastPage() {
  goToPage(totalPages.value - 1)
}

// 处理行选择
function isRowSelected(row: T): boolean {
  return props.selectedRows.some((selectedRow) => selectedRow === row)
}

function toggleRowSelection(row: T) {
  if (!props.selectable) return

  const newSelection = isRowSelected(row)
    ? props.selectedRows.filter((selectedRow) => selectedRow !== row)
    : [...props.selectedRows, row]

  props.onSelectionChange?.(newSelection)
}

function selectAllRows() {
  if (!props.selectable) return

  const allSelected = props.data.every((row) => isRowSelected(row))
  if (allSelected) {
    props.onSelectionChange?.([])
  } else {
    props.onSelectionChange?.([...props.data])
  }
}

// 监听搜索输入变化
watch(searchInput, (newValue) => {
  props.onSearchChange?.(newValue)
})
</script>

<template>
  <div class="space-y-4">
    <!-- 搜索栏 -->
    <div v-if="onSearchChange" class="flex items-center gap-2">
      <div class="relative flex-1 max-w-sm">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          v-model="searchInput"
          :placeholder="t('datatable.search')"
          class="pl-10"
          @keyup.enter="handleSearch"
        />
      </div>
      <Button variant="outline" @click="handleSearch">
        {{ t('datatable.search') }}
      </Button>
    </div>

    <!-- 表格 -->
    <div class="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <!-- 选择列 -->
            <TableHead v-if="selectable" class="w-10">
              <input
                type="checkbox"
                :checked="data.length > 0 && data.every((row) => isRowSelected(row))"
                @change="selectAllRows"
              />
            </TableHead>

            <!-- 数据列 -->
            <TableHead
              v-for="column in columns"
              :key="column.id"
              :style="{
                width: column.size ? `${column.size}px` : undefined,
                minWidth: column.minSize ? `${column.minSize}px` : undefined,
                maxWidth: column.maxSize ? `${column.maxSize}px` : undefined,
              }"
            >
              <div class="flex items-center gap-2">
                <span>{{ column.header }}</span>
                <Button
                  v-if="column.enableSorting !== false"
                  variant="ghost"
                  size="sm"
                  class="h-8 w-8 p-0"
                  @click="toggleSort(column.id)"
                >
                  <ArrowUpDown v-if="getSortState(column.id) === null" class="h-4 w-4" />
                  <ArrowUp v-else-if="getSortState(column.id) === 'asc'" class="h-4 w-4" />
                  <ArrowDown v-else class="h-4 w-4" />
                </Button>
              </div>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <!-- 加载状态 -->
          <TableRow v-if="isLoading">
            <TableCell
              :colspan="columns.length + (selectable ? 1 : 0)"
              class="h-24 text-center"
            >
              <div class="flex items-center justify-center gap-2">
                <Loader2 class="h-4 w-4 animate-spin" />
                <span>{{ t('datatable.loading') }}</span>
              </div>
            </TableCell>
          </TableRow>

          <!-- 空状态 -->
          <TableRow v-else-if="data.length === 0">
            <TableCell
              :colspan="columns.length + (selectable ? 1 : 0)"
              class="h-24 text-center"
            >
              {{ t('datatable.noData') }}
            </TableCell>
          </TableRow>

          <!-- 数据行 -->
          <TableRow
            v-else
            v-for="(row, rowIndex) in data"
            :key="rowIndex"
            class="cursor-pointer"
            :class="{ 'bg-muted/50': isRowSelected(row) }"
            @click="onRowClick?.(row)"
          >
            <!-- 选择列 -->
            <TableCell v-if="selectable" class="w-10">
              <input
                type="checkbox"
                :checked="isRowSelected(row)"
                @click.stop="toggleRowSelection(row)"
              />
            </TableCell>

            <!-- 数据列 -->
            <TableCell
              v-for="column in columns"
              :key="column.id"
            >
              <slot :name="`cell-${column.id}`" :row="row" :value="getCellValue(row, column)">
                {{ getCellValue(row, column) }}
              </slot>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>

    <!-- 分页栏 -->
    <div v-if="totalCount > 0" class="flex items-center justify-between">
      <div class="text-sm text-muted-foreground">
        {{ t('datatable.showing', { start: startIndex + 1, end: endIndex, total: totalCount }) }}
      </div>
      <div class="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          :disabled="pagination.pageIndex === 0"
          @click="goToFirstPage"
        >
          <ChevronsLeft class="h-4 w-4" />
        </Button>
        <Button
          variant="outline"
          size="sm"
          :disabled="pagination.pageIndex === 0"
          @click="goToPreviousPage"
        >
          <ChevronLeft class="h-4 w-4" />
        </Button>
        <div class="flex items-center gap-1">
          <span class="text-sm font-medium">{{ pagination.pageIndex + 1 }}</span>
          <span class="text-sm text-muted-foreground">/ {{ totalPages }}</span>
        </div>
        <Button
          variant="outline"
          size="sm"
          :disabled="pagination.pageIndex >= totalPages - 1"
          @click="goToNextPage"
        >
          <ChevronRight class="h-4 w-4" />
        </Button>
        <Button
          variant="outline"
          size="sm"
          :disabled="pagination.pageIndex >= totalPages - 1"
          @click="goToLastPage"
        >
          <ChevronsRight class="h-4 w-4" />
        </Button>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
// 辅助函数：获取单元格值
function getCellValue<T>(row: T, column: Column<T>): unknown {
  if (column.accessorFn) {
    return column.accessorFn(row)
  }
  if (column.accessorKey) {
    return (row as Record<string, unknown>)[column.accessorKey as string]
  }
  return null
}
</script>
