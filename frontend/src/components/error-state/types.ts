export interface ErrorStateProps {
  title?: string
  description?: string
  error?: Error | string
  retry?: () => void
  retryLabel?: string
  backLabel?: string
  backTo?: string
  size?: 'sm' | 'md' | 'lg'
  showDetails?: boolean
}
