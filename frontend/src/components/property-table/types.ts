export interface PropertyItem {
  key: string
  label: string
  value: unknown
  type?: 'text' | 'number' | 'boolean' | 'date' | 'array' | 'object' | 'link' | 'badge'
  copyable?: boolean
  editable?: boolean
  hidden?: boolean
  formatter?: (value: unknown) => string
  link?: string
  badgeVariant?: 'default' | 'secondary' | 'destructive' | 'outline'
}

export interface PropertyTableProps {
  items: PropertyItem[]
  title?: string
  variant?: 'default' | 'bordered' | 'compact'
  size?: 'sm' | 'md' | 'lg'
  showCopy?: boolean
  showEdit?: boolean
  editable?: boolean
  onCopy?: (value: string) => void
  onEdit?: (key: string, value: unknown) => void
}
