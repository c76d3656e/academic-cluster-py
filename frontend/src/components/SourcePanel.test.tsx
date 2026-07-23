import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ReviewResponse } from '../lib/api'
import { SourcePanel } from './SourcePanel'

function review(overrides: Partial<ReviewResponse> = {}): ReviewResponse {
  return {
    project_id: 'project-1',
    outline: null,
    sections: [],
    evidence_cards: [],
    references: [],
    final_review: null,
    abstract: null,
    status: 'completed',
    ...overrides,
  }
}

describe('SourcePanel', () => {
  it('renders only real API sources and evidence content', () => {
    render(
      <SourcePanel
        sources={[{ source: 'OpenAlex', count: 2, papers: [] }]}
        review={review({
          references: [{ new_number: 1, original_number: 3, paper_id: 'paper-1', title: 'Paper' }],
          evidence_cards: [
            {
              id: 'evidence-1',
              paper_id: 'paper-1',
              source_api: 'OpenAlex',
              claim: '层次化注意力改善了长文本分类。',
              evidence_span: 'The hierarchical module improved macro F1.',
              method: 'Ablation study',
              metric: 'Macro F1',
              confidence: 0.91,
              doi: '10.1000/example',
            },
          ],
        })}
      />,
    )

    expect(screen.getAllByText('OpenAlex')).not.toHaveLength(0)
    expect(screen.getByText('层次化注意力改善了长文本分类。')).toBeInTheDocument()
    expect(screen.getByText('The hierarchical module improved macro F1.')).toBeInTheDocument()
    expect(screen.getByText(/91% 置信度/)).toBeInTheDocument()
    expect(screen.queryByText('Semantic Scholar')).not.toBeInTheDocument()
  })

  it('reconstructs source counts from evidence for older review artifacts', () => {
    render(
      <SourcePanel
        sources={[]}
        review={review({
          evidence_cards: [
            { id: 'e-1', paper_id: 'p-1', source_api: 'Crossref', claim: 'Claim one' },
            { id: 'e-2', paper_id: 'p-2', source_api: 'Crossref', claim: 'Claim two' },
          ],
        })}
      />,
    )

    expect(screen.getAllByText('Crossref')).not.toHaveLength(0)
    expect(screen.getByText('2 篇')).toBeInTheDocument()
    expect(screen.getByText('Claim one')).toBeInTheDocument()
  })
})
