export interface SwitchProps {
  modelValue?: boolean
  disabled?: boolean
  size?: 'sm' | 'md' | 'lg'
  label?: string
  description?: string
  required?: boolean
  onUpdate?: (value: boolean) => void
  onChange?: (value: boolean) => void
}
