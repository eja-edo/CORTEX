import { describe, it, expect } from 'vitest'
import { renderMarkdownToSanitizedHtml, toggleTaskInMarkdown } from '../renderToHtml'

describe('renderMarkdownToSanitizedHtml — basic syntax (markdownguide.org)', () => {
  describe('headings', () => {
    it('renders ATX headings h1-h6', () => {
      const out = renderMarkdownToSanitizedHtml(
        '# H1\n## H2\n### H3\n#### H4\n##### H5\n###### H6'
      )
      expect(out).toContain('<h1>H1</h1>')
      expect(out).toContain('<h2>H2</h2>')
      expect(out).toContain('<h3>H3</h3>')
      expect(out).toContain('<h4>H4</h4>')
      expect(out).toContain('<h5>H5</h5>')
      expect(out).toContain('<h6>H6</h6>')
    })

    it('renders setext heading h1 (===)', () => {
      const out = renderMarkdownToSanitizedHtml('Title\n===\n')
      expect(out).toContain('<h1>Title</h1>')
    })

    it('renders setext heading h2 (---)', () => {
      const out = renderMarkdownToSanitizedHtml('Sub\n---\n')
      expect(out).toContain('<h2>Sub</h2>')
    })

    it('requires a space after # (best practice)', () => {
      const out = renderMarkdownToSanitizedHtml('#NoSpace')
      expect(out).not.toContain('<h1>NoSpace</h1>')
    })
  })

  describe('paragraphs & line breaks', () => {
    it('separates paragraphs with blank lines', () => {
      const out = renderMarkdownToSanitizedHtml('First.\n\nSecond.')
      expect(out).toContain('<p>First.</p>')
      expect(out).toContain('<p>Second.</p>')
    })

    it('renders a hard line break with two trailing spaces', () => {
      const out = renderMarkdownToSanitizedHtml('line1  \nline2')
      expect(out).toContain('<br')
      expect(out).toContain('line1')
      expect(out).toContain('line2')
    })
  })

  describe('emphasis', () => {
    it('renders bold **text** and __text__', () => {
      const out = renderMarkdownToSanitizedHtml('I love **bold text**.')
      expect(out).toContain('<strong>bold text</strong>')
    })

    it('renders italic *text* and _text_', () => {
      const out = renderMarkdownToSanitizedHtml('italic *cat* here.')
      expect(out).toContain('<em>cat</em>')
    })

    it('renders bold+italic ***text***', () => {
      const out = renderMarkdownToSanitizedHtml('This is ***really important***.')
      expect(out).toContain('<em><strong>really important</strong></em>')
    })

    it('bolds the middle of a word with asterisks', () => {
      const out = renderMarkdownToSanitizedHtml('Love**is**bold')
      expect(out).toContain('Love<strong>is</strong>bold')
    })
  })

  describe('blockquotes', () => {
    it('renders a single blockquote', () => {
      const out = renderMarkdownToSanitizedHtml('> Dorothy followed her.')
      expect(out).toContain('<blockquote>')
      expect(out).toContain('Dorothy followed her.')
    })

    it('renders multi-paragraph blockquote', () => {
      const out = renderMarkdownToSanitizedHtml('> Para 1.\n>\n> Para 2.')
      expect(out).toContain('<blockquote>')
      expect(out).toContain('Para 1.')
      expect(out).toContain('Para 2.')
    })

    it('renders nested blockquote', () => {
      const out = renderMarkdownToSanitizedHtml('> Outer\n>\n>> Inner')
      expect(out).toContain('<blockquote>')
      expect(out).toContain('Inner')
    })

    it('renders blockquote with heading + list + inline', () => {
      const out = renderMarkdownToSanitizedHtml(
        '> #### Title\n>\n> - item 1\n> - item 2\n>\n> *italic* and **bold**.'
      )
      expect(out).toContain('<h4>Title</h4>')
      expect(out).toContain('<ul>')
      expect(out).toContain('<strong>bold</strong>')
    })
  })

  describe('lists', () => {
    it('renders unordered list with -', () => {
      const out = renderMarkdownToSanitizedHtml('- a\n- b\n- c')
      expect(out).toContain('<ul>')
      expect(out).toContain('<li>a</li>')
      expect(out).toContain('<li>b</li>')
      expect(out).toContain('<li>c</li>')
    })

    it('renders ordered list', () => {
      const out = renderMarkdownToSanitizedHtml('1. First\n2. Second')
      expect(out).toContain('<ol>')
      expect(out).toContain('<li>First</li>')
    })

    it('renders nested list', () => {
      const out = renderMarkdownToSanitizedHtml('- a\n  - a1\n  - a2\n- b')
      expect(out).toContain('<ul>')
      expect(out).toContain('a1')
      expect(out).toContain('a2')
    })

    it('renders mixed nesting (ordered inside unordered)', () => {
      const out = renderMarkdownToSanitizedHtml('1. First\n2. Second\n    1. Indented\n3. Third')
      expect(out).toContain('<ol>')
      expect(out).toContain('Indented')
    })

    it('renders loose list item with paragraph continuation', () => {
      const out = renderMarkdownToSanitizedHtml(
        '- First item\n\n  Second paragraph in same item.\n- Second item'
      )
      expect(out).toContain('Second paragraph in same item.')
      expect(out).toContain('<p>Second paragraph in same item.</p>')
    })

    it('renders task list (GFM extension)', () => {
      const out = renderMarkdownToSanitizedHtml('- [ ] todo\n- [x] done')
      expect(out).toContain('todo')
      expect(out).toContain('done')
      expect(out).toContain('type="checkbox"')
      expect(out).toContain('disabled')
      expect(out).toContain('class="task-list-item"')
      // checked item
      expect(out.match(/checked/g)).toHaveLength(1)
    })

    it('renders interactive task list without disabled', () => {
      const out = renderMarkdownToSanitizedHtml('- [ ] todo\n- [x] done', { interactiveTasks: true })
      expect(out).toContain('data-task-index="0"')
      expect(out).toContain('data-task-index="1"')
      expect(out).not.toContain('disabled')
      expect(out).toContain('class="task-list-item"')
      expect(out.match(/checked/g)).toHaveLength(1)
    })

    it('supports bare images in interactive mode', () => {
      const out = renderMarkdownToSanitizedHtml('- [ ] ![img](x.png)', { interactiveTasks: true })
      expect(out).not.toContain('disabled')
    })
  })

  describe('toggleTaskInMarkdown', () => {
    it('toggles unchecked to checked', () => {
      const result = toggleTaskInMarkdown('- [ ] a\n- [x] b\n- [ ] c', 0)
      expect(result).toBe('- [x] a\n- [x] b\n- [ ] c')
    })

    it('toggles checked to unchecked', () => {
      const result = toggleTaskInMarkdown('- [ ] a\n- [x] b\n- [ ] c', 1)
      expect(result).toBe('- [ ] a\n- [ ] b\n- [ ] c')
    })

    it('toggles middle item', () => {
      const result = toggleTaskInMarkdown('- [ ] a\n- [x] b\n- [ ] c', 2)
      expect(result).toBe('- [ ] a\n- [x] b\n- [x] c')
    })

    it('handles ordered list markers', () => {
      const result = toggleTaskInMarkdown('1. [ ] first\n2. [x] second', 0)
      expect(result).toBe('1. [x] first\n2. [x] second')
    })

    it('handles asterisk and plus markers', () => {
      expect(toggleTaskInMarkdown('* [ ] item\n+ [x] other', 0)).toBe('* [x] item\n+ [x] other')
    })

    it('returns same string when index out of range', () => {
      const md = '- [ ] a\n- [x] b'
      expect(toggleTaskInMarkdown(md, 99)).toBe(md)
    })

    it('returns same string when no tasks exist', () => {
      const md = '- just a regular item'
      expect(toggleTaskInMarkdown(md, 0)).toBe(md)
    })

    it('handles indented task lists', () => {
      const result = toggleTaskInMarkdown('- [ ] a\n  - [x] b\n    - [ ] c', 2)
      expect(result).toBe('- [ ] a\n  - [x] b\n    - [x] c')
    })

    it('preserves [X] uppercase when toggling back', () => {
      const result = toggleTaskInMarkdown('- [X] done', 0)
      expect(result).toBe('- [ ] done')
    })

    it('toggles [X] to unchecked', () => {
      const result = toggleTaskInMarkdown('- [X] done\n- [ ] new', 0)
      expect(result).toBe('- [ ] done\n- [ ] new')
    })
  })

  describe('code', () => {
    it('renders inline code', () => {
      const out = renderMarkdownToSanitizedHtml('Use `nano`.')
      expect(out).toContain('<code>nano</code>')
    })

    it('renders fenced code block', () => {
      const out = renderMarkdownToSanitizedHtml('```\ncode block\n```')
      expect(out).toContain('<pre>')
      expect(out).toContain('<code>')
      expect(out).toContain('code block')
    })

    it('renders indented code block', () => {
      const out = renderMarkdownToSanitizedHtml('    <html>\n      </html>')
      expect(out).toContain('<pre>')
      expect(out).toContain('<code>')
      // html:false escapes the literal angle brackets inside code
      expect(out).toContain('&lt;html&gt;')
    })
  })

  describe('horizontal rule', () => {
    it('renders ---', () => {
      expect(renderMarkdownToSanitizedHtml('---\n')).toContain('<hr')
    })
    it('renders ***', () => {
      expect(renderMarkdownToSanitizedHtml('***\n')).toContain('<hr')
    })
    it('renders ___', () => {
      expect(renderMarkdownToSanitizedHtml('___\n')).toContain('<hr')
    })
  })

  describe('links', () => {
    it('renders inline link', () => {
      const out = renderMarkdownToSanitizedHtml('[Duck Duck Go](https://duckduckgo.com)')
      expect(out).toContain('<a href="https://duckduckgo.com"')
      expect(out).toContain('Duck Duck Go')
    })

    it('renders link with title', () => {
      const out = renderMarkdownToSanitizedHtml(
        '[Duck Duck Go](https://duckduckgo.com "The best search engine")'
      )
      expect(out).toContain('title="The best search engine"')
    })

    it('renders autolink', () => {
      const out = renderMarkdownToSanitizedHtml('<https://www.markdownguide.org>')
      expect(out).toContain('<a href="https://www.markdownguide.org"')
    })

    it('renders reference-style link', () => {
      const out = renderMarkdownToSanitizedHtml('[text][1]\n\n[1]: https://example.com')
      expect(out).toContain('<a href="https://example.com"')
      expect(out).toContain('text')
    })

    it('renders formatted link (bold inside link)', () => {
      const out = renderMarkdownToSanitizedHtml('[**Bold link**](https://eff.org)')
      expect(out).toContain('<strong>Bold link</strong>')
    })
  })

  describe('images', () => {
    it('renders image', () => {
      const out = renderMarkdownToSanitizedHtml('![alt text](https://example.com/x.png)')
      expect(out).toContain('<img')
      expect(out).toContain('src="https://example.com/x.png"')
      expect(out).toContain('alt="alt text"')
    })

    it('renders image with title', () => {
      const out = renderMarkdownToSanitizedHtml('![alt](https://e.com/x.jpg "Title")')
      expect(out).toContain('title="Title"')
    })

    it('renders linked image', () => {
      const out = renderMarkdownToSanitizedHtml(
        '[![alt](https://e.com/x.jpg)](https://e.com)'
      )
      expect(out).toContain('<a href="https://e.com"')
      expect(out).toContain('<img')
      expect(out).toContain('src="https://e.com/x.jpg"')
    })
  })

  describe('escaping', () => {
    it('renders literal asterisk', () => {
      const out = renderMarkdownToSanitizedHtml('\\* literal')
      expect(out).toContain('literal')
      expect(out).not.toContain('<em>')
    })

    it('renders escaped list marker', () => {
      const out = renderMarkdownToSanitizedHtml('1968\\. A great year!')
      expect(out).toContain('1968.')
      expect(out).not.toContain('<ol>')
    })
  })

  describe('sanitization', () => {
    it('strips script tags', () => {
      const out = renderMarkdownToSanitizedHtml('<script>alert(1)</script>')
      expect(out).not.toContain('<script>')
      expect(out).not.toContain('</script>')
    })

    it('strips raw html when html:false', () => {
      const out = renderMarkdownToSanitizedHtml('<p>raw</p>')
      expect(out).not.toContain('<p>raw</p>')
    })
  })
})
