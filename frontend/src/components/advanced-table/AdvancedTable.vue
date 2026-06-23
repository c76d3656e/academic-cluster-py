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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
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
  Download,
  RefreshCw,
  Settings,
} from 'lucide-vue-next'
import type { AdvancedTableProps, AdvancedTableColumn, AdvancedTableSort, AdvancedTablePagination } from './types'

const props = withDefaults(defineProps<AdvancedTableProps<T>>(), {
  isLoading: false,
  totalCount: 0,
  pagination: () => ({ pageIndex: 0, pageSize: 10 }),
  sorting: () => [],
  filters: () => [],
  search: '',
  showPagination: true,
  showSearch: true,
  showFilters: false,
  showColumnVisibility: false,
  showDensity: false,
  showExport: false,
  showRefresh: false,
  selectable: false,
  selectedRows: () => [],
  onPaginationChange: undefined,
  onSortingChange: undefined,
  onFiltersChange: undefined,
  onSearchChange: undefined,
  onRowClick: undefined,
  onSelectionChange: undefined,
  onRefresh: undefined,
  onExport: undefined,
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
  let newSorting: AdvancedTableSort[]

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

// 处理导出
function handleExport(format: 'csv' | 'excel' | 'pdf') {
  props.onExport?.(format)
}

// 处理刷新
function handleRefresh() {
  props.onRefresh?.()
}

// 监听搜索输入变化
watch(searchInput, (newValue) => {
  props.onSearchChange?.(newValue)
})
</script>

<template>
  <div class="space-y-4">
    <!-- 工具栏 -->
    <div class="flex items-center justify-between gap-4">
      <!-- 搜索 -->
      <div v-if="showSearch" class="flex items-center gap-2 flex-1 max-w-sm">
        <div class="relative flex-1">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            v-model="searchInput"
            :placeholder="t('table.search')"
            class="pl-10"
            @keyup.enter="handleSearch"
          />
        </div>
        <Button variant="outline" @click="handleSearch">
          {{ t('table.search') }}
        </Button>
      </div>

      <!-- 操作按钮 -->
      <div class="flex items-center gap-2">
        <Button
          v-if="showRefresh"
          variant="outline"
          size="sm"
          @click="handleRefresh"
        >
          <RefreshCw class="h-4 w-4" />
        </Button>

        <DropdownMenu v-if="showExport">
          <DropdownMenuTrigger as-child>
            <Button variant="outline" size="sm">
              <Download class="h-4 w-4 mr-2" />
              {{ t('table.export') }}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuItem @click="handleExport('csv')">
              {{ t('table.exportCsv') }}
            </DropdownMenuItem>
            <DropdownMenuItem @click="handleExport('excel')">
              {{ t('table.exportExcel') }}
            </DropdownMenuItem>
            <DropdownMenuItem @click="handleExport('pdf')">
              {{ t('table.exportPdf') }}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu v-if="showColumnVisibility || showDensity">
          <DropdownMenuTrigger as-child>
            <Button variant="outline" size="sm">
              <Settings class="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuItem v-if="showColumnVisibility">
              {{ t('table.columnVisibility') }}
            </DropdownMenuItem>
            <DropdownMenuItem v-if="showDensity">
              {{ t('table.density') }}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
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
              :class="{
                'text-center': column.align === 'center',
                'text-right': column.align === 'right',
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
                <span>{{ t('table.loading') }}</span>
              </div>
            </TableCell>
          </TableRow>

          <!-- 空状态 -->
          <TableRow v-else-if="data.length === 0">
            <TableCell
              :colspan="columns.length + (selectable ? 1 : 0)"
              class="h-24 text-center"
            >
              {{ t('table.noData') }}
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
              :class="{
                'text-center': column.align === 'center',
                'text-right': column.align === 'right',
              }"
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
    <div v-if="showPagination && totalCount > 0" class="flex items-center justify-between">
      <div class="text-sm text-muted-foreground">
        {{ t('table.showing', { start: startIndex + 1, end: endIndex, total: totalCount }) }}
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
function getCellValue<T>(row: T, column: AdvancedTableColumn<T>): unknown {
  if (column.accessorFn) {
    return column.accessorFn(row)
  }
  if (column.accessorKey) {
    return (row as Record<string, unknown>)[column.accessorKey as string]
  }
  return null
}
</script>
