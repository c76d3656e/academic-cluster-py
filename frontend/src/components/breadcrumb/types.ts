export interface BreadcrumbItem {
  label: string
  href?: string
  icon?: string
  current?: boolean
}

export interface BreadcrumbProps {
  items: BreadcrumbItem[]
  separator?: string
  maxItems?: number
  showHome?: boolean
  homeLabel?: string
  homeHref?: string
}
