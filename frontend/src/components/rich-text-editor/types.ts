export interface RichTextEditorProps {
  modelValue?: string
  placeholder?: string
  minHeight?: string | number
  maxHeight?: string | number
  readonly?: boolean
  disabled?: boolean
  showToolbar?: boolean
  showWordCount?: boolean
  showCharCount?: boolean
  maxLength?: number
  toolbar?: string[]
  format?: 'html' | 'markdown'
  onUpdate?: (value: string) => void
  onFocus?: () => void
  onBlur?: () => void
  onPaste?: (event: ClipboardEvent) => void
}
