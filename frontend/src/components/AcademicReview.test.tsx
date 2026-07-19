import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AcademicReview } from './AcademicReview'
import type { CitationReference } from '../lib/citations'

const DEFAULT_INNER_WIDTH = window.innerWidth

function referencesThrough(limit: number): CitationReference[] {
  return Array.from({ length: limit }, (_, index) => ({
    new_number: index + 1,
    original_number: index + 1,
    paper_id: `paper-${index + 1}`,
    title: `Structured source ${index + 1}`,
    authors: `Author ${index + 1}, Collaborator ${index + 1}`,
    venue: 'Journal of Tests',
    year: 2026,
  }))
}

afterEach(() => {
  window.history.replaceState(null, '', '/')
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: DEFAULT_INNER_WIDTH })
  vi.unstubAllGlobals()
})

describe('AcademicReview table of contents', () => {
  it('normal: renders nested headings and moves focus to the selected section', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1280 })
    const user = userEvent.setup()
    render(
      <AcademicReview
        markdown={
          '# Review title\n\n## \u6458\u8981\n\n### \u65b9\u6cd5 *\u6bd4\u8f83*\n\n#### \u8fb9\u754c `Case`\n\n## \u7ed3\u8bba'
        }
        references={referencesThrough(1)}
      />,
    )

    const toc = screen.getByRole('navigation', { name: '\u6587\u7ae0\u76ee\u5f55' })
    expect(within(toc).queryByRole('link', { name: 'Review title' })).not.toBeInTheDocument()

    const summaryLink = within(toc).getByRole('link', { name: '\u6458\u8981' })
    const methodLink = within(toc).getByRole('link', { name: '\u65b9\u6cd5 \u6bd4\u8f83' })
    const edgeLink = within(toc).getByRole('link', { name: '\u8fb9\u754c Case' })
    const bibliographyLink = within(toc).getByRole('link', { name: '\u53c2\u8003\u6587\u732e' })

    expect(summaryLink).toHaveAttribute('href', '#review-section-\u6458\u8981')
    expect(methodLink.closest('li')).toHaveClass('review-toc-depth-3')
    expect(edgeLink.closest('li')).toHaveClass('review-toc-depth-4')
    expect(bibliographyLink).toHaveAttribute('href', '#academic-bibliography-title')
    expect(document.getElementById('review-section-\u65b9\u6cd5-\u6bd4\u8f83')).toBeInTheDocument()

    await user.click(methodLink)
    expect(window.location.hash).toBe('#review-section-%E6%96%B9%E6%B3%95-%E6%AF%94%E8%BE%83')
    expect(methodLink).toHaveAttribute('aria-current', 'location')
    expect(document.activeElement).toBe(document.getElementById('review-section-\u65b9\u6cd5-\u6bd4\u8f83'))
    expect(screen.getByRole('button', { name: '\u76ee\u5f55' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('edge: creates unique anchors for duplicate headings and omits an empty directory', () => {
    const { rerender } = render(
      <AcademicReview
        markdown={'# Title\n\n## \u91cd\u590d\u6807\u9898\n\n## \u91cd\u590d\u6807\u9898'}
        references={[]}
      />,
    )

    const duplicateLinks = within(screen.getByRole('navigation', { name: '\u6587\u7ae0\u76ee\u5f55' })).getAllByRole(
      'link',
      { name: '\u91cd\u590d\u6807\u9898' },
    )
    expect(duplicateLinks).toHaveLength(2)
    expect(duplicateLinks[0]).toHaveAttribute('href', '#review-section-\u91cd\u590d\u6807\u9898')
    expect(duplicateLinks[1]).toHaveAttribute('href', '#review-section-\u91cd\u590d\u6807\u9898-1')

    rerender(<AcademicReview markdown={'# Title only\n\nBody'} references={[]} />)
    expect(screen.queryByRole('navigation', { name: '\u6587\u7ae0\u76ee\u5f55' })).not.toBeInTheDocument()
  })

  it('mobile: collapses the directory after selecting a section', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    const user = userEvent.setup()
    render(
      <AcademicReview markdown={'## \u7b2c\u4e00\u8282\n\nBody\n\n## \u7b2c\u4e8c\u8282\n\nBody'} references={[]} />,
    )

    const toggle = screen.getByRole('button', { name: '\u76ee\u5f55' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    await user.click(screen.getByRole('link', { name: '\u7b2c\u4e8c\u8282' }))
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('responsive: keeps the directory in the side rail when the desktop sidebar reduces reading space', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1280 })
    vi.stubGlobal(
      'ResizeObserver',
      class ResizeObserverMock {
        private readonly callback: ResizeObserverCallback

        constructor(callback: ResizeObserverCallback) {
          this.callback = callback
        }

        observe() {
          this.callback([{ contentRect: { width: 900 } } as ResizeObserverEntry], this as unknown as ResizeObserver)
        }

        disconnect() {}

        unobserve() {}
      },
    )

    render(<AcademicReview markdown={'## Narrow article\n\nBody'} references={[]} />)

    expect(screen.getByRole('button', { name: '\u76ee\u5f55' })).toHaveAttribute('aria-expanded', 'true')
    expect(document.querySelector('.academic-review-layout')).toHaveAttribute('data-layout', 'wide')
  })

  it('regression: keeps the nearest active heading when observer callbacks arrive separately', () => {
    let callback: IntersectionObserverCallback | undefined
    const observed: Element[] = []
    vi.stubGlobal(
      'IntersectionObserver',
      class IntersectionObserverMock {
        constructor(nextCallback: IntersectionObserverCallback) {
          callback = nextCallback
        }

        observe(target: Element) {
          observed.push(target)
        }

        disconnect() {}

        unobserve() {}
      },
    )

    render(<AcademicReview markdown={'## First section\n\nBody\n\n## Second section\n\nBody'} references={[]} />)
    const first = document.getElementById('review-section-first-section')
    const second = document.getElementById('review-section-second-section')
    expect(first).toBe(observed[0])
    expect(second).toBe(observed[1])
    expect(callback).toBeDefined()

    act(() => {
      callback?.(
        [
          {
            target: first as Element,
            isIntersecting: true,
            boundingClientRect: { top: 100 },
          } as IntersectionObserverEntry,
        ],
        {} as IntersectionObserver,
      )
    })
    expect(screen.getByRole('link', { name: 'First section' })).toHaveAttribute('aria-current', 'location')

    act(() => {
      callback?.(
        [
          {
            target: second as Element,
            isIntersecting: true,
            boundingClientRect: { top: 300 },
          } as IntersectionObserverEntry,
        ],
        {} as IntersectionObserver,
      )
    })
    expect(screen.getByRole('link', { name: 'First section' })).toHaveAttribute('aria-current', 'location')

    act(() => {
      callback?.(
        [
          {
            target: first as Element,
            isIntersecting: false,
            boundingClientRect: { top: -100 },
          } as IntersectionObserverEntry,
        ],
        {} as IntersectionObserver,
      )
    })
    expect(screen.getByRole('link', { name: 'Second section' })).toHaveAttribute('aria-current', 'location')
  })
})

describe('AcademicReview citations', () => {
  it('normal: links adjacent, grouped, and ranged citations to structured bibliography rows', () => {
    render(
      <AcademicReview
        markdown={
          '\u72ec\u7acb\u8bc1\u636e[1][2]\uff0c\u8054\u5408\u8bc1\u636e[14,15]\uff0c\u4ee5\u53ca\u8bc1\u636e\u533a\u95f4[12-17]\u3002' +
          '\u540c\u65f6\u652f\u6301[1;2]\u3002'
        }
        references={referencesThrough(17)}
      />,
    )

    for (const number of [1, 2, 12, 13, 14, 15, 16, 17]) {
      const links = screen.getAllByRole('link', { name: `\u67e5\u770b\u53c2\u8003\u6587\u732e ${number}` })
      expect(links[0]).toHaveAttribute('href', `#reference-${number}`)
      expect(links[0]).toHaveAttribute('id', `citation-${number}-1`)
      expect(document.getElementById(`reference-${number}`)).toBeInTheDocument()
    }
    expect(screen.getByText(/证据区间/, { selector: 'p' })).toHaveTextContent('证据区间[12-17]')

    const bibliography = screen.getByRole('list', { name: '\u53c2\u8003\u6587\u732e' })
    expect(within(bibliography).getAllByRole('listitem')).toHaveLength(17)
    expect(
      within(bibliography).getByRole('link', {
        name: '\u8fd4\u56de\u6b63\u6587\u4e2d\u53c2\u8003\u6587\u732e 1 \u7684\u9996\u6b21\u5f15\u7528',
      }),
    ).toHaveAttribute('href', '#citation-1-1')
    for (const number of [13, 16]) {
      expect(
        within(bibliography).getByRole('link', {
          name: `\u8fd4\u56de\u6b63\u6587\u4e2d\u53c2\u8003\u6587\u732e ${number} \u7684\u9996\u6b21\u5f15\u7528`,
        }),
      ).toHaveAttribute('href', `#citation-${number}-1`)
      const rangeAnchor = screen.getByRole('link', { name: `\u67e5\u770b\u53c2\u8003\u6587\u732e ${number}` })
      expect(rangeAnchor).toHaveClass('citation-range-anchor')
      expect(rangeAnchor).toHaveAttribute('tabindex', '-1')
    }
    const hiddenRangeAnchor = screen.getByRole('link', { name: '查看参考文献 13' })
    act(() => {
      window.history.pushState(null, '', '#citation-13-1')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    expect(document.activeElement).toBe(hiddenRangeAnchor)
  })

  it('edge: leaves unknown and year-like brackets untouched and preserves an embedded list without structured data', () => {
    const { rerender } = render(
      <AcademicReview
        markdown={'\u672a\u77e5\u5f15\u7528[99]\uff0c\u5e74\u4efd[2024]\u3002'}
        references={referencesThrough(2)}
      />,
    )

    expect(screen.queryByRole('link', { name: '\u67e5\u770b\u53c2\u8003\u6587\u732e 99' })).not.toBeInTheDocument()
    expect(screen.getByText(/\u672a\u77e5\u5f15\u7528\[99\].*\u5e74\u4efd\[2024\]/)).toBeInTheDocument()

    rerender(<AcademicReview markdown={'## References\n\n[1] Only embedded source'} references={[]} />)
    expect(screen.getByRole('heading', { name: 'References' })).toBeInTheDocument()
    expect(screen.getByText('[1] Only embedded source')).toBeInTheDocument()
  })

  it('regression: leaves bracket expressions inside code and math untouched', () => {
    const { container } = render(
      <AcademicReview
        markdown={[
          'Inline math $A[1,2]$ and code `refs[1]`.',
          '',
          String.raw`\[`,
          'B[1,2]',
          String.raw`\]`,
          '',
          'Visible evidence [1][2].',
        ].join('\n')}
        references={referencesThrough(2)}
      />,
    )

    expect(screen.getAllByRole('link', { name: '\u67e5\u770b\u53c2\u8003\u6587\u732e 1' })).toHaveLength(1)
    expect(screen.getAllByRole('link', { name: '\u67e5\u770b\u53c2\u8003\u6587\u732e 2' })).toHaveLength(1)
    expect(screen.getByText('refs[1]', { selector: 'code' })).toBeInTheDocument()
    expect(container.querySelectorAll('.katex')).toHaveLength(2)
  })

  it('regression: renders list-continuation math without turning matrix indices into citations', () => {
    const { container } = render(
      <AcademicReview
        markdown={['1. Metric', '', '    \\(A[1,2]\\)', '', 'Visible evidence [1].'].join('\n')}
        references={referencesThrough(2)}
      />,
    )

    expect(container.querySelectorAll('.katex')).toHaveLength(1)
    expect(screen.getAllByRole('link', { name: '查看参考文献 1' })).toHaveLength(1)
    expect(screen.queryByRole('link', { name: '查看参考文献 2' })).not.toBeInTheDocument()
  })

  it('regression: restores focus for citation hashes during history navigation', () => {
    render(<AcademicReview markdown={'Visible evidence [1], repeated [1].'} references={referencesThrough(1)} />)

    const citationLinks = screen.getAllByRole('link', { name: '\u67e5\u770b\u53c2\u8003\u6587\u732e 1' })
    expect(citationLinks[0]).toHaveAttribute('id', 'citation-1-1')
    expect(citationLinks[1]).toHaveAttribute('id', 'citation-1-2')

    act(() => {
      window.history.pushState(null, '', '#reference-1')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    expect(document.activeElement).toBe(document.getElementById('reference-1'))

    act(() => {
      window.history.pushState(null, '', '#citation-1-1')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    expect(document.activeElement).toBe(document.getElementById('citation-1-1'))
  })

  it('navigation: leaves modified and non-primary clicks to native browser behavior', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1280 })
    render(<AcademicReview markdown={'## First section\n\nBody'} references={[]} />)
    const link = screen.getByRole('link', { name: 'First section' })
    const pushState = vi.spyOn(window.history, 'pushState')

    for (const modifier of ['ctrlKey', 'metaKey', 'shiftKey', 'altKey'] as const) {
      const event = new MouseEvent('click', { bubbles: true, cancelable: true, [modifier]: true })
      link.dispatchEvent(event)
      expect(event.defaultPrevented).toBe(false)
    }
    const middleClick = new MouseEvent('click', { bubbles: true, cancelable: true, button: 1 })
    link.dispatchEvent(middleClick)
    expect(middleClick.defaultPrevented).toBe(false)
    expect(pushState).not.toHaveBeenCalled()
  })

  it('regression: removes the duplicate markdown bibliography and adds the first author to a leading proposal citation', () => {
    const references: CitationReference[] = [
      {
        new_number: 7,
        paper_id: 'paper-7',
        title: 'Structured canonical source',
        authors: [{ name: '\u738b\u4f1f' }, { name: '\u674e\u660e' }],
        doi: 'https://doi.org/10.1000/test.7',
      },
    ]
    render(
      <AcademicReview
        markdown={
          '[7]\u63d0\u51fa\u65b0\u65b9\u6cd5\u3002\n\n\u5728\u76f8\u5173\u4efb\u52a1\u4e2d\uff0c[7]\u63d0\u51fa\u6539\u8fdb\u65b9\u6cd5\u3002\n\n\u738b\u4f1f[7]\u63d0\u51fa\u540e\u7eed\u6539\u8fdb\u3002\n\n## References\n\n[7] stale embedded source\n\n## Appendix\n\nAppendix content survives structured bibliography replacement.'
        }
        references={references}
      />,
    )

    const paragraphs = screen.getAllByText(/\u738b\u4f1f.*\u63d0\u51fa/, { selector: 'p' })
    expect(paragraphs[0]).toHaveTextContent('\u738b\u4f1f[7]\u63d0\u51fa\u65b0\u65b9\u6cd5\u3002')
    expect(paragraphs[1]).toHaveTextContent(
      '\u5728\u76f8\u5173\u4efb\u52a1\u4e2d\uff0c\u738b\u4f1f[7]\u63d0\u51fa\u6539\u8fdb\u65b9\u6cd5\u3002',
    )
    expect(paragraphs[2]).toHaveTextContent('\u738b\u4f1f[7]\u63d0\u51fa\u540e\u7eed\u6539\u8fdb\u3002')
    expect(paragraphs[2]).not.toHaveTextContent('\u738b\u4f1f\u738b\u4f1f')
    expect(screen.queryByText(/stale embedded source/)).not.toBeInTheDocument()
    expect(screen.getByText('Appendix content survives structured bibliography replacement.')).toBeInTheDocument()
    expect(screen.getByText('Structured canonical source')).toBeInTheDocument()
    const toc = screen.getByRole('navigation', { name: '\u6587\u7ae0\u76ee\u5f55' })
    expect(within(toc).getAllByRole('link', { name: '\u53c2\u8003\u6587\u732e' })).toHaveLength(1)
    expect(screen.getByRole('link', { name: '\u6253\u5f00\u53c2\u8003\u6587\u732e 7 \u7684 DOI' })).toHaveAttribute(
      'href',
      'https://doi.org/10.1000/test.7',
    )
  })

  it('edge: accepts string reference numbers, Chinese separators, and comma-less author lists', () => {
    const references: CitationReference[] = [
      { new_number: '7', paper_id: 'paper-7', title: 'Source seven', authors: '王伟,李明' },
      { new_number: '8', paper_id: 'paper-8', title: 'Source eight', authors: [{ given: 'Zhao', family: 'Qiang' }] },
    ]
    render(<AcademicReview markdown={'[7；8]提出了联合方法。'} references={references} />)

    expect(screen.getByText(/王伟.*提出了联合方法/, { selector: 'p' })).toHaveTextContent('王伟[7；8]提出了联合方法。')
    expect(screen.getByRole('link', { name: '查看参考文献 7' })).toHaveAttribute('href', '#reference-7')
    expect(screen.getByRole('link', { name: '查看参考文献 8' })).toHaveAttribute('href', '#reference-8')
    expect(screen.getByText(/Zhao Qiang/)).toBeInTheDocument()
  })

  it('failure: rejects unsafe structured reference URLs while keeping HTTPS links', () => {
    const { rerender } = render(
      <AcademicReview
        markdown={'Evidence [1].'}
        references={[{ new_number: 1, paper_id: 'paper-1', title: 'Unsafe', url: 'javascript:alert(1)' }]}
      />,
    )
    expect(screen.queryByRole('link', { name: '打开参考文献 1 的原文' })).not.toBeInTheDocument()

    rerender(
      <AcademicReview
        markdown={'Evidence [1].'}
        references={[{ new_number: 1, paper_id: 'paper-1', title: 'Safe', url: 'https://example.com/paper/1' }]}
      />,
    )
    expect(screen.getByRole('link', { name: '打开参考文献 1 的原文' })).toHaveAttribute(
      'href',
      'https://example.com/paper/1',
    )
  })

  it('edge: does not expand descending citation ranges', () => {
    render(<AcademicReview markdown={'Reversed range [3-1].'} references={referencesThrough(3)} />)
    expect(screen.queryByRole('link', { name: '查看参考文献 2' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看参考文献 3' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看参考文献 1' })).toBeInTheDocument()
  })
})

describe('AcademicReview mathematics', () => {
  it('renders inline, display, and legacy TeX delimiters with stable equation anchors', () => {
    const { container } = render(
      <AcademicReview
        markdown={String.raw`Inline $x_i + 1$ and \(a+b\).

$$E = mc^2 \tag{1}$$

\[
\begin{gathered}
\frac{a}{b} = \sqrt{x}
\end{gathered}
\]`}
        references={[]}
      />,
    )

    expect(container.querySelectorAll('.katex')).toHaveLength(4)
    expect(container.querySelector('#equation-1')).toHaveClass('academic-equation')
    expect(container.querySelector('#equation-2')).toHaveClass('academic-equation')
    expect(container.querySelector('#equation-1 .academic-equation-scroll')).toHaveAttribute(
      'aria-label',
      '公式 1 内容',
    )
    expect(container.querySelector('#equation-1 .academic-equation-number')).toHaveTextContent('(1)')
    expect(container.querySelectorAll('.katex-mathml')).toHaveLength(4)
  })

  it('keeps invalid TeX visible without breaking the article render', () => {
    const { container } = render(
      <AcademicReview markdown={'An invalid formula $\\missingcommand{x}$ remains visible.'} />,
    )

    expect(container.querySelector('.katex')).toBeInTheDocument()
    expect(container.querySelector('mstyle[mathcolor]')).not.toBeNull()
    expect(container.textContent).toContain('An invalid formula')
  })
})

describe('AcademicReview currency and rich content', () => {
  it('keeps currency prose and links citations outside inline math', () => {
    render(
      <AcademicReview
        markdown={'Cost was $1,000,000 [1], $5m [2], and $5[3]. Formula $x[99]$ and visible [4].'}
        references={referencesThrough(4)}
      />,
    )

    expect(screen.getByText(/Cost was \$1,000,000/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看参考文献 1' })).toHaveAttribute('href', '#reference-1')
    expect(screen.getByRole('link', { name: '查看参考文献 2' })).toHaveAttribute('href', '#reference-2')
    expect(screen.getByRole('link', { name: '查看参考文献 3' })).toHaveAttribute('href', '#reference-3')
    expect(screen.getByRole('link', { name: '查看参考文献 4' })).toHaveAttribute('href', '#reference-4')
    expect(screen.queryByRole('link', { name: '查看参考文献 99' })).not.toBeInTheDocument()
  })

  it('regression: separates per-unit currency citations from numeric formulas', () => {
    const { container } = render(
      <AcademicReview
        markdown={'Rates were $5/GB [1] and $10m [2]. Formula $5[99]$ and $5 million [98]$; evidence [3 4].'}
        references={referencesThrough(4)}
      />,
    )

    for (const number of [1, 2, 3, 4]) {
      expect(screen.getByRole('link', { name: `查看参考文献 ${number}` })).toHaveAttribute(
        'href',
        `#reference-${number}`,
      )
    }
    expect(screen.queryByRole('link', { name: '查看参考文献 98' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '查看参考文献 99' })).not.toBeInTheDocument()
    expect(container.querySelectorAll('.katex')).toHaveLength(2)
  })

  it('wraps data tables for narrow screens and applies safe external media defaults', () => {
    render(
      <AcademicReview
        markdown={[
          '| Model | Score |',
          '| --- | ---: |',
          '| Baseline | 0.82 |',
          '',
          '[Open source](https://example.com/paper)',
          '',
          '![Result plot](https://example.com/plot.png)',
          '',
          '![](https://example.com/untitled.png)',
        ].join('\n')}
      />,
    )

    const tableRegion = screen.getByRole('region', { name: '\u6587\u7ae0\u6570\u636e\u8868' })
    expect(within(tableRegion).getByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open source' })).toHaveAttribute('target', '_blank')
    expect(screen.getByRole('link', { name: 'Open source' })).toHaveAttribute('rel', 'noreferrer noopener')
    expect(screen.getByRole('img', { name: 'Result plot' })).toHaveAttribute('loading', 'lazy')
    expect(screen.getByRole('img', { name: 'Result plot' })).toHaveAttribute('decoding', 'async')
    expect(screen.getByRole('img', { name: '\u6587\u7ae0\u63d2\u56fe' })).toBeInTheDocument()
  })
})
