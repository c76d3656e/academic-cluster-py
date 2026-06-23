export interface VideoProps {
  src: string
  poster?: string
  width?: number | string
  height?: number | string
  autoplay?: boolean
  loop?: boolean
  muted?: boolean
  controls?: boolean
  preload?: 'auto' | 'metadata' | 'none'
  objectFit?: 'contain' | 'cover' | 'fill' | 'none' | 'scale-down'
  rounded?: boolean | 'sm' | 'md' | 'lg' | 'full'
  bordered?: boolean
  onPlay?: () => void
  onPause?: () => void
  onEnded?: () => void
  onError?: (error: Event) => void
}
