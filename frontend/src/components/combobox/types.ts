export interface ComboboxOption {
  value: string | number
  label: string
  description?: string
  disabled?: boolean
  group?: string
}

export interface ComboboxProps {
  modelValue?: string | number
  options: ComboboxOption[]
  placeholder?: string
  disabled?: boolean
  clearable?: boolean
  searchable?: boolean
  loading?: boolean
  noResultsText?: string
  filterFunction?: (option: ComboboxOption, query: string) => boolean
  onUpdate?: (value: string | number) => void
  onChange?: (value: string | number) => void
  onSearch?: (query: string) => void
}
