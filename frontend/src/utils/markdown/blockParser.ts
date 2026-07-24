import MarkdownIt from 'markdown-it'
import type { Token } from 'markdown-it/index.js'
import type { BlockNode, BlockType } from '../../types/editor'
import { generateBlockId } from '../../types/editor'
import { MARKDOWN_IT_OPTIONS } from './config'

// Shared parser — `MARKDOWN_IT_OPTIONS` is the single source of truth mirrored
// in the backend `markdown_config.py`.
const md = new MarkdownIt(MARKDOWN_IT_OPTIONS)

interface CalloutMatch { calloutType: 'NOTE' | 'TIP' | 'WARNING' | 'IMPORTANT' | 'CAUTION' }
interface TaskMatch { checked: boolean; text: string }

function detectCallout(content: string): CalloutMatch | null {
  const match = content.match(/^\[!(\w+)\]/)
  if (!match) return null
  const type = match[1].toUpperCase()
  if (['NOTE', 'TIP', 'WARNING', 'IMPORTANT', 'CAUTION'].includes(type)) {
    return { calloutType: type as CalloutMatch['calloutType'] }
  }
  return null
}

function detectTaskItem(content: string): TaskMatch | null {
  const match = content.match(/^(?:-\s*)?\[\s*(x|X|\s)?\s*\]\s*/)
  if (!match) return null
  return { checked: match[1] === 'x' || match[1] === 'X', text: content.slice(match[0].length) }
}

// Parse an inline token subtree (anything between an `_open` and matching
// `_close`) into the raw markdown source. We use this so children blocks keep
// the original text including inline formatting (bold, link, code) that the
// editor's `useRichTextBlock` hook will re-render through `renderInlineMarkdownToHtml`.
function inlineTextFromTokens(tokens: Token[], startIdx: number, endIdx: number): string {
  const parts: string[] = []
  for (let i = startIdx; i < endIdx; i++) {
    const t = tokens[i]
    if (!t) continue
    if (t.type === 'inline') {
      parts.push(t.content)
    } else if (t.type === 'softbreak') {
      parts.push('\n')
    } else if (t.type === 'hardbreak') {
      parts.push('  \n')
    }
  }
  return parts.join('')
}

// Extract a list subtree (from `list_open` through `list_close` at the same
// nesting level) into a flat list of BlockNode ready for the editor.
// `level` is the nesting depth (0 = top-level) used by ListGroupBlock to
// compute padding.
function extractList(tokens: Token[], listOpenIdx: number, listType: 'bullet_list' | 'ordered_list', level = 0): { blocks: BlockNode[]; endIdx: number } {
  const blocks: BlockNode[] = []
  let i = listOpenIdx + 1
  let order = 0
  while (i < tokens.length) {
    const t = tokens[i]
    if (!t) { i++; continue }
    // Any list_close (bullet_list_close or ordered_list_close) ends this level.
    if (t.type === 'bullet_list_close' || t.type === 'ordered_list_close') {
      return { blocks, endIdx: i + 1 }
    }
    if (t.type === 'list_item_open') {
      order++
      const item = extractListItem(tokens, i, listType, order, level)
      blocks.push(item.node)
      i = item.endIdx
      continue
    }
    i++
  }
  return { blocks, endIdx: i }
}

