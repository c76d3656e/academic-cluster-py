export interface CheckboxOption {
  value: string | number
  label: string
  description?: string
  disabled?: boolean
}

export interface CheckboxGroupProps {
  modelValue?: (string | number)[]
  options: CheckboxOption[]
  disabled?: boolean
  orientation?: 'horizontal' | 'vertical'
  size?: 'sm' | 'md' | 'lg'
  label?: string
  description?: string
  required?: boolean
  onUpdate?: (value: (string | number)[]) => void
  onChange?: (value: (string | number)[]) => void
}
