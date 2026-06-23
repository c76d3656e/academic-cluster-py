export interface AutocompleteOption {
  value: string | number
  label: string
  description?: string
  disabled?: boolean
  group?: string
}

export interface AutocompleteProps {
  modelValue?: string | number
  options: AutocompleteOption[]
  placeholder?: string
  disabled?: boolean
  clearable?: boolean
  searchable?: boolean
  multiple?: boolean
  maxItems?: number
  loading?: boolean
  noResultsText?: string
  filterFunction?: (option: AutocompleteOption, query: string) => boolean
  onUpdate?: (value: string | number | (string | number)[]) => void
  onChange?: (value: string | number | (string | number)[]) => void
  onSearch?: (query: string) => void
}
