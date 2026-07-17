import { describe, expect, it } from 'vitest'
import {
  isPipelinePhase,
  isPipelineStatus,
  isTerminalPipelineStatus,
  normalizePipelinePhase,
  normalizePipelineStatus,
  PIPELINE_PHASES,
  PIPELINE_STATUSES,
  PIPELINE_STAGES,
} from './pipeline'

describe('pipeline contract', () => {
  it('exposes only the supported public statuses', () => {
    expect(PIPELINE_STATUSES).toEqual([
      'pending',
      'running',
      'completed',
      'failed',
      'interrupted',
    ])
    expect(PIPELINE_STATUSES.every(isPipelineStatus)).toBe(true)
    expect(isPipelineStatus('agent_completed')).toBe(false)
  })

  it('exposes the six multi-agent phases in execution order', () => {
    expect(PIPELINE_PHASES).toEqual([
      'supervisor',
      'research',
      'analysis',
      'writing',
      'peer_review',
      'finalize',
    ])
    expect(PIPELINE_STAGES.map(stage => stage.key)).toEqual(PIPELINE_PHASES)
    expect(PIPELINE_PHASES.every(isPipelinePhase)).toBe(true)
  })

  it('normalizes persisted pre-migration and encoded running states', () => {
    expect(normalizePipelineStatus('created')).toBe('pending')
    expect(normalizePipelineStatus('running:agent:analysis')).toBe('running')
    expect(normalizePipelineStatus('interrupted')).toBe('interrupted')
  })

  it('rejects removed or unknown terminal status aliases', () => {
    expect(() => normalizePipelineStatus('agent_completed')).toThrow(TypeError)
    expect(() => normalizePipelineStatus('completed_with_warnings')).toThrow(TypeError)
    expect(() => normalizePipelineStatus(undefined)).toThrow(TypeError)
  })

  it('resolves only canonical phases from API values', () => {
    expect(normalizePipelinePhase('peer_review')).toBe('peer_review')
    expect(normalizePipelinePhase('running:agent:writing')).toBe('writing')
    expect(normalizePipelinePhase('search')).toBeNull()
    expect(normalizePipelinePhase(null)).toBeNull()
  })

  it('recognizes every terminal state without treating pending or running as terminal', () => {
    expect(isTerminalPipelineStatus('completed')).toBe(true)
    expect(isTerminalPipelineStatus('failed')).toBe(true)
    expect(isTerminalPipelineStatus('interrupted')).toBe(true)
    expect(isTerminalPipelineStatus('pending')).toBe(false)
    expect(isTerminalPipelineStatus('running')).toBe(false)
  })
})
