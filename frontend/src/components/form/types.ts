export interface FormField {
  name: string
  label: string
  type: 'text' | 'email' | 'password' | 'number' | 'textarea' | 'select' | 'checkbox' | 'radio' | 'date' | 'file'
  placeholder?: string
  required?: boolean
  disabled?: boolean
  description?: string
  options?: { label: string; value: string | number }[]
  validation?: {
    min?: number
    max?: number
    minLength?: number
    maxLength?: number
    pattern?: string
    message?: string
  }
}

export interface FormProps {
  fields: FormField[]
  initialValues?: Record<string, unknown>
  onSubmit?: (values: Record<string, unknown>) => void
  onCancel?: () => void
  submitLabel?: string
  cancelLabel?: string
  isLoading?: boolean
  disabled?: boolean
}

export interface FormFieldProps {
  field: FormField
  value: unknown
  error?: string
  disabled?: boolean
  onChange: (value: unknown) => void
  onBlur: () => void
}
