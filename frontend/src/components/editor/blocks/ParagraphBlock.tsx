import { useCallback } from 'react'
import type { BlockNode } from '../../../types/editor'
import { useEditorStore } from '../../../stores/editorStore'
import { useRichTextBlock } from '../../../hooks/useRichTextBlock'

interface ParagraphBlockProps {
  block: BlockNode
}

export function ParagraphBlock({ block }: ParagraphBlockProps) {
  const splitBlock = useEditorStore(s => s.splitBlock)
  const mergeBlockBackward = useEditorStore(s => s.mergeBlockBackward)
  const openSlashMenu = useEditorStore(s => s.openSlashMenu)

  const {
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
  } = useRichTextBlock({ block })

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    const text = el.textContent ?? ''

    // Slash menu: only when empty
    if (e.key === '/' && text === '' && !e.shiftKey && !e.metaKey && !e.ctrlKey) {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      openSlashMenu(block.id, rect.left, rect.bottom)
      return
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      // Split at current cursor: get text before/after selection
      const selection = window.getSelection()
      if (selection && selection.rangeCount > 0) {
        const range = selection.getRangeAt(0)
        // Get text before cursor
        const beforeRange = document.createRange()
        beforeRange.setStart(el, 0)
        beforeRange.setEnd(range.startContainer, range.startOffset)
        const beforeText = beforeRange.toString()
        const afterText = text.slice(beforeText.length)
        splitBlock(block.id, beforeText, afterText)
      } else {
        splitBlock(block.id, text, '')
      }
      return
    }

    if (e.key === 'Backspace' && text === '' && !e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault()
      mergeBlockBackward(block.id)
      return
    }

    // Keyboard shortcuts for formatting
    if (e.metaKey || e.ctrlKey) {
      switch (e.key.toLowerCase()) {
        case 'b':
          e.preventDefault()
          document.execCommand('bold', false)
          break
        case 'i':
          e.preventDefault()
          document.execCommand('italic', false)
          break
        case 'k': {
          e.preventDefault()
          const url = window.prompt('URL:', 'https://')
          if (url) {
            const sel = window.getSelection()
            if (sel && !sel.isCollapsed) {
              const a = document.createElement('a')
              a.href = url
              a.target = '_blank'
              a.rel = 'noopener noreferrer'
              const range = sel.getRangeAt(0)
              try {
                range.surroundContents(a)
              } catch {
                const fragment = range.extractContents()
                a.appendChild(fragment)
                range.insertNode(a)
              }
              sel.removeAllRanges()
            }
          }
          break
        }
      }
    }
  }, [block.id, splitBlock, mergeBlockBackward, openSlashMenu])

  return (
    <div
      ref={ref}
      className={`block-paragraph block-editable block-richtext ${isFocused ? 'block-editable--focused' : ''}`}
      contentEditable="true"
      suppressContentEditableWarning
      onInput={handleInput}
      onCompositionStart={handleCompositionStart}
      onCompositionEnd={handleCompositionEnd}
      onKeyDown={handleKeyDown}
      onKeyUp={handleKeyUp}
      onFocus={handleFocus}
      onBlur={handleBlur}
      onMouseUp={handleMouseUp}
      onPaste={handlePaste}
    />
  )
}