// Extract a single `<li>` body. Handles three child shapes per CommonMark:
//  1. paragraph(s) (tight or loose)
//  2. nested list(s)
//  3. block-level content (code block, blockquote, …)
//
// Tight lists: all paragraphs collapse into the item's `content` text.
// Loose lists: the first paragraph is the item content; subsequent
// paragraphs and block children are surfaced as `children` blocks so the
// editor can render them inside the `<li>`.
function extractListItem(
  tokens: Token[],
  startIdx: number,
  listType: 'bullet_list' | 'ordered_list',
  order: number,
  level: number,
): { node: BlockNode; endIdx: number } {
  const itemChildren: BlockNode[] = []
  const paragraphParts: string[] = []
  let i = startIdx + 1

  while (i < tokens.length) {
    const t = tokens[i]
    if (!t) { i++; continue }
    if (t.type === 'list_item_close') {
      const inlineText = paragraphParts.join('\n').trimEnd()
      const taskMatch = detectTaskItem(inlineText)
      const isTask = !!taskMatch
      const itemType: BlockType = isTask ? 'task_list' : listType
      const content = isTask ? taskMatch.text : inlineText
      const node: BlockNode = {
        id: generateBlockId(),
        type: itemType,
        content,
        meta: isTask
          ? { checked: taskMatch.checked, listNesting: level }
          : { listNesting: level },
        children: itemChildren.length > 0 ? itemChildren : undefined,
      }
      if (order > 0) node.meta = { ...node.meta, order }
      return { node, endIdx: i + 1 }
    }

    if (t.type === 'paragraph_open') {
      const closeIdx = findClose(tokens, i, 'paragraph_open', 'paragraph_close')
      const text = inlineTextFromTokens(tokens, i + 1, closeIdx)
      if (paragraphParts.length === 0) {
        // First paragraph → item content.
        paragraphParts.push(text)
      } else {
        // Subsequent paragraph (loose list) → child block.
        itemChildren.push({
          id: generateBlockId(),
          type: 'paragraph',
          content: text,
        })
      }
      i = closeIdx + 1
      continue
    }

    if (t.type === 'bullet_list_open' || t.type === 'ordered_list_open') {
      const subListType: 'bullet_list' | 'ordered_list' = t.type === 'ordered_list_open' ? 'ordered_list' : 'bullet_list'
      const sub = extractList(tokens, i, subListType, level + 1)
      if (sub.blocks.length > 0) {
        itemChildren.push({
          id: generateBlockId(),
          type: 'list_group',
          content: '',
          children: sub.blocks,
        })
      }
      i = sub.endIdx
      continue
    }

    if (t.type === 'blockquote_open') {
      const closeIdx = findClose(tokens, i, 'blockquote_open', 'blockquote_close')
      const inner = extractBlockquote(tokens, i)
      itemChildren.push(...inner.blocks)
      i = closeIdx + 1
      continue
    }

    if (t.type === 'fence' || t.type === 'code_block') {
      const lang = t.type === 'fence' ? (t.info || '') : ''
      itemChildren.push({
        id: generateBlockId(),
        type: 'code_block',
        content: t.content,
        meta: lang ? { language: lang } : undefined,
      })
      i++
      continue
    }

    if (t.type === 'inline') {
      if (paragraphParts.length === 0) {
        paragraphParts.push(t.content)
      } else {
        itemChildren.push({ id: generateBlockId(), type: 'paragraph', content: t.content })
      }
      i++
      continue
    }

    i++
  }

  // Fell through without list_item_close (malformed input)
  const inlineText = paragraphParts.join('\n').trimEnd()
  const taskMatch = detectTaskItem(inlineText)
  const itemType: BlockType = taskMatch ? 'task_list' : listType
  return {
    node: {
      id: generateBlockId(),
      type: itemType,
      content: taskMatch ? taskMatch.text : inlineText,
      meta: taskMatch
        ? { checked: taskMatch.checked, listNesting: level }
        : { listNesting: level },
      children: itemChildren.length > 0 ? itemChildren : undefined,
    },
    endIdx: i,
  }
}

// Find the matching close token, accounting for nesting of the same tag type.
function findClose(tokens: Token[], from: number, openType: string, closeType: string): number {
  let depth = 0
  for (let i = from; i < tokens.length; i++) {
    const t = tokens[i]
    if (!t) continue
    if (t.type === openType) depth++
    if (t.type === closeType) {
      depth--
      if (depth === 0) return i
    }
  }
  return tokens.length - 1
}

