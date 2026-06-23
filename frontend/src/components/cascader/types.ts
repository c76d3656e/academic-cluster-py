export interface CascaderOption {
  value: string | number
  label: string
  children?: CascaderOption[]
  disabled?: boolean
  isLeaf?: boolean
}

export interface CascaderProps {
  modelValue?: (string | number)[]
  options: CascaderOption[]
  placeholder?: string
  disabled?: boolean
  clearable?: boolean
  searchable?: boolean
  changeOnSelect?: boolean
  showPath?: boolean
  expandTrigger?: 'click' | 'hover'
  onUpdate?: (value: (string | number)[]) => void
  onChange?: (value: (string | number)[]) => void
  onSearch?: (query: string) => void
}
