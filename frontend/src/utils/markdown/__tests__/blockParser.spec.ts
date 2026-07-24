import { describe, it, expect } from 'vitest'
import { parseMarkdownToBlocks } from '../blockParser'

describe('parseMarkdownToBlocks — block model', () => {
  describe('headings', () => {
    it('parses h1-h6', () => {
      const blocks = parseMarkdownToBlocks('# A\n## B\n### C\n#### D\n##### E\n###### F')
      expect(blocks).toHaveLength(6)
      expect(blocks.map(b => b.type)).toEqual([
        'heading_1', 'heading_2', 'heading_3',
        'heading_4', 'heading_5', 'heading_6',
      ])
      expect(blocks[0].content).toBe('A')
    })

    it('parses setext h1 (bug #2)', () => {
      const blocks = parseMarkdownToBlocks('Title\n===\n')
      expect(blocks[0].type).toBe('heading_1')
      expect(blocks[0].content).toBe('Title')
    })

    it('parses setext h2', () => {
      const blocks = parseMarkdownToBlocks('Sub\n---\n')
      expect(blocks[0].type).toBe('heading_2')
      expect(blocks[0].content).toBe('Sub')
    })
  })

  describe('lists', () => {
    it('parses bullet list', () => {
      const blocks = parseMarkdownToBlocks('- a\n- b\n- c')
      expect(blocks).toHaveLength(1)
      expect(blocks[0].type).toBe('list_group')
      const items = blocks[0].children!
      expect(items).toHaveLength(3)
      expect(items.map(i => i.content)).toEqual(['a', 'b', 'c'])
    })

    it('parses ordered list', () => {
      const blocks = parseMarkdownToBlocks('1. First\n2. Second')
      expect(blocks[0].type).toBe('list_group')
      const items = blocks[0].children!
      expect(items[0].type).toBe('ordered_list')
      expect(items[0].content).toBe('First')
    })

    it('parses nested list', () => {
      const blocks = parseMarkdownToBlocks('- a\n  - a1\n  - a2\n- b')
      expect(blocks[0].type).toBe('list_group')
      const items = blocks[0].children!
      expect(items).toHaveLength(2)
      expect(items[0].children).toBeDefined()
      const nested = items[0].children![0].children!
      expect(nested).toHaveLength(2)
      expect(nested.map(n => n.content)).toEqual(['a1', 'a2'])
    })

    it('parses loose list item with paragraph continuation (bug #10/#11)', () => {
      const blocks = parseMarkdownToBlocks(
        '- First item\n\n  Second paragraph in same item.\n- Second item'
      )
      expect(blocks[0].type).toBe('list_group')
      const items = blocks[0].children!
      expect(items).toHaveLength(2)
      // The second paragraph should be a child of the first list item, not a
      // top-level block.
      expect(items[0].children).toBeDefined()
      const childContents = items[0].children!.map(c => c.content)
      expect(childContents).toContain('Second paragraph in same item.')
    })

    it('parses task list', () => {
      const blocks = parseMarkdownToBlocks('- [ ] todo\n- [x] done')
      expect(blocks[0].type).toBe('list_group')
      const items = blocks[0].children!
      expect(items[0].type).toBe('task_list')
      expect(items[0].meta?.checked).toBe(false)
      expect(items[1].type).toBe('task_list')
      expect(items[1].meta?.checked).toBe(true)
    })
  })

  describe('images', () => {
    it('parses image with title (bug #8)', () => {
      const blocks = parseMarkdownToBlocks('![alt](https://x.com/i.png "title")')
      expect(blocks[0].type).toBe('image')
      expect(blocks[0].content).toContain('"title"')
      expect(blocks[0].meta?.language).toBe('https://x.com/i.png')
    })

    it('parses linked image (bug #9)', () => {
      const blocks = parseMarkdownToBlocks(
        '[![alt](https://x.com/i.png)](https://x.com)'
      )
      expect(blocks[0].type).toBe('image')
      expect(blocks[0].content).toContain('https://x.com')
      expect(blocks[0].content).toContain('https://x.com/i.png')
    })
  })

  describe('callouts', () => {
    it('parses callout', () => {
      const blocks = parseMarkdownToBlocks('[!NOTE] Hello')
      expect(blocks[0].type).toBe('callout')
      expect(blocks[0].meta?.calloutType).toBe('NOTE')
      expect(blocks[0].content).toBe('Hello')
    })
  })

  describe('code', () => {
    it('parses fenced code', () => {
      const blocks = parseMarkdownToBlocks('```js\nconst x = 1\n```')
      expect(blocks[0].type).toBe('code_block')
      expect(blocks[0].meta?.language).toBe('js')
      expect(blocks[0].content.trim()).toBe('const x = 1')
    })

    it('parses mermaid fence', () => {
      const blocks = parseMarkdownToBlocks('```mermaid\ngraph TD\n```')
      expect(blocks[0].type).toBe('mermaid')
    })

    it('parses indented code', () => {
      const blocks = parseMarkdownToBlocks('    code here')
      expect(blocks[0].type).toBe('code_block')
    })
  })

  describe('blockquote', () => {
    it('parses blockquote with children', () => {
      const blocks = parseMarkdownToBlocks('> quote text')
      expect(blocks[0].type).toBe('blockquote')
      expect(blocks[0].children).toBeDefined()
      expect(blocks[0].children![0].content).toBe('quote text')
    })
  })

  describe('table', () => {
    it('parses table', () => {
      const blocks = parseMarkdownToBlocks('| a | b |\n|---|---|\n| 1 | 2 |')
      expect(blocks[0].type).toBe('table')
      expect(blocks[0].content).toContain('| a | b |')
    })
  })

  describe('divider', () => {
    it('parses hr', () => {
      const blocks = parseMarkdownToBlocks('---\n')
      expect(blocks[0].type).toBe('divider')
    })
  })

  describe('toggle (html details)', () => {
    it('parses <details>', () => {
      // NOTE: with `html: false` in config, markdown-it treats <details> as
      // plain paragraph text. Enabling `html: true` would allow this but
      // introduces XSS vectors through `BlockRenderer`'s `html` block type.
      // Toggle blocks should be created through the editor UI (slash menu)
      // rather than markdown parsing.
      const blocks = parseMarkdownToBlocks(
        '<details>\n<summary>Title</summary>\nInner\n</details>'
      )
      expect(blocks[0].type).toBe('paragraph')
    })
  })

  describe('paragraphs', () => {
    it('parses plain paragraph', () => {
      const blocks = parseMarkdownToBlocks('Hello world')
      expect(blocks[0].type).toBe('paragraph')
      expect(blocks[0].content).toBe('Hello world')
    })

    it('parses multiple paragraphs separated by blank line', () => {
      const blocks = parseMarkdownToBlocks('First.\n\nSecond.')
      expect(blocks).toHaveLength(2)
      expect(blocks[0].content).toBe('First.')
      expect(blocks[1].content).toBe('Second.')
    })
  })

  describe('reference-style links (bug #7)', () => {
    it('reference text remains in paragraph content', () => {
      // The block parser keeps the reference-style syntax as-is in paragraph
      // content because the editor re-renders it via `renderInlineMarkdownToHtml`.
      const blocks = parseMarkdownToBlocks('[hobbit-hole][1]\n\n[1]: https://en.wikipedia.org/wiki/Hobbit')
      expect(blocks[0].type).toBe('paragraph')
      expect(blocks[0].content).toContain('[hobbit-hole][1]')
    })
  })

  describe('list item type detection', () => {
    it('detects ordered vs unordered items', () => {
      const blocks = parseMarkdownToBlocks('- a\n- b\n\n1. x\n2. y')
      expect(blocks[0].type).toBe('list_group')
      expect(blocks[0].children![0].type).toBe('bullet_list')
      expect(blocks[1].type).toBe('list_group')
      expect(blocks[1].children![0].type).toBe('ordered_list')
    })
  })

  describe('setext heading (bug #2)', () => {
    it('parses setext h1 and h2', () => {
      const blocks = parseMarkdownToBlocks('Title\n====\n\nSub\n---\n')
      expect(blocks[0].type).toBe('heading_1')
      expect(blocks[0].content).toBe('Title')
      expect(blocks[1].type).toBe('heading_2')
      expect(blocks[1].content).toBe('Sub')
    })
  })

  describe('linked image (bug #9)', () => {
    it('parses linked image as image block', () => {
      const blocks = parseMarkdownToBlocks('[![alt](https://x.com/i.png)](https://x.com)')
      expect(blocks[0].type).toBe('image')
      expect(blocks[0].content).toContain('https://x.com')
      expect(blocks[0].content).toContain('https://x.com/i.png')
    })
  })
})
