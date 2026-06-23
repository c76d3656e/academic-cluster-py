export interface StatusChipProps {
  status: string
  variant?: 'default' | 'secondary' | 'destructive' | 'outline'
  size?: 'sm' | 'md' | 'lg'
  dot?: boolean
  icon?: string
  label?: string
  color?: string
  backgroundColor?: string
}
