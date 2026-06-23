export interface StatCardProps {
  title: string
  value: number | string
  previousValue?: number | string
  change?: number
  changeLabel?: string
  icon?: string
  trend?: 'up' | 'down' | 'stable'
  format?: 'number' | 'currency' | 'percentage'
  loading?: boolean
  description?: string
  action?: {
    label: string
    onClick: () => void
  }
  size?: 'sm' | 'md' | 'lg'
}