function extractBlockquote(tokens: Token[], from: number): { blocks: BlockNode[]; endIdx: number } {
  const blocks: BlockNode[] = []
  const bqClose = findClose(tokens, from, 'blockquote_open', 'blockquote_close')
  let i = from + 1
  while (i < bqClose) {
    const t = tokens[i]
    if (!t) { i++; continue }
    if (t.type === 'paragraph_open') {
      const paraClose = findClose(tokens, i, 'paragraph_open', 'paragraph_close')
      const text = inlineTextFromTokens(tokens, i + 1, paraClose)
      blocks.push({ id: generateBlockId(), type: 'paragraph', content: text })
      i = paraClose + 1
      continue
    }
    if (t.type === 'heading_open') {
      const level = Number(t.tag.slice(1)) || 1
      const inline = tokens[i + 1]
      const text = inline?.type === 'inline' ? inline.content : ''
      const closeTagIdx = findClose(tokens, i, 'heading_open', 'heading_close')
      blocks.push({ id: generateBlockId(), type: `heading_${level}` as BlockType, content: text })
      i = closeTagIdx + 1
      continue
    }
    if (t.type === 'bullet_list_open' || t.type === 'ordered_list_open') {
      const blistType: 'bullet_list' | 'ordered_list' = t.type === 'ordered_list_open' ? 'ordered_list' : 'bullet_list'
      const sub = extractList(tokens, i, blistType, 0)
      if (sub.blocks.length > 0) {
        blocks.push({ id: generateBlockId(), type: 'list_group', content: '', children: sub.blocks })
      }
      i = sub.endIdx
      continue
    }
    i++
  }
  return { blocks, endIdx: bqClose + 1 }
}

// Pull alt/src/title/wrap-link from the inline `image` token. The token's
// children carry the alt text. The wrapping link, if any, is read by
// `parseImageFromTokens` so that `[![alt](src)](url)` round-trips.
function readImageAttrs(imageToken: Token): { alt: string; src: string; title: string | null } {
  const src = imageToken.attrGet('src') ?? ''
  const title = imageToken.attrGet('title')
  const alt = imageToken.children
    ?.filter(c => c.type === 'text' || c.type === 'code_inline')
    .map(c => c.content)
    .join('') ?? ''
  return { alt, src, title: title ?? null }
}

// Walk an inline token list (children of an inline token), looking for a
// `link_open` immediately before the `image` and a `link_close` immediately
// after. Returns the href of the wrapping link, or null if the image is bare.
function findWrappingLink(inlineChildren: Token[], imageIdx: number): string | null {
  if (imageIdx > 0 && imageIdx < inlineChildren.length - 1) {
    const prev = inlineChildren[imageIdx - 1]
    const next = inlineChildren[imageIdx + 1]
    if (prev?.type === 'link_open' && next?.type === 'link_close') {
      return prev.attrGet('href') ?? null
    }
  }
  return null
}

// Build a single image block from an `image` token. Captures alt, src, title,
// and the optional wrapping link href so the rendered block can either inline
// the link or fall back to raw markdown for unhandled cases.
function imageBlockFromToken(inlineChildren: Token[], imageIdx: number, lineMap?: [number, number]): BlockNode {
  const t = inlineChildren[imageIdx]
  if (!t) {
    return { id: generateBlockId(), type: 'image', content: '![](https://)', meta: { lineStart: lineMap?.[0], lineEnd: lineMap?.[1] } }
  }
  const { alt, src, title } = readImageAttrs(t)
  const wrapHref = findWrappingLink(inlineChildren, imageIdx)
  const md = wrapHref
    ? `[![${alt}](${src}${title ? ` "${title}"` : ''})](${wrapHref})`
    : `![${alt}](${src}${title ? ` "${title}"` : ''})`
  return {
    id: generateBlockId(),
    type: 'image',
    content: md,
    meta: { language: src, lineStart: lineMap?.[0], lineEnd: lineMap?.[1] },
  }
}

