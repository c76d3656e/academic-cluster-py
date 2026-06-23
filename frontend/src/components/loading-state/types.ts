export interface LoadingStateProps {
  title?: string
  description?: string
  size?: 'sm' | 'md' | 'lg'
  variant?: 'spinner' | 'dots' | 'skeleton'
  overlay?: boolean
  fullScreen?: boolean
}
