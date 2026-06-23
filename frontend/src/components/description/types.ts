export interface DescriptionItem {
  label: string
  value: unknown
  icon?: string
  copyable?: boolean
  hidden?: boolean
  formatter?: (value: unknown) => string
  span?: number
}

export interface DescriptionProps {
  items: DescriptionItem[]
  title?: string
  variant?: 'default' | 'bordered' | 'striped'
  size?: 'sm' | 'md' | 'lg'
  columns?: 1 | 2 | 3
  labelWidth?: string
  showCopy?: boolean
  showIcon?: boolean
  onCopy?: (value: string) => void
}
