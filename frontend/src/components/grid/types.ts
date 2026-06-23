export interface GridItem {
  id: string | number
  title: string
  description?: string
  image?: string
  icon?: string
  badge?: string | number
  disabled?: boolean
  metadata?: Record<string, unknown>
}

export interface GridProps {
  items: GridItem[]
  columns?: 1 | 2 | 3 | 4 | 5 | 6
  gap?: 'sm' | 'md' | 'lg'
  variant?: 'default' | 'bordered' | 'card'
  size?: 'sm' | 'md' | 'lg'
  showImage?: boolean
  showIcon?: boolean
  showBadge?: boolean
  showDescription?: boolean
  selectable?: boolean
  selectedItems?: (string | number)[]
  onItemClick?: (item: GridItem) => void
  onSelectionChange?: (items: (string | number)[]) => void
}
