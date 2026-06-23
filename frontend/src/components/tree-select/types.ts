export interface TreeSelectNode {
  id: string | number
  label: string
  children?: TreeSelectNode[]
  disabled?: boolean
  icon?: string
  isLeaf?: boolean
}

export interface TreeSelectProps {
  modelValue?: string | number | (string | number)[]
  nodes: TreeSelectNode[]
  placeholder?: string
  disabled?: boolean
  clearable?: boolean
  searchable?: boolean
  multiple?: boolean
  showPath?: boolean
  expandAll?: boolean
  defaultExpandKeys?: (string | number)[]
  onUpdate?: (value: string | number | (string | number)[]) => void
  onChange?: (value: string | number | (string | number)[]) => void
  onSearch?: (query: string) => void
}
