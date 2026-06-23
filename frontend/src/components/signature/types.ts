export interface SignatureProps {
  width?: number
  height?: number
  lineWidth?: number
  lineColor?: string
  backgroundColor?: string
  penStyle?: 'round' | 'square'
  showClear?: boolean
  showUndo?: boolean
  showSave?: boolean
  showDownload?: boolean
  disabled?: boolean
  placeholder?: string
  onClear?: () => void
  onUndo?: () => void
  onSave?: (data: string) => void
  onDownload?: (data: string) => void
  onChange?: (data: string) => void
}
