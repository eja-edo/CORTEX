import { useRef, useEffect, useCallback, useContext } from 'react'
import { useEditorStore } from '../stores/editorStore'
import type { BlockNode } from '../types/editor'
import { ReadOnlyCtx } from '../components/editor/EditorSurface'
import { renderInlineMarkdownToHtml } from '../utils/markdown/renderToHtml'

// ── Markdown ↔ HTML conversion ──────────────────────────────────────────────
//
// `inlineMdToHtml` delegates to the shared `renderInlineMarkdownToHtml` so the
// live editor preview parses with the same `markdown-it` configuration as
// every other render path (AskAI, ConversationDetail, NoteSidebar). This fixes
// the previous regex-based implementation which silently dropped the `title`
// attribute on links, did not unescape Markdown backslash syntax, and did not
// resolve reference-style links.
export function inlineMdToHtml(md: string): string {
  return renderInlineMarkdownToHtml(md)
}

export function htmlToInlineMd(html: string): string {
  if (!html) return ''

  const parser = new DOMParser()
  const doc = parser.parseFromString(`<body>${html}</body>`, 'text/html')

  function nodeToMd(node: Node): string {
    if (node.nodeType === Node.TEXT_NODE) {
      return node.textContent ?? ''
    }

    if (node.nodeType !== Node.ELEMENT_NODE) return ''

    const el = node as HTMLElement
    const tag = el.tagName.toLowerCase()
    const inner = Array.from(el.childNodes).map(nodeToMd).join('')

    switch (tag) {
      case 'strong':
      case 'b':
        return `**${inner}**`
      case 'em':
      case 'i':
        return `*${inner}*`
      case 'del':
      case 's':
        return `~~${inner}~~`
      case 'u':
        return `++${inner}++`
      case 'mark':
        return `==${inner}==`
      case 'code':
        return `\`${inner}\``
      case 'a': {
        const href = el.getAttribute('href') ?? ''
        const title = el.getAttribute('title') ?? ''
        // Re-emit `title` when present so the rendered HTML is round-trippable.
        return title ? `[${inner}](${href} "${title}")` : `[${inner}](${href})`
      }
      case 'br':
        return '  \n'
      case 'div':
      case 'p':
        return (el.previousSibling ? '\n' : '') + inner
      case 'span':
        return inner
      default:
        return inner
    }
  }

  const body = doc.body
  let result = Array.from(body.childNodes).map(nodeToMd).join('')

  result = result.replace(/\n{3,}/g, '\n\n')

  return result
}

type FormatType = 'bold' | 'italic' | 'underline' | 'strikethrough' | 'code' | 'highlight' | 'link'

function applyFormat(format: FormatType, linkUrl?: string): void {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) return
  
  const range = selection.getRangeAt(0)
  const selectedText = range.toString()
  
  if (format === 'code') {
    const code = document.createElement('code')
    try {
      range.surroundContents(code)
    } catch {
      const fragment = range.extractContents()
      code.appendChild(fragment)
      range.insertNode(code)
    }
    selection.removeAllRanges()
    return
  }
  
  if (format === 'strikethrough') {
    const del = document.createElement('del')
    try {
      range.surroundContents(del)
    } catch {
      const fragment = range.extractContents()
      del.appendChild(fragment)
      range.insertNode(del)
    }
    selection.removeAllRanges()
    return
  }
  
  if (format === 'highlight') {
    const mark = document.createElement('mark')
    try {
      range.surroundContents(mark)
    } catch {
      const fragment = range.extractContents()
      mark.appendChild(fragment)
      range.insertNode(mark)
    }
    selection.removeAllRanges()
    return
  }
  
  if (format === 'underline') {
    const u = document.createElement('u')
    try {
      range.surroundContents(u)
    } catch {
      const fragment = range.extractContents()
      u.appendChild(fragment)
      range.insertNode(u)
    }
    selection.removeAllRanges()
    return
  }
  
  if (format === 'link') {
    const url = linkUrl || window.prompt('URL:', 'https://')
    if (!url) return
    const a = document.createElement('a')
    a.href = url
    a.target = '_blank'
    a.rel = 'noopener noreferrer'
    a.textContent = selectedText || url
    range.deleteContents()
    range.insertNode(a)
    selection.removeAllRanges()
    return
  }
  
  if (format === 'bold') {
    document.execCommand('bold', false)
    return
  }
  
  if (format === 'italic') {
    document.execCommand('italic', false)
    return
  }
}

interface UseRichTextBlockOptions {
  block: BlockNode
  onContentChange?: (md: string) => void
}

