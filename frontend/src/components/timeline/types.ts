export interface TimelineItem {
  id: string
  title: string
  description?: string
  timestamp: Date | string
  icon?: string
  color?: string
  status?: 'success' | 'error' | 'warning' | 'info' | 'default'
  user?: {
    name: string
    avatar?: string
  }
  metadata?: Record<string, unknown>
}

export interface TimelineProps {
  items: TimelineItem[]
  variant?: 'default' | 'compact' | 'detailed'
  showConnector?: boolean
  showTimestamp?: boolean
  showUser?: boolean
  reverse?: boolean
}
