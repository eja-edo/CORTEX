import MarkdownIt from 'markdown-it'
import type { BlockNode, BlockType, BlockMeta } from '../types/editor'
import { generateBlockId } from '../types/editor'

interface MarkdownToken {
  type: string
  tag?: string
  content?: string
}

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
  const match = content.match(/^(?:-\s*)?\[\s*(x|X|\s)?\s*\]\s*/)
  if (!match) return null
  const checked = match[1] === 'x' || match[1] === 'X'
  const text = content.slice(match[0].length)
  return { checked, text }
}

function extractListContent(
  tokens: MarkdownToken[],
  startIdx: number,
  listType: BlockType,
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
            content += (content ? '\n' : '') + (inlineToken.content ?? '')
          }
          j += 2
          while (j < tokens.length && tokens[j]?.type !== 'paragraph_close') j++
          j++
        } else if (ct.type === 'bullet_list_open' || ct.type === 'ordered_list_open') {
          const nestedType: BlockType = ct.type === 'ordered_list_open' ? 'ordered_list' : 'bullet_list'
          const nested = extractListContent(tokens, j, nestedType)
          if (nested.blocks.length > 0) {
            itemChildren.push({
              id: generateBlockId(),
              type: 'list_group',
              content: '',
              children: nested.blocks,
            })
          }
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
      const type: BlockType = taskMatch ? 'task_list' : listType

      blocks.push({
        id: generateBlockId(),
        type,
        content: taskMatch ? taskMatch.text : content,
        meta: taskMatch ? { checked: taskMatch.checked } : {},
        children: itemChildren.length > 0 ? itemChildren : undefined,
      })

      i = j + 1
    } else if (t.type === 'bullet_list_close' || t.type === 'ordered_list_close') {
      break
    } else {
      i++
    }
  }

  return { blocks, endIdx: i }
}

function extractBlockquoteContent(
  tokens: MarkdownToken[],
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
          content: inlineToken.content ?? '',
        })
      }
      i += 2
      while (i < tokens.length && tokens[i]?.type !== 'paragraph_close') i++
      i++
    } else if (t.type === 'heading_open') {
      const levelTag = t.tag ?? ''
      const level = Number(levelTag.slice(1)) as 1 | 2 | 3
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
      const listType: BlockType = t.type === 'ordered_list_open' ? 'ordered_list' : 'bullet_list'
      const nested = extractListContent(tokens, i, listType)
      const listItems = nested.blocks
      if (listItems.length > 0) {
        blocks.push({
          id: generateBlockId(),
          type: 'list_group',
          content: '',
          children: listItems,
        })
      }
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

function pushPlainTextLines(blocks: BlockNode[], content: string): void {
  const lines = content.split(/\r?\n/)
  for (const line of lines) {
    if (line.trim() === '') continue
    blocks.push({
      id: generateBlockId(),
      type: 'paragraph',
      content: line,
    })
  }
}

type ListLineMatch = {
  kind: 'ordered' | 'bullet' | 'task'
  content: string
  checked?: boolean
}

function parseListLine(line: string): ListLineMatch | null {
  const orderedMatch = line.match(/^\s*(\d+)\.\s*(.*)$/)
  if (orderedMatch) {
    return { kind: 'ordered', content: orderedMatch[2] ?? '' }
  }

  const taskMatch = line.match(/^\s*[-*]\s*\[\s*(x|X)?\s*\]\s*(.*)$/)
  if (taskMatch) {
    return { kind: 'task', content: taskMatch[2] ?? '', checked: Boolean(taskMatch[1]) }
  }

  const bulletMatch = line.match(/^\s*[-*]\s*(.*)$/)
  if (bulletMatch) {
    return { kind: 'bullet', content: bulletMatch[1] ?? '' }
  }

  return null
}

interface FlatListItem {
  indent: number
  node: BlockNode
}

function buildNestedList(items: FlatListItem[], levelIndent: number): BlockNode[] {
  if (items.length === 0) return []

  const result: BlockNode[] = []
  let i = 0

  while (i < items.length) {
    const item = items[i]
    if (item.indent < levelIndent) break

    if (item.indent === levelIndent) {
      const children: FlatListItem[] = []
      let j = i + 1
      while (j < items.length && items[j].indent > levelIndent) {
        children.push(items[j])
        j++
      }

      const node: BlockNode = { ...item.node }
      if (children.length > 0) {
        const nextLevel = children[0].indent
        node.children = [{
          id: generateBlockId(),
          type: 'list_group',
          content: '',
          children: buildNestedList(children, nextLevel),
        }]
      }

      result.push(node)
      i = j
    } else {
      i++
    }
  }

  return result
}

function normalizeListParagraphs(blocks: BlockNode[]): BlockNode[] {
  const result: BlockNode[] = []
  let i = 0

  while (i < blocks.length) {
    const block = blocks[i]
    if (block?.type === 'paragraph') {
      const parsed = parseListLine(block.content)
      if (parsed) {
        const items: FlatListItem[] = []
        const targetKind = parsed.kind

        while (i < blocks.length) {
          const current = blocks[i]
          if (!current || current.type !== 'paragraph') break
          const currentIndent = current.content.match(/^\s*/)?.[0]?.length ?? 0
          const match = parseListLine(current.content)
          if (!match || match.kind !== targetKind) break

          const itemType: BlockType = match.kind === 'ordered'
            ? 'ordered_list'
            : match.kind === 'task'
              ? 'task_list'
              : 'bullet_list'

          items.push({
            indent: currentIndent,
            node: {
              id: generateBlockId(),
              type: itemType,
              content: match.content,
              meta: match.kind === 'task' ? { checked: match.checked } : undefined,
            },
          })
          i++
        }

        const firstIndent = items[0]?.indent ?? 0
        const children = buildNestedList(items, firstIndent)

        result.push({
          id: generateBlockId(),
          type: 'list_group',
          content: '',
          children,
        })
        continue
      }
    }

    if (block?.children) {
      result.push({ ...block, children: normalizeListParagraphs(block.children) })
    } else {
      result.push(block)
    }
    i++
  }

  return result
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
          const lines = content.split(/\r?\n/)
          for (const line of lines) {
            if (line.trim() === '') continue
            const imgMatch = line.match(/^!\[(.*?)\]\((.*?)\)$/)
            if (imgMatch) {
              blocks.push({
                id: generateBlockId(),
                type: 'image',
                content: line,
                meta: { language: imgMatch[2] },
              })
            } else {
              pushPlainTextLines(blocks, line)
            }
          }
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
        const lines = content.split(/\r?\n/)
        for (const line of lines) {
          if (line.trim() === '') continue
          const imgMatch = line.match(/^!\[(.*?)\]\((.*?)\)$/)
          if (imgMatch) {
            blocks.push({
              id: generateBlockId(),
              type: 'image',
              content: line,
              meta: { language: imgMatch[2] },
            })
          } else {
            pushPlainTextLines(blocks, line)
          }
        }
        break
      }

      case 'bullet_list_open':
      case 'ordered_list_open': {
        const listType: BlockType = token.type === 'ordered_list_open' ? 'ordered_list' : 'bullet_list'
        const listResult = extractListContent(tokens, i, listType)
        const listItems = listResult.blocks
        if (listItems.length > 0) {
          blocks.push({
            id: generateBlockId(),
            type: 'list_group',
            content: '',
            children: listItems,
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

  return normalizeListParagraphs(blocks)
}
