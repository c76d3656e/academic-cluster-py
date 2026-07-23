import type { Heading, Link, Parent, PhrasingContent, Root, Text } from 'mdast'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import remarkParse from 'remark-parse'
import type { Plugin } from 'unified'
import { unified } from 'unified'
import { normalizeMathDelimiters } from './mathMarkdown'

export interface CitationReference {
  new_number?: number | string | null
  number?: number | string | null
  original_number?: number | string | null
  paper_id?: string | null
  title?: string | null
  authors?: unknown
  venue?: string | null
  year?: string | number | null
  doi?: string | null
  url?: string | null
}

export interface NormalizedCitationReference {
  citationNumber: number
  paperId: string
  title: string
  authorsText: string
  authorLabel: string
  venue: string
  year: string
  doi: string
  url: string
}

export interface CitationPluginOptions {
  onOccurrence?: (citationNumber: number, occurrence: number, targetId: string) => void
}

const CITATION_PATTERN = /\[(\d+(?:\s*(?:[,;\u3001\uff0c\u00b7\uff1b\s]|[-\u2013\u2014])\s*\d+)*)\]/gu
const NUMBER_PATTERN = /\d+/g
const RANGE_SEPARATOR_PATTERN = /^\s*[-\u2013\u2014]\s*$/u
const MAX_CITATION_RANGE_SPAN = 20
const SENTENCE_BOUNDARY_PATTERN =
  /(?:^|[\n\u3002\uff01\uff1f!?\uff1b;.:\uff1a,\uff0c])[\s"'\u201c\u201d\u2018\u2019\uff08(]*$/u
const PROPOSAL_AFTER_CITATIONS_PATTERN =
  /^(?:\s*\[\d+(?:\s*(?:[,;\u3001\uff0c\u00b7\uff1b\s]|[-\u2013\u2014])\s*\d+)*\])*\s*\u63d0\u51fa/u
const INLINE_ROOT_TYPES = new Set(['paragraph', 'heading', 'tableCell'])
const INLINE_CONTAINER_TYPES = new Set(['emphasis', 'strong', 'delete'])
const SKIPPED_INLINE_TYPES = new Set(['link', 'linkReference', 'code', 'inlineCode'])

function positiveInteger(value: unknown): number | null {
  const candidate = typeof value === 'string' && /^\d+$/u.test(value.trim()) ? Number(value.trim()) : value
  if (typeof candidate !== 'number' || !Number.isSafeInteger(candidate) || candidate < 1) return null
  return candidate
}

function authorNames(authors: unknown): string[] {
  if (typeof authors === 'string') {
    const value = authors.trim()
    if (!value) return []
    return value
      .split(/\s*(?:;|\uff1b|\uff0c|,\s*(?=[\p{L}]))\s*/u)
      .map((name) => name.trim())
      .filter(Boolean)
  }
  if (!Array.isArray(authors)) return []
  return authors
    .map((author) => {
      if (typeof author === 'string') return author.trim()
      if (!author || typeof author !== 'object') return ''
      const record = author as Record<string, unknown>
      const directName = String(record.name || record.full_name || '').trim()
      if (directName) return directName
      return [record.given, record.family]
        .map((part) => String(part || '').trim())
        .filter(Boolean)
        .join(' ')
    })
    .filter(Boolean)
}

function authorsText(authors: unknown): string {
  if (typeof authors === 'string') return authors.trim()
  return authorNames(authors).join(', ')
}

export function firstAuthorLabel(authors: unknown): string {
  return authorNames(authors)[0] || ''
}

export function normalizeCitationReferences(references: readonly CitationReference[]): NormalizedCitationReference[] {
  const byNumber = new Map<number, NormalizedCitationReference>()

  references.forEach((reference, index) => {
    const citationNumber =
      positiveInteger(reference.new_number) ??
      positiveInteger(reference.number) ??
      positiveInteger(reference.original_number) ??
      index + 1
    if (byNumber.has(citationNumber)) return

    byNumber.set(citationNumber, {
      citationNumber,
      paperId: String(reference.paper_id || '').trim(),
      title: String(reference.title || '').trim(),
      authorsText: authorsText(reference.authors),
      authorLabel: firstAuthorLabel(reference.authors),
      venue: String(reference.venue || '').trim(),
      year: String(reference.year || '').trim(),
      doi: String(reference.doi || '').trim(),
      url: String(reference.url || '').trim(),
    })
  })

  return [...byNumber.values()].sort((left, right) => left.citationNumber - right.citationNumber)
}

function textNode(value: string): Text {
  return { type: 'text', value }
}

interface CitationSurfaceNumber {
  index: number
  length: number
  number: number
  rangeNumbers: number[]
}

function citationSurfaceNumbers(surface: string): CitationSurfaceNumber[] {
  const tokens = [...surface.matchAll(NUMBER_PATTERN)].map((match) => ({
    index: match.index ?? 0,
    length: match[0].length,
    number: Number(match[0]),
    rangeNumbers: [] as number[],
  }))

  tokens.forEach((token, index) => {
    const next = tokens[index + 1]
    if (!next) return
    const between = surface.slice(token.index + token.length, next.index)
    if (!RANGE_SEPARATOR_PATTERN.test(between)) return

    // The backend treats descending ranges as malformed. Keep their two
    // explicit endpoints readable, but do not invent intermediate citations.
    if (next.number < token.number) return
    const span = Math.abs(next.number - token.number) + 1
    if (span > MAX_CITATION_RANGE_SPAN) return
    const step = token.number <= next.number ? 1 : -1
    for (let number = token.number + step; number !== next.number; number += step) {
      token.rangeNumbers.push(number)
    }
  })

  return tokens
}

function expandedCitationNumbers(surface: string): number[] {
  return citationSurfaceNumbers(surface).flatMap((token) => [token.number, ...token.rangeNumbers])
}

function citationLink(number: number, occurrence: number, hiddenRangeNumber = false): Link {
  const id = `citation-${number}-${occurrence}`
  return {
    type: 'link',
    url: `#reference-${number}`,
    children: hiddenRangeNumber ? [] : [textNode(String(number))],
    data: {
      hProperties: {
        id,
        ...(hiddenRangeNumber
          ? {
              className: ['citation-range-anchor'],
              ariaLabel: `\u67e5\u770b\u53c2\u8003\u6587\u732e ${number}`,
              tabIndex: -1,
            }
          : {}),
      },
    },
  }
}

function citationGroupNodes(
  surface: string,
  knownReferences: ReadonlyMap<number, NormalizedCitationReference>,
  occurrenceCounts: Map<number, number>,
  onOccurrence?: CitationPluginOptions['onOccurrence'],
) {
  const nodes: PhrasingContent[] = []
  let cursor = 0

  const appendCitation = (number: number, hiddenRangeNumber: boolean) => {
    if (knownReferences.has(number)) {
      const occurrence = (occurrenceCounts.get(number) ?? 0) + 1
      occurrenceCounts.set(number, occurrence)
      const targetId = `citation-${number}-${occurrence}`
      onOccurrence?.(number, occurrence, targetId)
      nodes.push(citationLink(number, occurrence, hiddenRangeNumber))
    } else {
      if (!hiddenRangeNumber) nodes.push(textNode(String(number)))
    }
  }

  for (const token of citationSurfaceNumbers(surface)) {
    if (token.index > cursor) nodes.push(textNode(surface.slice(cursor, token.index)))
    appendCitation(token.number, false)
    token.rangeNumbers.forEach((number) => appendCitation(number, true))
    cursor = token.index + token.length
  }

  if (cursor < surface.length) nodes.push(textNode(surface.slice(cursor)))
  return nodes
}

function splitCitationText(
  value: string,
  knownReferences: ReadonlyMap<number, NormalizedCitationReference>,
  precedingText: string,
  occurrenceCounts: Map<number, number>,
  onOccurrence?: CitationPluginOptions['onOccurrence'],
): PhrasingContent[] | null {
  const nodes: PhrasingContent[] = []
  let cursor = 0
  let transformed = false

  for (const match of value.matchAll(CITATION_PATTERN)) {
    const index = match.index ?? 0
    const numbers = expandedCitationNumbers(match[0])
    const firstKnownNumber = numbers.find((number) => knownReferences.has(number))
    if (firstKnownNumber === undefined) continue

    if (index > cursor) nodes.push(textNode(value.slice(cursor, index)))

    const beforeCitation = precedingText + value.slice(0, index)
    const afterCitation = value.slice(index + match[0].length)
    const reference = knownReferences.get(firstKnownNumber)
    if (
      reference?.authorLabel &&
      SENTENCE_BOUNDARY_PATTERN.test(beforeCitation) &&
      PROPOSAL_AFTER_CITATIONS_PATTERN.test(afterCitation)
    ) {
      nodes.push(textNode(reference.authorLabel))
    }

    nodes.push(...citationGroupNodes(match[0], knownReferences, occurrenceCounts, onOccurrence))
    cursor = index + match[0].length
    transformed = true
  }

  if (!transformed) return null
  if (cursor < value.length) nodes.push(textNode(value.slice(cursor)))
  return nodes
}

function hasChildren(node: PhrasingContent): node is PhrasingContent & Parent {
  return 'children' in node && Array.isArray(node.children)
}

function nodeText(node: PhrasingContent): string {
  if (node.type === 'text') return node.value
  if (!hasChildren(node)) return ''
  return node.children.map((child) => nodeText(child as PhrasingContent)).join('')
}

function transformInlineParent(
  parent: Parent,
  knownReferences: ReadonlyMap<number, NormalizedCitationReference>,
  inheritedText = '',
  occurrenceCounts = new Map<number, number>(),
  onOccurrence?: CitationPluginOptions['onOccurrence'],
): void {
  let precedingText = inheritedText

  for (let index = 0; index < parent.children.length; index += 1) {
    const child = parent.children[index] as PhrasingContent
    if (child.type === 'text') {
      const replacement = splitCitationText(child.value, knownReferences, precedingText, occurrenceCounts, onOccurrence)
      if (replacement) {
        parent.children.splice(index, 1, ...replacement)
        index += replacement.length - 1
      }
      precedingText += replacement?.map(nodeText).join('') ?? child.value
      continue
    }

    if (hasChildren(child) && INLINE_CONTAINER_TYPES.has(child.type) && !SKIPPED_INLINE_TYPES.has(child.type)) {
      transformInlineParent(child, knownReferences, precedingText, occurrenceCounts, onOccurrence)
    }
    precedingText += nodeText(child)
  }
}

function transformCitations(
  parent: Parent,
  knownReferences: ReadonlyMap<number, NormalizedCitationReference>,
  occurrenceCounts: Map<number, number>,
  onOccurrence?: CitationPluginOptions['onOccurrence'],
): void {
  for (const child of parent.children) {
    if (!('children' in child) || !Array.isArray(child.children)) continue
    if (INLINE_ROOT_TYPES.has(child.type)) {
      transformInlineParent(child, knownReferences, '', occurrenceCounts, onOccurrence)
    } else if (!SKIPPED_INLINE_TYPES.has(child.type)) {
      transformCitations(child, knownReferences, occurrenceCounts, onOccurrence)
    }
  }
}

function headingText(heading: Heading): string {
  return heading.children
    .map((child) => nodeText(child))
    .join('')
    .trim()
}

function isBibliographyHeading(node: Root['children'][number]): node is Heading {
  if (node.type !== 'heading') return false
  const title = headingText(node)
    .replace(/^\d+(?:\.\d+)*[.)\u3001]?\s*/u, '')
    .trim()
  return /^(?:references?|bibliography|\u53c2\u8003\u6587\u732e|\u53c2\u8003\u8d44\u6599)(?:\s*[\uff08(]references?[\uff09)])?$/iu.test(
    title,
  )
}

