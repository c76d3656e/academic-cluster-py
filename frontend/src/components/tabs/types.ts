export interface TabItem {
  id: string
  label: string
  icon?: string
  disabled?: boolean
  badge?: string | number
  content?: unknown
}

export interface TabsProps {
  items: TabItem[]
  defaultTab?: string
  onChange?: (tabId: string) => void
  variant?: 'default' | 'pills' | 'underline'
  size?: 'sm' | 'md' | 'lg'
  fullWidth?: boolean
}
