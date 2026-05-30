import { useRef, useEffect, useCallback } from 'react'
import { useEditorStore } from '../stores/editorStore'
import type { BlockNode } from '../types/editor'

// ── Markdown ↔ HTML conversion ──────────────────────────────────────────────

/**
 * Convert inline markdown to HTML for display in contentEditable.
 * Order matters: bold before italic to handle **bold** vs *italic* overlap.
 */
export function inlineMdToHtml(md: string): string {
  if (!md) return ''
  return md
    // Bold+italic: ***text*** or ___text___
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/___(.+?)___/g, '<strong><em>$1</em></strong>')
    // Bold: **text** or __text__
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/__(.+?)__/g, '<strong>$1</strong>')
    // Italic: *text* or _text_
    .replace(/\*([^*\n]+?)\*/g, '<em>$1</em>')
    .replace(/_([^_\n]+?)_/g, '<em>$1</em>')
    // Strikethrough: ~~text~~
    .replace(/~~(.+?)~~/g, '<del>$1</del>')
    // Underline: ++text++ (non-standard but useful)
    .replace(/\+\+(.+?)\+\+/g, '<u>$1</u>')
    // Highlight: ==text==
    .replace(/==(.+?)==/g, '<mark>$1</mark>')
    // Inline code: `code`
    .replace(/`([^`\n]+?)`/g, '<code>$1</code>')
    // Links: [text](url)
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
}

/**
 * Convert HTML (from contentEditable inner HTML) back to inline markdown.
 * Handles nested tags and browser-inserted elements like <br>, <div>, <span>.
 */
export function htmlToInlineMd(html: string): string {
  if (!html) return ''
  
  // Use a DOMParser to walk the tree properly
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
        return `[${inner}](${href})`
      }
      case 'br':
        return '\n'
      case 'div':
      case 'p':
        // Browser wraps new lines in divs - add newline before block elements
        // but only if there's preceding content (not the first div)
        return (el.previousSibling ? '\n' : '') + inner
      case 'span':
        return inner
      default:
        return inner
    }
  }
  
  const body = doc.body
  let result = Array.from(body.childNodes).map(nodeToMd).join('')
  
  // Clean up: normalize multiple newlines into single
  result = result.replace(/\n{3,}/g, '\n\n')
  
  return result
}

// ── Formatting command ───────────────────────────────────────────────────────

type FormatType = 'bold' | 'italic' | 'underline' | 'strikethrough' | 'code' | 'highlight' | 'link'

function applyFormat(format: FormatType, linkUrl?: string): void {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) return
  
  const range = selection.getRangeAt(0)
  const selectedText = range.toString()
  
  // For code and strikethrough, use execCommand workaround via surroundContents
  if (format === 'code') {
    const code = document.createElement('code')
    try {
      range.surroundContents(code)
    } catch {
      // Selection spans multiple elements - extract and re-wrap
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
  
  // Bold and italic: use execCommand (best browser support)
  if (format === 'bold') {
    document.execCommand('bold', false)
    return
  }
  
  if (format === 'italic') {
    document.execCommand('italic', false)
    return
  }
}

// ── useRichTextBlock hook ────────────────────────────────────────────────────

interface UseRichTextBlockOptions {
  block: BlockNode
  /** Called when content changes, receives the markdown string */
  onContentChange?: (md: string) => void
}

export function useRichTextBlock({ block, onContentChange }: UseRichTextBlockOptions) {
  const ref = useRef<HTMLDivElement>(null)
  const isComposingRef = useRef(false)
  const lastMdRef = useRef<string>(block.content)
  
  const updateBlockContent = useEditorStore(s => s.updateBlockContent)
  const setFocusedBlock = useEditorStore(s => s.setFocusedBlock)
  const focusedBlockId = useEditorStore(s => s.focusedBlockId)
  const openBubbleToolbar = useEditorStore(s => s.openBubbleToolbar)
  const closeBubbleToolbar = useEditorStore(s => s.closeBubbleToolbar)
  const isFocused = focusedBlockId === block.id

  // Sync content from store → DOM (only when not focused to avoid cursor jump)
  useEffect(() => {
    if (!ref.current) return
    if (isFocused) return // Don't overwrite while user is typing
    
    const newHtml = inlineMdToHtml(block.content)
    if (ref.current.innerHTML !== newHtml) {
      ref.current.innerHTML = newHtml
      lastMdRef.current = block.content
    }
  }, [block.content, isFocused])

  // Focus management
  useEffect(() => {
    if (isFocused && ref.current) {
      ref.current.focus()
      // Place cursor at end
      const sel = window.getSelection()
      if (sel) {
        const range = document.createRange()
        range.selectNodeContents(ref.current)
        range.collapse(false)
        sel.removeAllRanges()
        sel.addRange(range)
      }
    }
  }, [isFocused])

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
    if (isComposingRef.current) return
    syncToStore()
  }, [syncToStore])

  const handleCompositionStart = useCallback(() => {
    isComposingRef.current = true
  }, [])

  const handleCompositionEnd = useCallback(() => {
    isComposingRef.current = false
    syncToStore()
  }, [syncToStore])

  const handleFocus = useCallback(() => {
    setFocusedBlock(block.id)
  }, [block.id, setFocusedBlock])

  const handleBlur = useCallback(() => {
    setFocusedBlock(null)
    closeBubbleToolbar()
    syncToStore()
  }, [setFocusedBlock, closeBubbleToolbar, syncToStore])

  const handleMouseUp = useCallback(() => {
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
  }, [openBubbleToolbar, closeBubbleToolbar])

  const handleKeyUp = useCallback((e: React.KeyboardEvent) => {
    // Update bubble toolbar position if selection exists after keyboard navigation
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
  }, [openBubbleToolbar, closeBubbleToolbar])

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    e.preventDefault()
    const text = e.clipboardData.getData('text/plain')
    document.execCommand('insertText', false, text)
  }, [])

  const format = useCallback((formatType: FormatType, linkUrl?: string) => {
    if (!ref.current) return
    ref.current.focus()
    applyFormat(formatType, linkUrl)
    // Sync after format (slight delay to let DOM settle)
    setTimeout(syncToStore, 0)
  }, [syncToStore])

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
  }
}