// Inline-level parser: walk an array of inline tokens (paragraph body) and
// yield a list of blocks. Used as a fallback when we have raw inline text
// rather than tokens (e.g. inside list items where we already extracted text).
function parseInlineTextAsBlocks(text: string, lineMap?: [number, number]): BlockNode[] {
  if (!text) return []
  // Single bare line of image markdown?
  const trimmed = text.trim()
  const imgMatch = trimmed.match(/^!\[(.*?)\]\((.*?)(?:\s+"(.*?)")?\)$/)
  if (imgMatch) {
    return [{
      id: generateBlockId(),
      type: 'image',
      content: imgMatch[3]
        ? `![${imgMatch[1]}](${imgMatch[2]} "${imgMatch[3]}")`
        : `![${imgMatch[1]}](${imgMatch[2]})`,
      meta: { language: imgMatch[2], lineStart: lineMap?.[0], lineEnd: lineMap?.[1] },
    }]
  }
  return [{ id: generateBlockId(), type: 'paragraph', content: text, meta: lineMap ? { lineStart: lineMap[0], lineEnd: lineMap[1] } : undefined }]
}

// Trim top-level inline content, keeping links/strong/em/code/strike intact
// for the editor's rich-text hook to re-render.
function readInlineContent(tokens: Token[], start: number, end: number): string {
  return inlineTextFromTokens(tokens, start, end)
}

