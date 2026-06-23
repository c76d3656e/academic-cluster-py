export interface ChartDataPoint {
  label: string
  value: number
  color?: string
  metadata?: Record<string, unknown>
}

export interface ChartSeries {
  name: string
  data: ChartDataPoint[]
  color?: string
}

export interface ChartProps {
  title?: string
  description?: string
  type: 'bar' | 'line' | 'pie' | 'area' | 'donut'
  data: ChartSeries[]
  height?: number
  showLegend?: boolean
  showGrid?: boolean
  showTooltip?: boolean
  animate?: boolean
  responsive?: boolean
  colors?: string[]
  formatValue?: (value: number) => string
  onPointClick?: (point: ChartDataPoint, series: ChartSeries) => void
}

export interface StatCardProps {
  title: string
  value: number | string
  previousValue?: number | string
  change?: number
  changeLabel?: string
  icon?: string
  trend?: 'up' | 'down' | 'stable'
  format?: 'number' | 'currency' | 'percentage'
  loading?: boolean
}
