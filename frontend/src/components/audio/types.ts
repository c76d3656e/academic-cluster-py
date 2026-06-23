export interface AudioProps {
  src: string
  title?: string
  artist?: string
  cover?: string
  autoplay?: boolean
  loop?: boolean
  muted?: boolean
  controls?: boolean
  preload?: 'auto' | 'metadata' | 'none'
  showVisualizer?: boolean
  onPlay?: () => void
  onPause?: () => void
  onEnded?: () => void
  onError?: (error: Event) => void
}
