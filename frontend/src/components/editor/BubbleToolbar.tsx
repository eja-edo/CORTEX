import { useEffect, useRef, useCallback } from 'react'
import { useEditorStore } from '../../stores/editorStore'
import { Bold, Italic, Underline, Strikethrough, Code, Link } from 'lucide-react'

interface BubbleToolbarProps {
  onFormat?: (format: string) => void
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
        onClick={() => handleFormat('bold')}
      >
        <Bold size={14} />
      </button>
      <button
        type="button"
        className="bubble-toolbar-btn"
        title="Italic (Ctrl+I)"
        onClick={() => handleFormat('italic')}
      >
        <Italic size={14} />
      </button>
      <button
        type="button"
        className="bubble-toolbar-btn"
        title="Underline"
        onClick={() => handleFormat('underline')}
      >
        <Underline size={14} />
      </button>
      <button
        type="button"
        className="bubble-toolbar-btn"
        title="Strikethrough"
        onClick={() => handleFormat('strikethrough')}
      >
        <Strikethrough size={14} />
      </button>
      <div className="bubble-toolbar-sep" />
      <button
        type="button"
        className="bubble-toolbar-btn"
        title="Inline code"
        onClick={() => handleFormat('code')}
      >
        <Code size={14} />
      </button>
      <button
        type="button"
        className="bubble-toolbar-btn"
        title="Link (Ctrl+K)"
        onClick={() => handleFormat('link')}
      >
        <Link size={14} />
      </button>
    </div>
  )
}
