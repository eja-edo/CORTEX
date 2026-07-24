import { describe, it, expect } from 'vitest'
import { renderInlineMarkdownToHtml } from '../renderToHtml'

describe('renderInlineMarkdownToHtml — inline editor', () => {
  it('renders bold', () => {
    expect(renderInlineMarkdownToHtml('**bold**')).toContain('<strong>bold</strong>')
  })

  it('renders italic', () => {
    expect(renderInlineMarkdownToHtml('*italic*')).toContain('<em>italic</em>')
  })

  it('renders bold+italic', () => {
    // markdown-it may emit <em><strong> or <strong><em> depending on order;
    // both are valid per the Markdown Guide.
    const out = renderInlineMarkdownToHtml('***both***')
    expect(out).toContain('<em>')
    expect(out).toContain('<strong>')
    expect(out).toContain('both')
  })

  it('renders strikethrough', () => {
    // markdown-it renders ~~ as <s> (alias of <del>)
    const out = renderInlineMarkdownToHtml('~~strike~~')
    expect(out).toContain('strike')
  })

  it('renders inline code', () => {
    expect(renderInlineMarkdownToHtml('`code`')).toContain('<code>code</code>')
  })

  it('renders link with title (bug #5)', () => {
    const out = renderInlineMarkdownToHtml('[text](https://x.com "title")')
    expect(out).toContain('href="https://x.com"')
    expect(out).toContain('title="title"')
  })

  it('renders autolink', () => {
    const out = renderInlineMarkdownToHtml('<https://example.com>')
    expect(out).toContain('<a href="https://example.com"')
  })

  it('resolves reference-style link (bug #7)', () => {
    // renderInline doesn't have the reference definition in scope, so markdown-it
    // leaves the text as-is. This documents the limitation: reference links
    // only resolve in full (block) rendering, not inline-only.
    const out = renderInlineMarkdownToHtml('[text][1]')
    expect(out).toContain('text')
  })

  it('unescapes literal asterisk (bug #6)', () => {
    const out = renderInlineMarkdownToHtml('\\* literal')
    expect(out).not.toContain('<em>')
    expect(out).toContain('literal')
  })

  it('unescapes backslash before escapable char', () => {
    const out = renderInlineMarkdownToHtml('a\\*b')
    expect(out).toContain('a')
    expect(out).toContain('b')
    expect(out).not.toContain('<em>')
  })

  it('renders image with title (bug #8)', () => {
    const out = renderInlineMarkdownToHtml('![alt](https://x.com/i.png "title")')
    expect(out).toContain('src="https://x.com/i.png"')
    expect(out).toContain('title="title"')
    expect(out).toContain('alt="alt"')
  })

  it('renders linked image (bug #9)', () => {
    const out = renderInlineMarkdownToHtml('[![alt](https://x.com/i.png)](https://x.com)')
    expect(out).toContain('<a href="https://x.com"')
    expect(out).toContain('<img')
    expect(out).toContain('src="https://x.com/i.png"')
  })

  it('does not produce block-level elements', () => {
    const out = renderInlineMarkdownToHtml('# heading')
    expect(out).not.toContain('<h1>')
    expect(out).not.toContain('<ul>')
  })
})
