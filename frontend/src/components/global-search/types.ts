export interface SearchResult {
  id: string
  title: string
  subtitle?: string
  href: string
  icon?: string
}

export interface SearchSource {
  label: string
  items: unknown[]
  toResult: (item: unknown) => SearchResult
  search?: (query: string) => SearchResult[]
}

export interface GlobalSearchProps {
  sources: SearchSource[]
  placeholder?: string
  inline?: boolean
  limitPerGroup?: number
}
