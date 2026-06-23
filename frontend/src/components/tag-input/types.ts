export interface TagInputProps {
  modelValue?: string[]
  placeholder?: string
  disabled?: boolean
  maxTags?: number
  allowDuplicates?: boolean
  showAddButton?: boolean
  tagVariant?: 'default' | 'secondary' | 'destructive' | 'outline'
  onUpdate?: (value: string[]) => void
  onChange?: (value: string[]) => void
  onAdd?: (tag: string) => void
  onRemove?: (tag: string) => void
}
