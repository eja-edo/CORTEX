import MarkdownIt from 'markdown-it'
import type Token from 'markdown-it/lib/token.mjs'
import type { BlockNode, BlockType, BlockMeta } from '../types/editor'
import { generateBlockId } from '../types/editor'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: true,
})

function isCalloutBlock(content: string): { calloutType: BlockMeta['calloutType'] } | null {
  const match = content.match(/^\[!(\w+)\]/)
  if (!match) return null
  const type = match[1].toUpperCase()
  if (['NOTE', 'TIP', 'WARNING', 'IMPORTANT', 'CAUTION'].includes(type)) {
    return { calloutType: type as BlockMeta['calloutType'] }
  }
  return null
}

function isTaskItem(content: string): { checked: boolean; text: string } | null {
  const match = content.match(/^-\s*\[\s*(x|X|\s)?\s*\]\s*/)
  if (!match) return null
  const checked = match[1] === 'x' || match[1] === 'X'
  const text = content.slice(match[0].length)
  return { checked, text }
}

function extractListContent(
  tokens: Token[],
  startIdx: number,
): { blocks: BlockNode[]; endIdx: number } {
  const blocks: BlockNode[] = []
  let i = startIdx

  while (i < tokens.length) {
    const t = tokens[i]
    if (!t) break

    if (t.type === 'list_item_open') {
      let content = ''
      let j = i + 1
      const itemChildren: BlockNode[] = []

      while (j < tokens.length && tokens[j]?.type !== 'list_item_close') {
        const ct = tokens[j]
        if (!ct) { j++; continue }

        if (ct.type === 'paragraph_open') {
          const inlineToken = tokens[j + 1]
          if (inlineToken?.type === 'inline') {
            content += (content ? '\n' : '') + inlineToken.content
          }
          j += 2
          while (j < tokens.length && tokens[j]?.type !== 'paragraph_close') j++
          j++
        } else if (ct.type === 'bullet_list_open' || ct.type === 'ordered_list_open') {
          const nested = extractListContent(tokens, j)
          itemChildren.push(...nested.blocks)
          j = nested.endIdx
        } else if (ct.type === 'blockquote_open') {
          const nested = extractBlockquoteContent(tokens, j)
          itemChildren.push(...nested.blocks)
          j = nested.endIdx
        } else {
          j++
        }
      }

      const taskMatch = isTaskItem(content)
      const type: BlockType = taskMatch ? 'task_list' : 'bullet_list'

      blocks.push({
        id: generateBlockId(),
        type,
        content: taskMatch ? taskMatch.text : content,
        meta: taskMatch ? { checked: taskMatch.checked } : {},
        children: itemChildren.length > 0 ? itemChildren : undefined,
      })

      i = j + 1
    } else if (t.type === 'bullet_list_close' || t.type === 'ordered_list_close') {
      i++
      break
    } else {
      i++
    }
  }

  return { blocks, endIdx: i }
}

function extractBlockquoteContent(
  tokens: Token[],
  startIdx: number,
): { blocks: BlockNode[]; endIdx: number } {
  const blocks: BlockNode[] = []
  let i = startIdx + 1

  while (i < tokens.length) {
    const t = tokens[i]
    if (!t) { i++; continue }

    if (t.type === 'paragraph_open') {
      const inlineToken = tokens[i + 1]
      if (inlineToken?.type === 'inline') {
        blocks.push({
          id: generateBlockId(),
          type: 'paragraph',
          content: inlineToken.content,
        })
      }
      i += 2
      while (i < tokens.length && tokens[i]?.type !== 'paragraph_close') i++
      i++
    } else if (t.type === 'heading_open') {
      const level = Number(t.tag.slice(1)) as 1 | 2 | 3
      const inlineToken = tokens[i + 1]
      const content = inlineToken?.content ?? ''
      const headingType = `heading_${level}` as BlockType
      blocks.push({
        id: generateBlockId(),
        type: headingType,
        content,
      })
      i += 2
      while (i < tokens.length && tokens[i]?.type !== 'heading_close') i++
      i++
    } else if (t.type === 'bullet_list_open' || t.type === 'ordered_list_open') {
      const nested = extractListContent(tokens, i)
      blocks.push(...nested.blocks)
      i = nested.endIdx
    } else if (t.type === 'blockquote_close') {
      i++
      break
    } else {
      i++
    }
  }

  return { blocks, endIdx: i }
}

function insertBlankLineBlocks(blocks: BlockNode[], currentLineStart: number, lastLineEndRef: { value: number }): void {
  // gap includes the standard markdown separator (1 blank line between blocks)
  // extra blank lines beyond the separator become empty paragraph blocks
  const gap = currentLineStart - lastLineEndRef.value
  const extraLines = Math.max(0, gap - 1)
  if (extraLines > 0) {
    for (let g = 0; g < extraLines; g++) {
      blocks.push({
        id: generateBlockId(),
        type: 'paragraph',
        content: '',
      })
    }
  }
  lastLineEndRef.value = currentLineStart
}

