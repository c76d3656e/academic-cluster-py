export interface PaginationProps {
  currentPage: number
  totalPages: number
  onPageChange: (page: number) => void
  showFirstLast?: boolean
  showPrevNext?: boolean
  showPageNumbers?: boolean
  maxVisiblePages?: number
  disabled?: boolean
  size?: 'sm' | 'md' | 'lg'
}

export interface PaginationState {
  currentPage: number
  totalPages: number
  pages: number[]
  hasPrevious: boolean
  hasNext: boolean
  hasFirst: boolean
  hasLast: boolean
}
