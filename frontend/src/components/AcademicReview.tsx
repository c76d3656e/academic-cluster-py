import { ChevronDown, CornerUpLeft, ExternalLink, ListTree } from 'lucide-react'
import { memo, useEffect, useId, useMemo, useRef, useState, type MouseEvent } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import 'katex/dist/katex.min.css'
import {
  createAcademicCitationPlugin,
  collectCitationOccurrenceCounts,
  normalizeCitationReferences,
  type CitationReference,
  type NormalizedCitationReference,
} from '../lib/citations'
import { createReviewHeadingPlugin, extractReviewHeadings, type ReviewHeading } from '../lib/markdownHeadings'
import { normalizeMathDelimiters, rehypeAcademicEquations } from '../lib/mathMarkdown'

interface AcademicReviewProps {
  markdown: string
  references?: readonly CitationReference[]
}

interface ReferenceListProps {
  citationCounts: ReadonlyMap<number, number>
  references: readonly NormalizedCitationReference[]
}

interface ReviewTableOfContentsProps {
  activeId: string
  expanded: boolean
  headings: readonly ReviewHeading[]
  listId: string
  onNavigate: (event: MouseEvent<HTMLAnchorElement>, id: string) => void
  onToggle: () => void
}

const EMPTY_REFERENCES: readonly CitationReference[] = []
const INLINE_TOC_BREAKPOINT = 680
const KATEX_OPTIONS = {
  output: 'htmlAndMathml' as const,
  strict: 'ignore' as const,
  throwOnError: false,
}

function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function initialCompactToc(): boolean {
  return typeof window !== 'undefined' && window.innerWidth <= INLINE_TOC_BREAKPOINT
}