export function parseMarkdownToBlocks(source: string): BlockNode[] {
  if (!source || !source.trim()) {
    return [{ id: generateBlockId(), type: 'paragraph', content: '' }]
  }

  const tokens = md.parse(source, {})
  const blocks: BlockNode[] = []
  let lastLineEnd = 0

  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i]
    if (!token) continue

    // Track blank lines between top-level blocks (one blank line = separator,
    // extras become empty paragraphs).
    if (token.level === 0 && token.map) {
      const gap = token.map[0] - lastLineEnd
      if (gap > 1) {
        for (let g = 1; g < gap; g++) {
          blocks.push({ id: generateBlockId(), type: 'paragraph', content: '' })
        }
      }
      lastLineEnd = token.map[1]
    }

    const lineStart = token.map?.[0]
    const lineEnd = token.map?.[1]
    const lineMeta: [number, number] | undefined = (lineStart !== undefined && lineEnd !== undefined)
      ? [lineStart, lineEnd]
      : undefined

    switch (token.type) {
      case 'heading_open': {
        const level = Number(token.tag.slice(1))
        if (level < 1 || level > 6) continue
        const inline = tokens[i + 1]
        const text = inline?.type === 'inline' ? inline.content : ''
        const closeIdx = findClose(tokens, i, 'heading_open', 'heading_close')
        blocks.push({
          id: generateBlockId(),
          type: `heading_${level}` as BlockType,
          content: text,
          meta: lineMeta ? { lineStart: lineMeta[0], lineEnd: lineMeta[1] } : undefined,
        })
        i = closeIdx
        break
      }

      case 'paragraph_open': {
        const closeIdx = findClose(tokens, i, 'paragraph_open', 'paragraph_close')
        const text = readInlineContent(tokens, i + 1, closeIdx)

        // Look inside the inline for image(s). Supports:
        //   - bare image  ![alt](src)
        //   - linked image [![alt](src)](url)
        //   - only-this-paragraph-is-an-image (single token or link→image→close)
        const inlineToken = tokens[i + 1]
        if (inlineToken?.children && inlineToken.children.length > 0) {
          const cs = inlineToken.children
          const onlyImage =
            cs.length === 1 && cs[0]?.type === 'image'
          const linkedImage =
            cs.length === 3 &&
            cs[0]?.type === 'link_open' &&
            cs[1]?.type === 'image' &&
            cs[2]?.type === 'link_close'
          if (onlyImage) {
            blocks.push(imageBlockFromToken(cs, 0, lineMeta))
            i = closeIdx
            break
          }
          if (linkedImage) {
            blocks.push(imageBlockFromToken(cs, 1, lineMeta))
            i = closeIdx
            break
          }
        }

        const callout = detectCallout(text)
        if (callout) {
          blocks.push({
            id: generateBlockId(),
            type: 'callout',
            content: text.replace(/^\[!\w+\]\s*/, ''),
            meta: { ...callout, lineStart: lineMeta?.[0], lineEnd: lineMeta?.[1] },
          })
        } else {
          // Split multi-line paragraphs on hard breaks (2-space line break per
          // spec) — each becomes its own block so the editor can render the
          // line break as a real <br>.
          const segments = text.split(/\n/)
          for (const seg of segments) {
            if (seg === '') continue
            blocks.push(...parseInlineTextAsBlocks(seg, lineMeta))
          }
        }
        i = closeIdx
        break
      }

      case 'bullet_list_open':
      case 'ordered_list_open': {
        const listType: 'bullet_list' | 'ordered_list' = token.type === 'ordered_list_open' ? 'ordered_list' : 'bullet_list'
        const list = extractList(tokens, i, listType, 0)
        if (list.blocks.length > 0) {
          blocks.push({
            id: generateBlockId(),
            type: 'list_group',
            content: '',
            children: list.blocks,
            meta: lineMeta ? { lineStart: lineMeta[0], lineEnd: lineMeta[1] } : undefined,
          })
        }
        i = list.endIdx - 1
        break
      }

      case 'blockquote_open': {
        const inner = extractBlockquote(tokens, i)
        blocks.push({
          id: generateBlockId(),
          type: 'blockquote',
          content: '',
          children: inner.blocks.length > 0 ? inner.blocks : undefined,
          meta: lineMeta ? { lineStart: lineMeta[0], lineEnd: lineMeta[1] } : undefined,
        })
        i = inner.endIdx - 1
        break
      }

      case 'fence': {
        const language = token.info || ''
        if (language.toLowerCase() === 'mermaid') {
          blocks.push({
            id: generateBlockId(),
            type: 'mermaid',
            content: token.content,
            meta: { language, ...(lineMeta ? { lineStart: lineMeta[0], lineEnd: lineMeta[1] } : {}) },
          })
        } else {
          blocks.push({
            id: generateBlockId(),
            type: 'code_block',
            content: token.content,
            meta: { language, ...(lineMeta ? { lineStart: lineMeta[0], lineEnd: lineMeta[1] } : {}) },
          })
        }
        break
      }

      case 'code_block': {
        blocks.push({
          id: generateBlockId(),
          type: 'code_block',
          content: token.content,
          meta: lineMeta ? { lineStart: lineMeta[0], lineEnd: lineMeta[1] } : undefined,
        })
        break
      }

      case 'hr': {
        blocks.push({
          id: generateBlockId(),
          type: 'divider',
          content: '',
          meta: lineMeta ? { lineStart: lineMeta[0], lineEnd: lineMeta[1] } : undefined,
        })
        break
      }

      case 'table_open': {
        const closeIdx = findClose(tokens, i, 'table_open', 'table_close')
        const tableLines = source.split('\n')
        const startLine = lineMeta?.[0] ?? 0
        const endLine = lineMeta?.[1] ?? startLine + 1
        blocks.push({
          id: generateBlockId(),
          type: 'table',
          content: tableLines.slice(startLine, endLine).join('\n'),
          meta: lineMeta ? { lineStart: lineMeta[0], lineEnd: lineMeta[1] } : undefined,
        })
        i = closeIdx
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
            meta: lineMeta ? { lineStart: lineMeta[0], lineEnd: lineMeta[1] } : undefined,
            children: innerContent ? parseMarkdownToBlocks(innerContent) : undefined,
          })
        } else {
          blocks.push({
            id: generateBlockId(),
            type: 'html',
            content: htmlContent,
            meta: lineMeta ? { lineStart: lineMeta[0], lineEnd: lineMeta[1] } : undefined,
          })
        }
        break
      }
    }
  }

  // Trailing blank lines: first is the separator, rest become empty blocks.
  const totalLines = source.split('\n').length - 1
  const trailing = totalLines - lastLineEnd
  if (trailing > 1) {
    for (let g = 1; g < trailing; g++) {
      blocks.push({ id: generateBlockId(), type: 'paragraph', content: '' })
    }
  }

  return blocks
}

// Re-export for unit tests so they can drive the same parser without exposing
// `md` through the public surface.
export const _internal = { md, detectCallout, detectTaskItem, readImageAttrs, findWrappingLink }
