import type { Element, Root as HastRoot } from 'hast'
import remarkGfm from 'remark-gfm'
import remarkParse from 'remark-parse'
import type { Plugin } from 'unified'
import { unified } from 'unified'
import type { Node } from 'unist'
import { visit } from 'unist-util-visit'

/**
 * Normalize TeX delimiter variants before remark-parse runs.
 *
 * `remark-parse` treats the backslash in `\(...\)`/`\[...\]` as a Markdown
 * escape, so a post-parse plugin cannot recover those delimiters. This helper
 * converts only paired legacy delimiters and leaves Markdown code regions
 * untouched. The result is intended to be passed to `remark-math`.
 */

const MARKDOWN_CODE_PARSER = unified().use(remarkParse).use(remarkGfm)

function isEscaped(source: string, index: number): boolean {
  let slashCount = 0
  for (let cursor = index - 1; cursor >= 0 && source[cursor] === '\\'; cursor -= 1) {
    slashCount += 1
  }
  return slashCount % 2 === 1
}

function markRange(mask: Uint8Array, start: number, end: number): void {
  for (let index = start; index < end; index += 1) mask[index] = 1
}

/**
 * Mark Markdown regions where math delimiters are literal text.
 *
 * The CommonMark parser owns code-block and code-span recognition, including
 * list-relative indentation and escaped backticks. A byte mask is used instead
 * of placeholders so source text, Unicode, and line endings remain unchanged.
 */
function protectedMarkdownRegions(source: string): Uint8Array {
  const mask = new Uint8Array(source.length)
  const tree = MARKDOWN_CODE_PARSER.parse(source)
  visit(tree, ['code', 'inlineCode'], (node: Node) => {
    const start = node.position?.start.offset
    const end = node.position?.end.offset
    if (typeof start === 'number' && typeof end === 'number') markRange(mask, start, end)
  })

  return mask
}