function decodeHashId(value: string): string {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

const markdownComponents: Components = {
  a({ node, href, className, children, ...props }) {
    void node
    const citationNumber = href?.match(/^#reference-(\d+)$/)?.[1]
    const external = Boolean(href && /^https?:\/\//i.test(href))
    return (
      <a
        {...props}
        href={href}
        target={external ? '_blank' : props.target}
        rel={external ? 'noreferrer noopener' : props.rel}
        className={[className, citationNumber ? 'citation-link' : ''].filter(Boolean).join(' ') || undefined}
        aria-label={citationNumber ? `\u67e5\u770b\u53c2\u8003\u6587\u732e ${citationNumber}` : props['aria-label']}
      >
        {children}
      </a>
    )
  },
  img({ node, ...props }) {
    void node
    const alt = typeof props.alt === 'string' && props.alt.trim() ? props.alt : '\u6587\u7ae0\u63d2\u56fe'
    return <img {...props} alt={alt} loading="lazy" decoding="async" />
  },
  table({ node, ...props }) {
    void node
    return (
      <div className="academic-table-scroll" role="region" aria-label={'\u6587\u7ae0\u6570\u636e\u8868'} tabIndex={0}>
        <table {...props} />
      </div>
    )
  },
}

function ReviewTableOfContents({
  activeId,
  expanded,
  headings,
  listId,
  onNavigate,
  onToggle,
}: ReviewTableOfContentsProps) {
  return (
    <nav className="review-toc" aria-label="文章目录" data-open={expanded ? 'true' : 'false'}>
      <div className="review-toc-heading">
        <ListTree size={15} aria-hidden="true" />
        <span>目录</span>
      </div>
      <button
        type="button"
        className="review-toc-toggle"
        aria-controls={listId}
        aria-expanded={expanded}
        onClick={onToggle}
      >
        <span>
          <ListTree size={16} aria-hidden="true" />
          目录
        </span>
        <ChevronDown className="review-toc-chevron" size={16} aria-hidden="true" />
      </button>
      <ol className="review-toc-list" id={listId}>
        {headings.map((heading) => {
          const active = heading.id === activeId
          return (
            <li className={`review-toc-item review-toc-depth-${heading.depth}`} key={heading.id}>
              <a
                className={active ? 'review-toc-link is-active' : 'review-toc-link'}
                href={`#${heading.id}`}
                aria-current={active ? 'location' : undefined}
                onClick={(event) => onNavigate(event, heading.id)}
              >
                {heading.title}
              </a>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

function normalizedDoi(doi: string): string {
  return doi
    .replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '')
    .replace(/^doi:\s*/i, '')
    .trim()
}

function safeHttpUrl(value: string): string {
  if (!value) return ''
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : ''
  } catch {
    return ''
  }
}

function ReferenceRow({ citationCount, reference }: { citationCount: number; reference: NormalizedCitationReference }) {
  const doi = normalizedDoi(reference.doi)
  const externalUrl = doi ? `https://doi.org/${doi}` : safeHttpUrl(reference.url)
  const externalLabel = doi ? `DOI ${doi}` : '\u539f\u6587'

  return (
    <li
      id={`reference-${reference.citationNumber}`}
      className="bibliography-row"
      tabIndex={-1}
      aria-label={`\u53c2\u8003\u6587\u732e ${reference.citationNumber}`}
    >
      <span className="bibliography-number" aria-hidden="true">
        [{reference.citationNumber}]
      </span>
      <div className="bibliography-entry">
        {reference.authorsText && <span className="bibliography-authors">{reference.authorsText}. </span>}
        <cite>{reference.title || reference.paperId || `\u53c2\u8003\u6587\u732e ${reference.citationNumber}`}</cite>
        {(reference.venue || reference.year) && (
          <span className="bibliography-publication">
            . {[reference.venue, reference.year].filter(Boolean).join(', ')}
          </span>
        )}
        {externalUrl && (
          <a
            className="bibliography-external"
            href={externalUrl}
            target="_blank"
            rel="noreferrer noopener"
            aria-label={`\u6253\u5f00\u53c2\u8003\u6587\u732e ${reference.citationNumber} \u7684${doi ? ' DOI' : '\u539f\u6587'}`}
          >
            {externalLabel}
            <ExternalLink size={12} aria-hidden="true" />
          </a>
        )}
        {citationCount > 0 && (
          <a
            className="bibliography-backlink"
            href={`#citation-${reference.citationNumber}-1`}
            aria-label={`返回正文中参考文献 ${reference.citationNumber} 的首次引用`}
            title="返回正文中的首次引用"
          >
            <CornerUpLeft size={13} aria-hidden="true" />
          </a>
        )}
      </div>
    </li>
  )
}

export function ReferenceList({ citationCounts, references }: ReferenceListProps) {
  if (references.length === 0) return null

  return (
    <section className="academic-bibliography" aria-labelledby="academic-bibliography-title">
      <h2 id="academic-bibliography-title" tabIndex={-1}>
        {'\u53c2\u8003\u6587\u732e'}
      </h2>
      <ol className="bibliography-list" aria-label={'\u53c2\u8003\u6587\u732e'}>
        {references.map((reference) => (
          <ReferenceRow
            key={reference.citationNumber}
            citationCount={citationCounts.get(reference.citationNumber) ?? 0}
            reference={reference}
          />
        ))}
      </ol>
    </section>
  )
}

function AcademicReviewView({ markdown, references }: AcademicReviewProps) {
  const resolvedReferences = references ?? EMPTY_REFERENCES
  const normalizedMarkdown = useMemo(() => normalizeMathDelimiters(markdown), [markdown])
  const normalizedReferences = useMemo(() => normalizeCitationReferences(resolvedReferences), [resolvedReferences])
  const citationCounts = useMemo(
    () => collectCitationOccurrenceCounts(normalizedMarkdown, resolvedReferences),
    [normalizedMarkdown, resolvedReferences],
  )
  const citationPlugin = useMemo(() => createAcademicCitationPlugin(resolvedReferences), [resolvedReferences])
  const headingPlugin = useMemo(() => createReviewHeadingPlugin(), [])
  const headings = useMemo(() => {
    const extracted = extractReviewHeadings(normalizedMarkdown, resolvedReferences)
    if (normalizedReferences.length === 0) return extracted
    return [
      ...extracted,
      {
        id: 'academic-bibliography-title',
        title: '\u53c2\u8003\u6587\u732e',
        depth: 2 as const,
      },
    ]
  }, [normalizedMarkdown, normalizedReferences.length, resolvedReferences])
  const [observedHeadingId, setObservedHeadingId] = useState('')
  const [compactToc, setCompactToc] = useState(initialCompactToc)
  const [tocExpanded, setTocExpanded] = useState(() => !initialCompactToc())
  const compactTocRef = useRef(compactToc)
  const tocListId = useId()
  const layoutRef = useRef<HTMLDivElement>(null)
  const pendingMobileScrollId = useRef<string | null>(null)
  const hashId = typeof window === 'undefined' ? '' : decodeHashId(window.location.hash.slice(1))
  const activeId = headings.some((heading) => heading.id === observedHeadingId)
    ? observedHeadingId
    : headings.some((heading) => heading.id === hashId)
      ? hashId
      : (headings[0]?.id ?? '')

  useEffect(() => {
    const layout = layoutRef.current
    if (!layout) return

    const updateLayoutMode = (width: number) => {
      if (width <= 0) return
      const nextCompact = width <= INLINE_TOC_BREAKPOINT
      if (compactTocRef.current === nextCompact) return
      compactTocRef.current = nextCompact
      setCompactToc(nextCompact)
      setTocExpanded(!nextCompact)
    }

    updateLayoutMode(layout.getBoundingClientRect().width)
    if (typeof ResizeObserver === 'undefined') return

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) updateLayoutMode(entry.contentRect.width)
    })
    observer.observe(layout)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (headings.length === 0 || typeof IntersectionObserver === 'undefined') return
    const intersectingHeadings = new Map<string, IntersectionObserverEntry>()
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) intersectingHeadings.set(entry.target.id, entry)
          else intersectingHeadings.delete(entry.target.id)
        })
        const nearest = [...intersectingHeadings.values()].sort(
          (left, right) => left.boundingClientRect.top - right.boundingClientRect.top,
        )[0]
        if (nearest?.target.id) {
          setObservedHeadingId((current) => (current === nearest.target.id ? current : nearest.target.id))
        }
      },
      { rootMargin: '-88px 0px -68% 0px', threshold: [0, 1] },
    )

    headings.forEach((heading) => {
      const target = document.getElementById(heading.id)
      if (target) observer.observe(target)
    })
    return () => observer.disconnect()
  }, [headings])

  useEffect(() => {
    const id = pendingMobileScrollId.current
    if (!id || tocExpanded) return
    pendingMobileScrollId.current = null
    const target = document.getElementById(id)
    if (!target) return
    target.scrollIntoView?.({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' })
  }, [tocExpanded])

  useEffect(() => {
    const restoreHashTarget = () => {
      const id = decodeHashId(window.location.hash.slice(1))
      const target = document.getElementById(id)
      if (!target || !layoutRef.current?.contains(target)) return

      target.focus({ preventScroll: true })
      if (headings.some((heading) => heading.id === id)) setObservedHeadingId(id)
      target.scrollIntoView?.({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' })
    }

    window.addEventListener('hashchange', restoreHashTarget)
    window.addEventListener('popstate', restoreHashTarget)
    restoreHashTarget()
    return () => {
      window.removeEventListener('hashchange', restoreHashTarget)
      window.removeEventListener('popstate', restoreHashTarget)
    }
  }, [headings])

  function navigateToHeading(event: MouseEvent<HTMLAnchorElement>, id: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    const target = document.getElementById(id)
    if (!target) return

    event.preventDefault()
    if (window.location.hash !== `#${id}`) window.history.pushState(null, '', `#${id}`)
    target.focus({ preventScroll: true })
    setObservedHeadingId(id)
    if (compactToc) {
      pendingMobileScrollId.current = id
      setTocExpanded(false)
      return
    }

    target.scrollIntoView?.({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' })
  }

  return (
    <div
      ref={layoutRef}
      className={headings.length > 0 ? 'academic-review-layout' : 'academic-review-layout academic-review-no-toc'}
      data-layout={compactToc ? 'compact' : 'wide'}
    >
      {headings.length > 0 && (
        <ReviewTableOfContents
          activeId={activeId}
          expanded={tocExpanded}
          headings={headings}
          listId={tocListId}
          onNavigate={navigateToHeading}
          onToggle={() => setTocExpanded((value) => !value)}
        />
      )}
      <div className="academic-review-content">
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath, citationPlugin, headingPlugin]}
          rehypePlugins={[[rehypeKatex, KATEX_OPTIONS], rehypeAcademicEquations]}
          components={markdownComponents}
        >
          {normalizedMarkdown}
        </ReactMarkdown>
        <ReferenceList citationCounts={citationCounts} references={normalizedReferences} />
      </div>
    </div>
  )
}

export const AcademicReview = memo(AcademicReviewView)
AcademicReview.displayName = 'AcademicReview'
