export interface WizardStep {
  id: string
  title: string
  description?: string
  component: unknown
  props?: Record<string, unknown>
  validation?: () => boolean | Promise<boolean>
}

export interface WizardProps {
  steps: WizardStep[]
  initialStep?: number
  onComplete?: (data: Record<string, unknown>) => void
  onCancel?: () => void
  showProgress?: boolean
  allowSkip?: boolean
  submitLabel?: string
  cancelLabel?: string
  nextLabel?: string
  previousLabel?: string
}