export function parseMarkdownToBlocks(source: string): BlockNode[] {
  if (!source || !source.trim()) {
    return [{
      id: generateBlockId(),
      type: 'paragraph',
      content: '',
    }]
  }

  const tokens = md.parse(source, {})
  const blocks: BlockNode[] = []
  const lastLineEnd = { value: 0 }

  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i]
    if (!token) continue

    // Track blank lines by checking map offsets (top-level tokens only)
    if (token.level === 0 && token.map) {
      insertBlankLineBlocks(blocks, token.map[0], lastLineEnd)
      lastLineEnd.value = token.map[1]
    }

    switch (token.type) {
      case 'heading_open': {
        const level = Number(token.tag.slice(1)) as 1 | 2 | 3
        if (level < 1 || level > 3) continue
        const inlineToken = tokens[i + 1]
        const content = inlineToken?.content ?? ''
        const headingType = `heading_${level}` as BlockType
        blocks.push({
          id: generateBlockId(),
          type: headingType,
          content,
        })
        i += 2
        while (i < tokens.length && tokens[i]?.type !== 'heading_close') i++
        break
      }

      case 'paragraph_open': {
        let content = ''
        if (token.map) {
          const sourceLines = source.split('\n')
          content = sourceLines.slice(token.map[0], token.map[1]).join('\n')
        } else {
          const inlineToken = tokens[i + 1]
          content = inlineToken?.content ?? ''
        }

        const calloutMatch = isCalloutBlock(content)
        if (calloutMatch) {
          blocks.push({
            id: generateBlockId(),
            type: 'callout',
            content: content.replace(/^\[!\w+\]\s*/, ''),
            meta: { calloutType: calloutMatch.calloutType },
          })
        } else {
          blocks.push({
            id: generateBlockId(),
            type: 'paragraph',
            content,
          })
        }

        i += 2
        while (i < tokens.length && tokens[i]?.type !== 'paragraph_close') i++
        break
      }

      case 'inline': {
        let content = token.content
        if (token.map) {
          const sourceLines = source.split('\n')
          content = sourceLines.slice(token.map[0], token.map[1]).join('\n')
        }
        blocks.push({
          id: generateBlockId(),
          type: 'paragraph',
          content,
        })
        break
      }

      case 'bullet_list_open':
      case 'ordered_list_open': {
        const listType: BlockType = token.type === 'ordered_list_open' ? 'ordered_list' : 'bullet_list'
        const listResult = extractListContent(tokens, i)
        for (const item of listResult.blocks) {
          const itemType = item.type === 'task_list' ? 'task_list' : listType
          blocks.push({
            ...item,
            type: itemType,
          })
        }
        i = listResult.endIdx
        break
      }

      case 'fence': {
        const language = token.info || ''
        if (language.toLowerCase() === 'mermaid') {
          blocks.push({
            id: generateBlockId(),
            type: 'mermaid',
            content: token.content,
          })
        } else {
          blocks.push({
            id: generateBlockId(),
            type: 'code_block',
            content: token.content,
            meta: { language },
          })
        }
        break
      }

      case 'code_block': {
        blocks.push({
          id: generateBlockId(),
          type: 'code_block',
          content: token.content,
        })
        break
      }

      case 'hr': {
        blocks.push({
          id: generateBlockId(),
          type: 'divider',
          content: '',
        })
        break
      }

      case 'blockquote_open': {
        const quoteBlocks = extractBlockquoteContent(tokens, i)
        blocks.push({
          id: generateBlockId(),
          type: 'blockquote',
          content: '',
          children: quoteBlocks.blocks.length > 0 ? quoteBlocks.blocks : undefined,
        })
        i = quoteBlocks.endIdx
        break
      }

      case 'table_open': {
        let depth = 1
        let j = i + 1
        while (j < tokens.length && depth > 0) {
          const tt = tokens[j]
          if (tt?.type === 'table_open') depth++
          if (tt?.type === 'table_close') depth--
          j++
        }
        const tableLines = source.split('\n')
        const startLine = token.map?.[0] ?? 0
        const endLine = tokens[j - 1]?.map?.[1] ?? startLine + 1
        const tableMd = tableLines.slice(startLine, endLine).join('\n')
        blocks.push({
          id: generateBlockId(),
          type: 'table',
          content: tableMd,
        })
        i = j - 1
        break
      }

      case 'image': {
        const src = token.attrGet('src') ?? ''
        const alt = token.content ?? ''
        blocks.push({
          id: generateBlockId(),
          type: 'image',
          content: `![${alt}](${src})`,
          meta: { language: src },
        })
        break
      }

      case 'html_block': {
        const htmlContent = token.content

        if (htmlContent.trim().startsWith('<details')) {
          const summaryMatch = htmlContent.match(/<summary>([\s\S]*?)<\/summary>/)
          const summary = summaryMatch?.[1]?.trim() ?? ''
          const innerContent = htmlContent
            .replace(/<details>?[\s\S]*?<\/summary>\s*/, '')
            .replace(/<\/details>/, '')
            .trim()

          blocks.push({
            id: generateBlockId(),
            type: 'toggle',
            content: summary,
            children: innerContent
              ? parseMarkdownToBlocks(innerContent)
              : undefined,
          })
        } else {
          blocks.push({
            id: generateBlockId(),
            type: 'html',
            content: htmlContent,
          })
        }
        break
      }
    }
  }

  // Trailing blank lines: first is the separator, rest become empty blocks
  const totalLines = source.split('\n').length - 1
  const trailingBlanks = totalLines - lastLineEnd.value
  const extraTrailing = Math.max(0, trailingBlanks - 1)
  if (extraTrailing > 0) {
    for (let g = 0; g < extraTrailing; g++) {
      blocks.push({
        id: generateBlockId(),
        type: 'paragraph',
        content: '',
      })
    }
  }

  return blocks
}
