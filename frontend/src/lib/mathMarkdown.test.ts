import { describe, expect, it } from 'vitest'
import { normalizeMathDelimiters } from './mathMarkdown'

describe('normalizeMathDelimiters', () => {
  it('converts inline TeX delimiters for remark-math', () => {
    expect(normalizeMathDelimiters('注意 \\(x_i + 1\\) 的变化。')).toBe('注意 $x_i + 1$ 的变化。')
  })

  it('converts standalone display delimiters and keeps multiline TeX intact', () => {
    const source = ['前文。', '', '\\[', '\\frac{a}{b} = \\sqrt{x}', '\\]', '', '后文。'].join('\n')
    const expected = ['前文。', '', '$$', '\\frac{a}{b} = \\sqrt{x}', '$$', '', '后文。'].join('\n')
    expect(normalizeMathDelimiters(source)).toBe(expected)
  })

  it('promotes same-line double-dollar math to a display flow block', () => {
    expect(normalizeMathDelimiters('$$E=mc^2\\tag{1}$$')).toBe('$$\nE=mc^2\\tag{1}\n$$')
    const existingFlow = '$$\n\\begin{gathered}a=b\\\\c=d\\end{gathered}\n$$'
    expect(normalizeMathDelimiters(existingFlow)).toBe(existingFlow)
  })

  it('supports a display delimiter embedded in prose by promoting it to a flow block', () => {
    expect(normalizeMathDelimiters('前文 \\[x + y\\] 后文')).toBe('前文 \n\n$$\nx + y\n$$\n\n 后文')
  })

  it('does not rewrite fenced, indented, or inline code', () => {
    const source = [
      '```latex',
      '\\(x\\)',
      '\\[y\\]',
      '```',
      '',
      '    \\(z\\)',
      '',
      '`\\(inline\\)` and \\(real\\)',
    ].join('\n')
    const expected = ['```latex', '\\(x\\)', '\\[y\\]', '```', '', '    \\(z\\)', '', '`\\(inline\\)` and $real$'].join(
      '\n',
    )
    expect(normalizeMathDelimiters(source)).toBe(expected)

    const dollarCode = ['```tex', '$$x$$', '```', '', '`$$y$$` and $$z$$'].join('\n')
    const normalizedDollarCode = normalizeMathDelimiters(dollarCode)
    expect(normalizedDollarCode).toContain('```tex\n$$x$$\n```')
    expect(normalizedDollarCode).toContain('`$$y$$`')
    expect(normalizedDollarCode).toContain('$$\nz\n$$')

    const crossingCode = '$$ `literal` $$ and $$z$$'
    const normalizedCrossingCode = normalizeMathDelimiters(crossingCode)
    expect(normalizedCrossingCode).toContain('$$ `literal` $$')
    expect(normalizedCrossingCode).toContain('$$\nz\n$$')
  })

  it('uses Markdown list context instead of a raw four-space heuristic', () => {
    const source = ['1. item', '', '    \\(x + y\\)', '', '    `\\(literal\\)`'].join('\n')
    const expected = ['1. item', '', '    $x + y$', '', '    `\\(literal\\)`'].join('\n')
    expect(normalizeMathDelimiters(source)).toBe(expected)
  })

  it('does not mistake escaped backticks for inline code spans', () => {
    const source = String.raw`\`literal \(x\)\` and \(real\)`
    const expected = String.raw`\`literal $x$\` and $real$`
    expect(normalizeMathDelimiters(source)).toBe(expected)
  })

  it('supports tilde fences and unmatched delimiters without data loss', () => {
    const source = ['~~~', '\\(code\\)', '~~~', '', '未闭合 \\(x'].join('\n')
    expect(normalizeMathDelimiters(source)).toBe(source)
    expect(normalizeMathDelimiters(String.raw`未闭合 $$x`)).toBe(String.raw`未闭合 $$x`)
    expect(normalizeMathDelimiters(String.raw`转义 \$$x$$`)).toBe(String.raw`转义 \$$x$$`)
  })

  it('respects escaped backslashes and preserves existing dollar math', () => {
    const source = String.raw`文字 \\(literal) 与 $\frac{a}{b}$ 以及 \(x\)`
    expect(normalizeMathDelimiters(source)).toBe(String.raw`文字 \\(literal) 与 $\frac{a}{b}$ 以及 $x$`)
  })

  it('protects currency amounts without swallowing adjacent citations or formulas', () => {
    const source =
      'Cost was $1,000,000 [1], $5m [2], and $5[3]. Formula $x[4]$ and $12 USD. ' +
      'Paired math $5 million$, $5 USD$, and $5 per x$ stays math.'

    expect(normalizeMathDelimiters(source)).toBe(
      'Cost was \\$1,000,000 [1], \\$5m [2], and \\$5[3]. Formula $x[4]$ and \\$12 USD. ' +
        'Paired math $5 million$, $5 USD$, and $5 per x$ stays math.',
    )
  })

  it('supports signed, fractional, grouped, abbreviated, and per-unit currency surfaces', () => {
    const source = 'Rates were $5/GB [1], $-10 [2], $.50 [3], $2\u202f000 [4], and $5mm [5].'

    expect(normalizeMathDelimiters(source)).toBe(
      'Rates were \\$5/GB [1], \\$-10 [2], \\$.50 [3], \\$2\u202f000 [4], and \\$5mm [5].',
    )
  })

  it('gives explicit paired math priority over currency-like formula prefixes', () => {
    const source = 'Math $5[1]$ and $5 million [2]$ stays math; currency $5 [3] and $10/GB [4].'

    expect(normalizeMathDelimiters(source)).toBe(
      'Math $5[1]$ and $5 million [2]$ stays math; currency \\$5 [3] and \\$10/GB [4].',
    )
  })

  it('leaves currency-like text inside Markdown code regions byte-for-byte unchanged', () => {
    const source = ['`$5/GB [1]`', '', '```text', '$5 [2]', '```', '', '$5/GB [3]'].join('\n')
    const expected = ['`$5/GB [1]`', '', '```text', '$5 [2]', '```', '', '\\$5/GB [3]'].join('\n')

    expect(normalizeMathDelimiters(source)).toBe(expected)
  })

  it('returns empty and delimiter-free markdown by identity', () => {
    expect(normalizeMathDelimiters('')).toBe('')
    const source = '# 标题\n\n普通文本'
    expect(normalizeMathDelimiters(source)).toBe(source)
  })
})
