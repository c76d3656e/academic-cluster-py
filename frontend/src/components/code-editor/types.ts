export interface CodeEditorProps {
  modelValue?: string
  language?: string
  theme?: 'light' | 'dark'
  placeholder?: string
  minHeight?: string | number
  maxHeight?: string | number
  readonly?: boolean
  disabled?: boolean
  showLineNumbers?: boolean
  showMinimap?: boolean
  showToolbar?: boolean
  showCopy?: boolean
  showFormat?: boolean
  tabSize?: number
  wordWrap?: 'on' | 'off' | 'wordWrapColumn' | 'bounded'
  fontSize?: number
  fontFamily?: string
  onUpdate?: (value: string) => void
  onFocus?: () => void
  onBlur?: () => void
  onCopy?: (value: string) => void
  onFormat?: (value: string) => string
}
