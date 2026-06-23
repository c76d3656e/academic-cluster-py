export interface Plan {
  id: string
  name: string
  price: number
  cadence: string
  description: string
  features: string[]
  featured?: boolean
}

export interface UsageMetric {
  label: string
  used: number
  limit: number
  unit?: string
}

export interface Invoice {
  id: string
  date: string
  amount: number
  status: 'paid' | 'open' | 'void'
  downloadUrl?: string
}

export interface PaymentMethod {
  type: string
  last4: string
  expiry: string
}

export interface BillingProps {
  plans: Plan[]
  currentPlanId: string
  usageMetrics: UsageMetric[]
  invoices: Invoice[]
  paymentMethod?: PaymentMethod
  onPlanSelect?: (planId: string) => void
  onPaymentUpdate?: () => void
  onInvoiceDownload?: (invoiceId: string) => void
}
