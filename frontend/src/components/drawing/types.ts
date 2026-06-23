export interface DrawingTool {
  id: string
  name: string
  icon: string
  type: 'pen' | 'line' | 'rect' | 'circle' | 'arrow' | 'text' | 'eraser'
}

export interface DrawingProps {
  width?: number
  height?: number
  tools?: DrawingTool[]
  defaultTool?: string
  lineWidth?: number
  lineColor?: string
  fillColor?: string
  backgroundColor?: string
  showTools?: boolean
  showColors?: boolean
  showLineWidth?: boolean
  showClear?: boolean
  showUndo?: boolean
  showSave?: boolean
  showDownload?: boolean
  disabled?: boolean
  onClear?: () => void
  onUndo?: () => void
  onSave?: (data: string) => void
  onDownload?: (data: string) => void
  onChange?: (data: string) => void
}
