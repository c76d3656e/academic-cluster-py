import type { ClassValue } from "clsx"
import { clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// ─── Shared status helpers ──────────────────────────────────────────────

/** Badge variant for project/task status */
export function getStatusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'completed': return 'default'
    case 'running': return 'secondary'
    case 'failed': return 'destructive'
    default: return 'outline'
  }
}

/** Human-readable label for a status string (handles "running:NODE" prefix) */
export function getStatusLabel(status: string): string {
  if (status === 'completed') return 'Completed'
  if (status === 'failed') return 'Failed'
  if (status === 'interrupted') return 'Interrupted'
  if (status === 'created') return 'Ready'
  if (status.startsWith('running:')) {
    const node = status.replace('running:', '')
    const nodeNames: Record<string, string> = {
      search: 'Searching',
      deduplicate: 'Deduplicating',
      filter: 'Filtering',
      bm25: 'Building index',
      embedding: 'Vectorizing',
      pgvector_knn: 'Building KNN',
      rerank: 'Reranking',
      kg_extraction: 'Extracting KG',
      community_memory: 'Synthesizing memory',
      community_detection: 'Detecting communities',
      visualize_community: 'Generating visualization',
      evidence_cards: 'Generating evidence cards',
      gap_analysis: 'Analyzing gaps',
      targeted_refine: 'Supplementary search',
      outline_generation: 'Generating outline',
      user_confirm: 'Awaiting confirmation',
      write_review: 'Writing review',
      coverage_audit: 'Auditing coverage',
      section_revision: 'Revising sections',
      artifact_registration: 'Registering artifacts',
      finalize: 'Finalizing',
    }
    return nodeNames[node] || `Running: ${node}`
  }
  if (status === 'running') return 'Running'
  return status
}

// ─── Number / token formatting ──────────────────────────────────────────

/** Format large token counts (e.g. 1_234_567 -> "1.2M") */
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

/** Format a cost value as USD with 6 decimal places */
export function formatCost(value: number): string {
  return `$${Number(value || 0).toFixed(6)}`
}

// ─── Time formatting ────────────────────────────────────────────────────

/** Current time as HH:MM:SS (zh-CN locale) */
export function formatTime(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** Human-readable runtime between two ISO timestamps */
export function formatRuntime(start: string, end?: string): string {
  const t1 = new Date(start).getTime()
  const t2 = end ? new Date(end).getTime() : Date.now()
  const total = Math.max(0, Math.floor((t2 - t1) / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

// ─── User helpers ───────────────────────────────────────────────────────

/** First two characters of an email, upper-cased (for avatar fallback) */
export function getInitials(email: string): string {
  return email.slice(0, 2).toUpperCase()
}
