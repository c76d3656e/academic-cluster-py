import { ExternalLink, LibraryBig, Radar } from 'lucide-react'
import { motion } from 'motion/react'
import type { EvidenceCard, PipelinePhase, ProgressNode, ReviewResponse, SearchSourceSummary } from '../lib/api'
import { Badge, EmptyState } from './ui'

interface SourcePanelProps {
  review?: ReviewResponse | null
  progress?: ProgressNode[]
  activePhase?: PipelinePhase | null
  sources?: SearchSourceSummary[]
  compact?: boolean
}

function normalizedSource(value?: string | null) {
  return String(value || '未标注来源').trim() || '未标注来源'
}

function sourcesFromEvidence(cards: EvidenceCard[]): SearchSourceSummary[] {
  const counts = new Map<string, number>()
  cards.forEach((card) => {
    const source = normalizedSource(card.source_api)
    counts.set(source, (counts.get(source) ?? 0) + 1)
  })
  return Array.from(counts, ([source, count]) => ({ source, count, papers: [] }))
}

function confidenceLabel(confidence?: number | null) {
  if (confidence == null) return null
  const percent = confidence <= 1 ? confidence * 100 : confidence
  return `${Math.round(percent)}% 置信度`
}

export function SourcePanel({ review, progress = [], activePhase, sources = [], compact = false }: SourcePanelProps) {
  const cards = review?.evidence_cards ?? []
  const references = review?.references ?? []
  const displaySources = sources.length > 0 ? sources : sourcesFromEvidence(cards)
  const researchNode = progress.find((node) => node.node_name === 'research')
  const researchComplete = researchNode?.status === 'completed'
  const visibleSources = compact ? displaySources.slice(0, 6) : displaySources
  const visibleCards = compact ? cards.slice(0, 3) : cards
  const sourcePaperCount = displaySources.reduce((total, source) => total + source.count, 0)

  return (
    <section className={compact ? 'source-panel source-panel-compact' : 'source-panel'} aria-label="来源与证据">
      <div className="source-panel-heading">
        <h3>来源与证据</h3>
        <Badge tone={activePhase === 'research' ? 'active' : researchComplete ? 'success' : 'neutral'}>
          {activePhase === 'research' ? '检索中' : researchComplete ? '已完成' : '等待数据'}
        </Badge>
      </div>

      {(displaySources.length > 0 || cards.length > 0 || references.length > 0) && (
        <div className="source-summary" aria-label="来源统计">
          <span>
            <strong>{sourcePaperCount}</strong> 篇论文
          </span>
          <span>
            <strong>{cards.length}</strong> 张证据卡
          </span>
          <span>
            <strong>{references.length}</strong> 条引用
          </span>
        </div>
      )}

      {visibleSources.length > 0 ? (
        <div className="source-list" aria-label="检索来源">
          {visibleSources.map((source, index) => (
            <motion.div
              className="source-row"
              key={source.source}
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18, delay: index * 0.025 }}
            >
              <span className="source-mark" aria-hidden="true" />
              <strong>{source.source}</strong>
              <span>{source.count.toLocaleString('zh-CN')} 篇</span>
              {activePhase === 'research' && <Radar size={13} className="source-pulse" aria-label="正在检索" />}
            </motion.div>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={<LibraryBig size={20} />}
          title={activePhase === 'research' ? '正在检索来源' : '暂无来源数据'}
        />
      )}

      {visibleCards.length > 0 && (
        <div className="evidence-section">
          <div className="evidence-heading">
            <h4>证据卡</h4>
            {compact && cards.length > visibleCards.length && <span>显示前 {visibleCards.length} 条</span>}
          </div>
          <div className="evidence-list">
            {visibleCards.map((card, index) => {
              const metadata = [card.method, card.metric, confidenceLabel(card.confidence)].filter(Boolean)
              return (
                <article className="evidence-row" key={`${card.id || card.paper_id}-${index}`}>
                  <div className="evidence-source-line">
                    <span>{normalizedSource(card.source_api)}</span>
                    {card.doi && (
                      <a
                        href={`https://doi.org/${card.doi}`}
                        target="_blank"
                        rel="noreferrer"
                        aria-label={`打开证据 ${index + 1} 的 DOI`}
                      >
                        <ExternalLink size={13} />
                      </a>
                    )}
                  </div>
                  <h5>{card.claim || card.title || `证据 ${index + 1}`}</h5>
                  {card.evidence_span && <blockquote>{card.evidence_span}</blockquote>}
                  {(card.title || card.authors || card.year) && (
                    <p className="evidence-paper">
                      {[card.title, card.authors, card.year].filter(Boolean).join(' · ')}
                    </p>
                  )}
                  {metadata.length > 0 && <p className="evidence-meta">{metadata.join(' · ')}</p>}
                  {card.limitation && <p className="evidence-limitation">局限：{card.limitation}</p>}
                </article>
              )
            })}
          </div>
        </div>
      )}
    </section>
  )
}
