export const PIPELINE_STATUSES = [
  'pending',
  'running',
  'completed',
  'failed',
  'interrupted',
] as const

export type PipelineStatus = (typeof PIPELINE_STATUSES)[number]

export const PIPELINE_PHASES = [
  'supervisor',
  'research',
  'analysis',
  'writing',
  'peer_review',
  'finalize',
] as const

export type PipelinePhase = (typeof PIPELINE_PHASES)[number]

export interface PipelineStage {
  key: PipelinePhase
  labelKey: string
  icon: string
}

export const PIPELINE_STAGES: readonly PipelineStage[] = [
  { key: 'supervisor', labelKey: 'pipeline.phases.supervisor', icon: '◎' },
  { key: 'research', labelKey: 'pipeline.phases.research', icon: '⌕' },
  { key: 'analysis', labelKey: 'pipeline.phases.analysis', icon: '◇' },
  { key: 'writing', labelKey: 'pipeline.phases.writing', icon: '✎' },
  { key: 'peer_review', labelKey: 'pipeline.phases.peerReview', icon: '✓' },
  { key: 'finalize', labelKey: 'pipeline.phases.finalize', icon: '●' },
] as const

const PIPELINE_STATUS_SET = new Set<string>(PIPELINE_STATUSES)
const PIPELINE_PHASE_SET = new Set<string>(PIPELINE_PHASES)

export function isPipelineStatus(value: unknown): value is PipelineStatus {
  return typeof value === 'string' && PIPELINE_STATUS_SET.has(value)
}

export function isPipelinePhase(value: unknown): value is PipelinePhase {
  return typeof value === 'string' && PIPELINE_PHASE_SET.has(value)
}

/**
 * Convert API status values to the public five-state pipeline contract.
 * `created` is accepted only to keep pre-migration projects startable.
 */
export function normalizePipelineStatus(value: unknown): PipelineStatus {
  if (value === 'created') return 'pending'
  if (typeof value === 'string' && value.startsWith('running:')) return 'running'
  if (isPipelineStatus(value)) return value
  throw new TypeError(`Unsupported pipeline status: ${String(value)}`)
}

/** Resolve a canonical phase from a phase name or a legacy encoded running status. */
export function normalizePipelinePhase(value: unknown): PipelinePhase | null {
  if (isPipelinePhase(value)) return value
  if (typeof value !== 'string') return null

  const candidate = value.split(':').at(-1)
  return isPipelinePhase(candidate) ? candidate : null
}

export function isTerminalPipelineStatus(status: PipelineStatus): boolean {
  return status === 'completed' || status === 'failed' || status === 'interrupted'
}
