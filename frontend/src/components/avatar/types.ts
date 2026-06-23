export interface AvatarProps {
  src?: string
  alt?: string
  fallback?: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
  shape?: 'circle' | 'square'
  status?: 'online' | 'offline' | 'away' | 'busy'
  border?: boolean
  className?: string
}

export interface AvatarGroupProps {
  avatars: AvatarProps[]
  max?: number
  size?: 'sm' | 'md' | 'lg' | 'xl'
  spacing?: 'tight' | 'normal' | 'loose'
  showCount?: boolean
}
