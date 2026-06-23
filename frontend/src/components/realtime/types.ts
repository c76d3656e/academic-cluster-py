export interface RealtimeData {
  id: string
  timestamp: Date
  type: string
  content: string
  metadata?: Record<string, unknown>
}

export interface RealtimeMetric {
  label: string
  value: number
  previousValue?: number
  unit?: string
  trend?: 'up' | 'down' | 'stable'
}

export interface RealtimeFeedItem {
  id: string
  timestamp: Date
  type: 'info' | 'success' | 'warning' | 'error'
  title: string
  description?: string
}

export interface RealtimeProps {
  metrics: RealtimeMetric[]
  feed: RealtimeFeedItem[]
  isLive?: boolean
  refreshInterval?: number
  onToggleLive?: (live: boolean) => void
  onRefresh?: () => void
}
