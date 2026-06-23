export interface AdvancedTableColumn<T> {
  id: string
  header: string
  accessorKey?: keyof T
  accessorFn?: (row: T) => unknown
  cell?: (row: T) => unknown
  enableSorting?: boolean
  enableFiltering?: boolean
  enableResizing?: boolean
  size?: number
  minSize?: number
  maxSize?: number
  align?: 'left' | 'center' | 'right'
  fixed?: 'left' | 'right'
  visible?: boolean
}

export interface AdvancedTableSort {
  id: string
  desc: boolean
}

export interface AdvancedTableFilter {
  id: string
  value: string
}

export interface AdvancedTablePagination {
  pageIndex: number
  pageSize: number
}

export interface AdvancedTableProps<T> {
  data: T[]
  columns: AdvancedTableColumn<T>[]
  isLoading?: boolean
  totalCount?: number
  pagination?: AdvancedTablePagination
  sorting?: AdvancedTableSort[]
  filters?: AdvancedTableFilter[]
  search?: string
  showPagination?: boolean
  showSearch?: boolean
  showFilters?: boolean
  showColumnVisibility?: boolean
  showDensity?: boolean
  showExport?: boolean
  showRefresh?: boolean
  selectable?: boolean
  selectedRows?: T[]
  onPaginationChange?: (pagination: AdvancedTablePagination) => void
  onSortingChange?: (sorting: AdvancedTableSort[]) => void
  onFiltersChange?: (filters: AdvancedTableFilter[]) => void
  onSearchChange?: (search: string) => void
  onRowClick?: (row: T) => void
  onSelectionChange?: (rows: T[]) => void
  onRefresh?: () => void
  onExport?: (format: 'csv' | 'excel' | 'pdf') => void
}
