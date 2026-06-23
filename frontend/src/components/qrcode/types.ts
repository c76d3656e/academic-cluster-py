export interface QRCodeProps {
  value: string
  size?: number
  level?: 'L' | 'M' | 'Q' | 'H'
  bgColor?: string
  fgColor?: string
  style?: 'square' | 'rounded' | 'dots'
  logo?: string
  logoSize?: number
  showDownload?: boolean
  showCopy?: boolean
  onDownload?: () => void
  onCopy?: () => void
}
