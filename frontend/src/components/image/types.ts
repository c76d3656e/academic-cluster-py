export interface ImageProps {
  src: string
  alt: string
  width?: number | string
  height?: number | string
  objectFit?: 'contain' | 'cover' | 'fill' | 'none' | 'scale-down'
  loading?: 'lazy' | 'eager'
  placeholder?: string
  fallback?: string
  rounded?: boolean | 'sm' | 'md' | 'lg' | 'full'
  bordered?: boolean
  zoomable?: boolean
  preview?: boolean
  onLoad?: () => void
  onError?: (error: Event) => void
}
