export interface Step {
  id: string
  title: string
  description?: string
  icon?: string
  status?: 'pending' | 'active' | 'completed' | 'error'
}

export interface StepperProps {
  steps: Step[]
  currentStep: number
  onStepClick?: (stepIndex: number) => void
  variant?: 'default' | 'vertical' | 'dots'
  size?: 'sm' | 'md' | 'lg'
  clickable?: boolean
  showDescription?: boolean
}
