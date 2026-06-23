export interface CommandProps {
  items?: any[]
  filter?: (query: string) => any[]
}

export interface CommandInputProps {
  modelValue?: string
  placeholder?: string
}

export interface CommandListProps {
  maxHeight?: string
}

export interface CommandGroupProps {
  heading?: string
}

export interface CommandItemProps {
  value: string
  disabled?: boolean
  selected?: boolean
}

export interface CommandDialogProps {
  open?: boolean
}