const CURRENCY_AMOUNT_PATTERN = /^-?(?:\d{1,3}(?:[,\u00a0\u202f]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)/u
const CURRENCY_CITATION_PATTERN = /^\s*\[\d+(?:\s*(?:[,;\u3001\uff0c\u00b7\uff1b\s]|[-\u2013\u2014])\s*\d+)*\]/u
const CURRENCY_SUFFIX_PATTERN =
  /^(?:\s*usd\b|\s+(?:us\s+dollars?|dollars?|million|billion|trillion)\b|\s*(?:k|m|mn|mm|b|bn|t)(?=[\s.,;:!?，。；：！？]|\[|$)|\s*\/[a-z][a-z0-9._-]*(?=[\s.,;:!?，。；：！？]|\[|$)|\s*\[\d+(?:\s*(?:[,;\u3001\uff0c\u00b7\uff1b\s]|[-\u2013\u2014])\s*\d+)*\]|\s*(?:美元|美金|元)|(?=[,.;:!?，。；：！？](?:\s|$))|$)/iu

function hasImmediateMathClose(source: string, index: number): boolean {
  let cursor = index
  while (cursor < source.length) {
    const citation = source.slice(cursor).match(CURRENCY_CITATION_PATTERN)
    if (!citation) break
    cursor += citation[0].length
  }
  return source[cursor] === '$'
}

/**
 * Return whether a single dollar starts a likely monetary amount.
 *
 * `remark-math` intentionally treats every paired `$` as inline math. That
 * makes prose such as `$5 million [1]` consume the next formula delimiter and
 * hide both the citation and the surrounding text. Only common currency
 * surfaces are escaped; algebraic expressions such as `$5 + x$` remain math.
 */
function isCurrencyDollar(source: string, index: number): boolean {
  const end = source.length
  if (index + 1 >= end) return false

  const amount = source.slice(index + 1).match(CURRENCY_AMOUNT_PATTERN)
  if (!amount) return false

  const amountEnd = index + 1 + amount[0].length
  if (hasImmediateMathClose(source, amountEnd)) return false
  const suffix = source.slice(amountEnd).match(CURRENCY_SUFFIX_PATTERN)
  if (!suffix) return false

  // `$5 million$` and `$5 USD$` are explicit paired math delimiters. Keep
  // those surfaces as math; only escape a currency amount when the suffix is
  // followed by prose, punctuation, a citation, or the end of the source.
  return !hasImmediateMathClose(source, amountEnd + suffix[0].length)
}

/**
 * Escape currency dollars outside Markdown code regions while preserving the
 * source text that the reader sees. An escaped dollar is rendered literally by
 * Markdown, but no longer participates in remark-math delimiter pairing.
 */
function protectCurrencyDollars(source: string): string {
  const mask = protectedMarkdownRegions(source)
  let output = ''
  let cursor = 0
  let changed = false

  for (let index = 0; index < source.length; index += 1) {
    if (
      source[index] !== '$' ||
      mask[index] ||
      isEscaped(source, index) ||
      source[index - 1] === '$' ||
      source[index + 1] === '$' ||
      !isCurrencyDollar(source, index)
    ) {
      continue
    }

    output += source.slice(cursor, index)
    output += '\\$'
    cursor = index + 1
    changed = true
  }

  return changed ? output + source.slice(cursor) : source
}

function hasProtectedCharacter(mask: Uint8Array, start: number, end: number): boolean {
  for (let index = start; index < end; index += 1) {
    if (mask[index]) return true
  }
  return false
}

function findClosingDelimiter(source: string, start: number, delimiter: '\\)' | '\\]', mask: Uint8Array): number {
  for (let index = start; index <= source.length - delimiter.length; index += 1) {
    if (mask[index] || mask[index + 1]) continue
    if (source.startsWith(delimiter, index) && !isEscaped(source, index)) return index
  }
  return -1
}

function blockReplacement(source: string, start: number, close: number, inner: string): string {
  const lineStart = source.lastIndexOf('\n', start - 1) + 1
  const lineEnd = source.indexOf('\n', close + 2)
  const currentLineEnd = lineEnd < 0 ? source.length : lineEnd
  const prefix = source.slice(lineStart, start)
  const suffix = source.slice(close + 2, currentLineEnd)
  const withoutOpeningBreak = inner.startsWith('\r\n') ? inner.slice(2) : inner.replace(/^\n/, '')
  const normalizedInner = withoutOpeningBreak.endsWith('\r\n')
    ? withoutOpeningBreak.slice(0, -2)
    : withoutOpeningBreak.replace(/\n$/, '')
  const body = `$$\n${normalizedInner}\n$$`

  // Flow math is only valid at a block boundary. Keep a standalone `\[...\]`
  // compact; otherwise split the surrounding paragraph explicitly.
  if (!prefix.trim() && !suffix.trim()) return body
  return `\n\n${body}\n\n`
}

function isExactDoubleDollar(source: string, index: number): boolean {
  return source[index] === '$' && source[index + 1] === '$' && source[index - 1] !== '$' && source[index + 2] !== '$'
}

function findClosingDoubleDollar(source: string, start: number, mask: Uint8Array): number {
  for (let index = start; index < source.length - 1; index += 1) {
    if (mask[index] || mask[index + 1]) continue
    if (isExactDoubleDollar(source, index) && !isEscaped(source, index)) return index
  }
  return -1
}

function isStandaloneDollarFlow(source: string, start: number, close: number): boolean {
  const lineStart = source.lastIndexOf('\n', start - 1) + 1
  const lineEnd = source.indexOf('\n', close + 2)
  const currentLineEnd = lineEnd < 0 ? source.length : lineEnd
  const prefix = source.slice(lineStart, start)
  const suffix = source.slice(close + 2, currentLineEnd)
  const inner = source.slice(start + 2, close)
  return !prefix.trim() && !suffix.trim() && /^(?:\r?\n)/.test(inner) && /(?:\r?\n)$/.test(inner)
}

/**
 * `remark-math` treats same-line `$$...$$` as inline math. Promote an exact
 * double-dollar pair to flow math so equation tags and display layout work
 * consistently with published article markup. Existing flow blocks remain
 * byte-for-byte unchanged.
 */
function normalizeDisplayDollarMath(markdown: string): string {
  if (!markdown.includes('$$')) return markdown

  const mask = protectedMarkdownRegions(markdown)
  let output = ''
  let cursor = 0
  let changed = false

  for (let index = 0; index < markdown.length - 1; index += 1) {
    if (mask[index] || !isExactDoubleDollar(markdown, index) || isEscaped(markdown, index)) continue

    const close = findClosingDoubleDollar(markdown, index + 2, mask)
    if (close < 0) continue
    // A delimiter pair spanning a code region is literal Markdown. Skip its
    // closing token as well so it cannot be mistaken for a new opener.
    if (hasProtectedCharacter(mask, index, close + 2)) {
      index = close + 1
      continue
    }
    if (isStandaloneDollarFlow(markdown, index, close)) {
      index = close + 1
      continue
    }

    output += markdown.slice(cursor, index)
    output += blockReplacement(markdown, index, close, markdown.slice(index + 2, close))
    cursor = close + 2
    index = cursor - 1
    changed = true
  }

  return changed ? output + markdown.slice(cursor) : markdown
}

/**
 * Convert paired `\(...\)` and `\[...\]` delimiters to the delimiters
 * understood by `remark-math` (`$...$` and `$$...$$`).
 *
 * Existing inline dollar math is preserved. Same-line display pairs are
 * promoted to flow blocks; unmatched or code-contained delimiters are
 * returned unchanged so a failed normalization never destroys user content.
 */
export function normalizeMathDelimiters(markdown: string): string {
  if (!markdown) return markdown
  if (!markdown.includes('\\(') && !markdown.includes('\\[')) {
    return protectCurrencyDollars(normalizeDisplayDollarMath(markdown))
  }

  const mask = protectedMarkdownRegions(markdown)
  let output = ''
  let cursor = 0

  for (let index = 0; index < markdown.length - 1; index += 1) {
    if (mask[index] || markdown[index] !== '\\' || isEscaped(markdown, index)) continue

    const opening = markdown[index + 1]
    if (opening !== '(' && opening !== '[') continue

    const closingDelimiter = opening === '(' ? '\\)' : '\\]'
    const close = findClosingDelimiter(markdown, index + 2, closingDelimiter, mask)
    if (close < 0 || hasProtectedCharacter(mask, index, close + 2)) continue

    output += markdown.slice(cursor, index)
    const inner = markdown.slice(index + 2, close)
    if (opening === '(') {
      output += `$${inner}$`
    } else {
      output += blockReplacement(markdown, index, close, inner)
    }
    cursor = close + 2
    index = cursor - 1
  }

  const normalized = cursor === 0 ? markdown : output + markdown.slice(cursor)
  return protectCurrencyDollars(normalizeDisplayDollarMath(normalized))
}

/**
 * Add stable anchors to display equations after KaTeX has created their HAST.
 * The anchor is intentionally metadata-only: explicit TeX tags remain the
 * source of the visible equation number, matching published article markup.
 */
export const rehypeAcademicEquations: Plugin<[], HastRoot> = function academicEquations() {
  function classNames(element: Element): string[] {
    return Array.isArray(element.properties.className) ? element.properties.className.map(String) : []
  }

  function takeDescendantWithClass(parent: Element, className: string): Element | null {
    for (let index = 0; index < parent.children.length; index += 1) {
      const child = parent.children[index]
      if (child.type !== 'element') continue
      if (classNames(child).includes(className)) {
        parent.children.splice(index, 1)
        return child
      }
      const nested = takeDescendantWithClass(child, className)
      if (nested) return nested
    }
    return null
  }

  return function addEquationAnchors(tree) {
    let equationNumber = 0

    visit(tree, 'element', (node) => {
      const names = classNames(node)
      if (!names.includes('katex-display')) return

      equationNumber += 1
      const equationTag = takeDescendantWithClass(node, 'tag')
      const equationContent: Element = {
        type: 'element',
        tagName: 'span',
        properties: {
          className: ['academic-equation-scroll'],
          role: 'region',
          ariaLabel: `公式 ${equationNumber} 内容`,
          tabIndex: 0,
        },
        children: node.children,
      }
      const children: Element[] = [equationContent]
      if (equationTag) {
        children.push({
          type: 'element',
          tagName: 'span',
          properties: {
            className: ['academic-equation-number'],
            ariaHidden: 'true',
          },
          children: equationTag.children,
        })
      }
      node.properties = {
        ...node.properties,
        className: [...names, 'academic-equation', ...(equationTag ? ['academic-equation-numbered'] : [])],
        id: `equation-${equationNumber}`,
        role: 'group',
        ariaLabel: `公式 ${equationNumber}`,
        tabIndex: -1,
      }
      node.children = children
    })
  }
}
