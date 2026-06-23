export interface JsonEditorProps {
  modelValue?: unknown
  placeholder?: string
  minHeight?: string | number
  maxHeight?: string | number
  readonly?: boolean
  disabled?: boolean
  showToolbar?: boolean
  showCopy?: boolean
  showFormat?: boolean
  showValidate?: boolean
  showTree?: boolean
  indent?: number
  onUpdate?: (value: unknown) => void
  onError?: (error: Error) => void
  onCopy?: (value: string) => void
}
