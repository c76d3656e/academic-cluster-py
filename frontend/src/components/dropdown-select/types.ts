export interface DropdownSelectOption {
  value: string | number
  label: string
  description?: string
  disabled?: boolean
  icon?: string
  group?: string
}

export interface DropdownSelectProps {
  modelValue?: string | number
  options: DropdownSelectOption[]
  placeholder?: string
  disabled?: boolean
  clearable?: boolean
  searchable?: boolean
  multiple?: boolean
  maxItems?: number
  showIcon?: boolean
  showDescription?: boolean
  onUpdate?: (value: string | number | (string | number)[]) => void
  onChange?: (value: string | number | (string | number)[]) => void
}
