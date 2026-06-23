export interface SkeletonProps {
  width?: string | number
  height?: string | number
  variant?: 'text' | 'circular' | 'rectangular' | 'rounded'
  animation?: 'pulse' | 'wave' | 'none'
  lines?: number
  className?: string
}

export interface SkeletonGroupProps {
  count: number
  gap?: string | number
  direction?: 'row' | 'column'
  className?: string
}
