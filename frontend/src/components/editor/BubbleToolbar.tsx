import { useEffect, useRef, useCallback } from 'react'
import { useEditorStore } from '../../stores/editorStore'
import { Bold, Italic, Underline, Strikethrough, Code, Link, Highlighter } from 'lucide-react'

interface BubbleToolbarProps {
  onFormat?: (format: string) => void
}

const MARKDOWN_WRAPPERS: Record<string, [string, string]> = {
  bold: ['**', '**'],
  italic: ['*', '*'],
  underline: ['<u>', '</u>'],
  strikethrough: ['~~', '~~'],
  code: ['`', '`'],
  highlight: ['==', '=='],
}

export function BubbleToolbar({ onFormat }: BubbleToolbarProps) {
  const bubbleToolbar = useEditorStore(s => s.bubbleToolbar)
  const closeBubbleToolbar = useEditorStore(s => s.closeBubbleToolbar)
  const toolbarRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!bubbleToolbar.open) return

    const handleClickOutside = (e: MouseEvent) => {
      if (toolbarRef.current && !toolbarRef.current.contains(e.target as Node)) {
        closeBubbleToolbar()
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [bubbleToolbar.open, closeBubbleToolbar])

  useEffect(() => {
    if (!bubbleToolbar.open) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeBubbleToolbar()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [bubbleToolbar.open, closeBubbleToolbar])

  const handleFormat = useCallback((format: string) => {
    const sel = window.getSelection()
    if (!sel || sel.isCollapsed || !sel.rangeCount) {
      closeBubbleToolbar()
      return
    }

    const blockEl = (sel.anchorNode as HTMLElement)?.closest?.('[contenteditable]') as HTMLElement | null
    if (!blockEl) {
      closeBubbleToolbar()
      return
    }

    const { focusedBlockId, updateBlockContent } = useEditorStore.getState()
    if (!focusedBlockId) {
      closeBubbleToolbar()
      return
    }

    const text = blockEl.textContent || ''
    const startOffset = sel.getRangeAt(0).startOffset
    const endOffset = sel.getRangeAt(0).endOffset

    if (startOffset >= endOffset) {
      closeBubbleToolbar()
      return
    }

    const selected = text.slice(startOffset, endOffset)
    if (!selected) {
      closeBubbleToolbar()
      return
    }

    let newText: string
    if (format === 'link') {
      const url = prompt('Enter URL:', 'https://')
      if (!url) {
        closeBubbleToolbar()
        return
      }
      newText = text.slice(0, startOffset) + `[${selected}](${url})` + text.slice(endOffset)
    } else {
      const [before, after] = MARKDOWN_WRAPPERS[format] || ['', '']
      if (!before) return
      newText = text.slice(0, startOffset) + before + selected + after + text.slice(endOffset)
    }

    blockEl.textContent = newText
    updateBlockContent(focusedBlockId, newText)

    const textNode = blockEl.firstChild
    if (textNode) {
      const cursorPos = newText.length
      const newRange = document.createRange()
      newRange.setStart(textNode, cursorPos)
      newRange.setEnd(textNode, cursorPos)
      sel.removeAllRanges()
      sel.addRange(newRange)
    }

    onFormat?.(format)
    closeBubbleToolbar()
  }, [onFormat, closeBubbleToolbar])

  if (!bubbleToolbar.open || !bubbleToolbar.position) return null

  return (
    <div
      ref={toolbarRef}
      className="bubble-toolbar"
      style={{
        position: 'fixed',
        left: bubbleToolbar.position.x,
        top: bubbleToolbar.position.y - 40,
      }}
      contentEditable={false}
    >
      <button
        type="button"
        className="bubble-toolbar-btn"
        title="Bold (Ctrl+B)"
        onMouseDown={(e) => { e.preventDefault(); handleFormat('bold') }}
      >
        <Bold size={14} />
      </button>
      <button
        type="button"
        className="bubble-toolbar-btn"
        title="Italic (Ctrl+I)"
        onMouseDown={(e) => { e.preventDefault(); handleFormat('italic') }}
      >
        <Italic size={14} />
      </button>
      <button
        type="button"
        className="bubble-toolbar-btn"
        title="Underline"
        onMouseDown={(e) => { e.preventDefault(); handleFormat('underline') }}
      >
        <Underline size={14} />
      </button>
      <button
        type="button"
        className="bubble-toolbar-btn"
        title="Strikethrough"
        onMouseDown={(e) => { e.preventDefault(); handleFormat('strikethrough') }}
      >
        <Strikethrough size={14} />
      </button>
      <div className="bubble-toolbar-sep" />
      <button
        type="button"
        className="bubble-toolbar-btn"
        title="Inline code"
        onMouseDown={(e) => { e.preventDefault(); handleFormat('code') }}
      >
        <Code size={14} />
      </button>
      <button
        type="button"
        className="bubble-toolbar-btn"
        title="Highlight"
        onMouseDown={(e) => { e.preventDefault(); handleFormat('highlight') }}
      >
        <Highlighter size={14} />
      </button>
      <button
        type="button"
        className="bubble-toolbar-btn"
        title="Link (Ctrl+K)"
        onMouseDown={(e) => { e.preventDefault(); handleFormat('link') }}
      >
        <Link size={14} />
      </button>
    </div>
  )
}