export function useRichTextBlock({ block, onContentChange }: UseRichTextBlockOptions) {
  const ref = useRef<HTMLDivElement>(null)
  const isComposingRef = useRef(false)
  const lastMdRef = useRef<string>(block.content)
  const readOnly = useContext(ReadOnlyCtx)
  
  const updateBlockContent = useEditorStore(s => s.updateBlockContent)
  const setFocusedBlock = useEditorStore(s => s.setFocusedBlock)
  const focusedBlockId = useEditorStore(s => s.focusedBlockId)
  const openBubbleToolbar = useEditorStore(s => s.openBubbleToolbar)
  const closeBubbleToolbar = useEditorStore(s => s.closeBubbleToolbar)
  const isFocused = focusedBlockId === block.id

  useEffect(() => {
    if (!ref.current) return
    if (isFocused) return
    
    const newHtml = inlineMdToHtml(block.content)
    if (ref.current.innerHTML !== newHtml) {
      ref.current.innerHTML = newHtml
      lastMdRef.current = block.content
    }
  }, [block.content, isFocused])

  useEffect(() => {
    if (readOnly) return
    if (isFocused && ref.current) {
      ref.current.focus()
      const sel = window.getSelection()
      if (sel) {
        const range = document.createRange()
        range.selectNodeContents(ref.current)
        range.collapse(false)
        sel.removeAllRanges()
        sel.addRange(range)
      }
    }
  }, [isFocused, readOnly])

  const syncToStore = useCallback(() => {
    if (!ref.current) return
    const md = htmlToInlineMd(ref.current.innerHTML)
    if (md !== lastMdRef.current) {
      lastMdRef.current = md
      updateBlockContent(block.id, md)
      onContentChange?.(md)
    }
  }, [block.id, updateBlockContent, onContentChange])

  const handleInput = useCallback(() => {
    if (isComposingRef.current || readOnly) return
    syncToStore()
  }, [syncToStore, readOnly])

  const handleCompositionStart = useCallback(() => {
    isComposingRef.current = true
  }, [])

  const handleCompositionEnd = useCallback(() => {
    isComposingRef.current = false
    if (readOnly) return
    syncToStore()
  }, [syncToStore, readOnly])

  const handleFocus = useCallback(() => {
    if (readOnly) return
    setFocusedBlock(block.id)
  }, [block.id, setFocusedBlock, readOnly])

  const handleBlur = useCallback(() => {
    if (readOnly) return
    setFocusedBlock(null)
    closeBubbleToolbar()
    syncToStore()
  }, [setFocusedBlock, closeBubbleToolbar, syncToStore, readOnly])

  const handleMouseUp = useCallback(() => {
    if (readOnly) return
    const selection = window.getSelection()
    if (!selection || selection.isCollapsed) {
      closeBubbleToolbar()
      return
    }
    
    const range = selection.getRangeAt(0)
    const rect = range.getBoundingClientRect()
    
    if (rect.width > 0) {
      const x = rect.left + rect.width / 2
      const y = rect.top
      openBubbleToolbar(x, y, range.startOffset, range.endOffset)
    }
  }, [openBubbleToolbar, closeBubbleToolbar, readOnly])

  const handleKeyUp = useCallback((e: React.KeyboardEvent) => {
    if (readOnly) return
    if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Shift'].includes(e.key)) {
      const selection = window.getSelection()
      if (!selection?.isCollapsed) {
        const range = selection!.getRangeAt(0)
        const rect = range.getBoundingClientRect()
        if (rect.width > 0) {
          openBubbleToolbar(rect.left + rect.width / 2, rect.top, range.startOffset, range.endOffset)
        }
      } else {
        closeBubbleToolbar()
      }
    }
  }, [openBubbleToolbar, closeBubbleToolbar, readOnly])

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    if (readOnly) return
    e.preventDefault()
    const text = e.clipboardData.getData('text/plain')
    document.execCommand('insertText', false, text)
  }, [readOnly])

  const format = useCallback((formatType: FormatType, linkUrl?: string) => {
    if (readOnly || !ref.current) return
    ref.current.focus()
    applyFormat(formatType, linkUrl)
    setTimeout(syncToStore, 0)
  }, [syncToStore, readOnly])

  return {
    ref,
    isFocused,
    handleInput,
    handleCompositionStart,
    handleCompositionEnd,
    handleFocus,
    handleBlur,
    handleMouseUp,
    handleKeyUp,
    handlePaste,
    format,
    readOnly,
  }
}
