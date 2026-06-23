export interface DescriptionItem {
  label: string
  value: unknown
  icon?: string
  copyable?: boolean
  hidden?: boolean
  formatter?: (value: unknown) => string
}

export interface DescriptionListProps {
  items: DescriptionItem[]
  variant?: 'default' | 'bordered' | 'striped'
  size?: 'sm' | 'md' | 'lg'
  columns?: 1 | 2 | 3
  labelWidth?: string
  showCopy?: boolean
  onCopy?: (value: string) => void
}
