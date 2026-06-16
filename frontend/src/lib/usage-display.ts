export const callTypeLabel: Record<string, string> = {
  llm: 'LLM',
  embedding: 'Embedding',
  rerank: 'Rerank',
}

export const callTypeBadgeClass: Record<string, string> = {
  llm: 'border-neutral-300 bg-neutral-100 text-neutral-900 dark:border-neutral-700 dark:bg-neutral-900/70 dark:text-neutral-100',
  embedding: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/60 dark:bg-blue-950/40 dark:text-blue-300',
  rerank: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300',
}

export const callTypeChartClass: Record<string, string> = {
  llm: 'bg-foreground/80',
  embedding: 'bg-blue-400/80',
  rerank: 'bg-amber-400/80',
}

export const callTypeValueClass: Record<string, string> = {
  llm: 'text-foreground',
  embedding: 'text-blue-500',
  rerank: 'text-amber-500',
}
