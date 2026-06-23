export interface CodeBlockProps {
  code: string
  language?: string
  title?: string
  showLineNumbers?: boolean
  showCopy?: boolean
  showHeader?: boolean
  maxHeight?: string
  wrap?: boolean
  highlightLines?: number[]
  onCopy?: (code: string) => void
}
