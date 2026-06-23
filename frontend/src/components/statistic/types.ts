export interface StatisticProps {
  title: string
  value: number | string
  previousValue?: number | string
  change?: number
  changeLabel?: string
  prefix?: string
  suffix?: string
  icon?: string
  trend?: 'up' | 'down' | 'stable'
  format?: 'number' | 'currency' | 'percentage'
  precision?: number
  loading?: boolean
  description?: string
  action?: {
    label: string
    onClick: () => void
  }
  size?: 'sm' | 'md' | 'lg'
  variant?: 'default' | 'bordered' | 'card'
}