function stripEmbeddedBibliography(root: Root): void {
  const bibliographyIndex = root.children.findIndex(isBibliographyHeading)
  if (bibliographyIndex < 0) return

  const bibliographyHeading = root.children[bibliographyIndex]
  if (bibliographyHeading.type !== 'heading') return
  const nextSectionOffset = root.children.slice(bibliographyIndex + 1).findIndex((node) => {
    return node.type === 'heading' && node.depth <= bibliographyHeading.depth
  })
  const deleteCount = nextSectionOffset < 0 ? root.children.length - bibliographyIndex : nextSectionOffset + 1
  root.children.splice(bibliographyIndex, deleteCount)
}

export function createAcademicCitationPlugin(
  references: readonly CitationReference[],
  options: CitationPluginOptions = {},
): Plugin<[], Root> {
  const normalizedReferences = normalizeCitationReferences(references)
  const referenceMap = new Map(normalizedReferences.map((reference) => [reference.citationNumber, reference]))
  const occurrenceCounts = new Map<number, number>()

  return function academicCitationPlugin() {
    return function transformAcademicCitations(tree) {
      occurrenceCounts.clear()
      if (referenceMap.size > 0) stripEmbeddedBibliography(tree)
      transformCitations(tree, referenceMap, occurrenceCounts, options.onOccurrence)
    }
  }
}

export function collectCitationOccurrenceCounts(
  markdown: string,
  references: readonly CitationReference[],
): ReadonlyMap<number, number> {
  const counts = new Map<number, number>()
  const processor = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkMath)
    .use(
      createAcademicCitationPlugin(references, {
        onOccurrence: (citationNumber, occurrence) => counts.set(citationNumber, occurrence),
      }),
    )

  processor.runSync(processor.parse(normalizeMathDelimiters(markdown)))
  return counts
}
