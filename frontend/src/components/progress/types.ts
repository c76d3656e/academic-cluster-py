export interface ProgressProps {
  value: number
  max?: number
  size?: 'sm' | 'md' | 'lg'
  variant?: 'default' | 'success' | 'warning' | 'error'
  showValue?: boolean
  showLabel?: boolean
  label?: string
  indeterminate?: boolean
  striped?: boolean
  animated?: boolean
  format?: (value: number, max: number) => string
}
