export interface ListItem {
  id: string | number
  title: string
  description?: string
  icon?: string
  avatar?: string
  badge?: string | number
  disabled?: boolean
  selected?: boolean
  metadata?: Record<string, unknown>
}

export interface ListProps {
  items: ListItem[]
  variant?: 'default' | 'bordered' | 'striped'
  size?: 'sm' | 'md' | 'lg'
  selectable?: boolean
  selectedItems?: (string | number)[]
  showIcon?: boolean
  showAvatar?: boolean
  showBadge?: boolean
  showDescription?: boolean
  onItemClick?: (item: ListItem) => void
  onSelectionChange?: (items: (string | number)[]) => void
}
