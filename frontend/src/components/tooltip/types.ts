export interface TooltipProps {
  content: string
  side?: 'top' | 'right' | 'bottom' | 'left'
  align?: 'start' | 'center' | 'end'
  delay?: number
  disabled?: boolean
  variant?: 'default' | 'info' | 'success' | 'warning' | 'error'
}
