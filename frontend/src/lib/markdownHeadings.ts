import GithubSlugger from 'github-slugger'
import type { Heading, Root } from 'mdast'
import { toString } from 'mdast-util-to-string'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import remarkParse from 'remark-parse'
import type { Plugin } from 'unified'
import { unified } from 'unified'
import { visit } from 'unist-util-visit'
import { createAcademicCitationPlugin, type CitationReference } from './citations'
import { normalizeMathDelimiters } from './mathMarkdown'

export type ReviewHeadingDepth = 2 | 3 | 4

export interface ReviewHeading {
  id: string
  title: string
  depth: ReviewHeadingDepth
}

const REVIEW_HEADING_PREFIX = 'review-section-'

function isTocDepth(depth: number): depth is ReviewHeadingDepth {
  return depth >= 2 && depth <= 4
}

export function createReviewHeadingPlugin(capture?: (headings: ReviewHeading[]) => void): Plugin<[], Root> {
  return function reviewHeadingPlugin() {
    return function addReviewHeadingAnchors(tree) {
      const slugger = new GithubSlugger()
      const headings: ReviewHeading[] = []

      visit(tree, 'heading', (node: Heading) => {
        const title = toString(node).trim()
        if (!title) return

        const id = `${REVIEW_HEADING_PREFIX}${slugger.slug(title)}`
        node.data = {
          ...node.data,
          hProperties: {
            ...node.data?.hProperties,
            id,
            tabIndex: -1,
          },
        }

        if (isTocDepth(node.depth)) headings.push({ id, title, depth: node.depth })
      })

      capture?.(headings)
    }
  }
}

export function extractReviewHeadings(markdown: string, references: readonly CitationReference[]): ReviewHeading[] {
  let headings: ReviewHeading[] = []
  const processor = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkMath)
    .use(createAcademicCitationPlugin(references))
    .use(
      createReviewHeadingPlugin((value) => {
        headings = value
      }),
    )

  processor.runSync(processor.parse(normalizeMathDelimiters(markdown)))
  return headings
}
