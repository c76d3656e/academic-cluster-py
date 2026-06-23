export interface Column<T> {
  id: string
  header: string
  accessorKey?: keyof T
  accessorFn?: (row: T) => unknown
  cell?: (row: T) => unknown
  enableSorting?: boolean
  enableFiltering?: boolean
  size?: number
  minSize?: number
  maxSize?: number
}

export interface SortState {
  id: string
  desc: boolean
}

export interface FilterState {
  id: string
  value: string
}

export interface PaginationState {
  pageIndex: number
  pageSize: number
}

export interface DataTableProps<T> {
  data: T[]
  columns: Column<T>[]
  isLoading?: boolean
  totalCount?: number
  pagination?: PaginationState
  sorting?: SortState[]
  filters?: FilterState[]
  search?: string
  onPaginationChange?: (pagination: PaginationState) => void
  onSortingChange?: (sorting: SortState[]) => void
  onFiltersChange?: (filters: FilterState[]) => void
  onSearchChange?: (search: string) => void
  onRowClick?: (row: T) => void
  selectable?: boolean
  selectedRows?: T[]
  onSelectionChange?: (rows: T[]) => void
}
