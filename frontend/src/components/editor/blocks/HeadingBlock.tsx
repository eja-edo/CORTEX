import { useCallback } from 'react'
import type { BlockNode } from '../../../types/editor'
import { useEditorStore } from '../../../stores/editorStore'
import { useRichTextBlock } from '../../../hooks/useRichTextBlock'

interface HeadingBlockProps {
  block: BlockNode
}

export function HeadingBlock({ block }: HeadingBlockProps) {
  const level = Number(block.type.split('_')[1]) || 3
  const splitBlock = useEditorStore(s => s.splitBlock)
  const mergeBlockBackward = useEditorStore(s => s.mergeBlockBackward)

  const {
    ref,
    isFocused,
    readOnly,
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
    if (readOnly) return
    const text = e.currentTarget.textContent ?? ''

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      splitBlock(block.id, text, '')
      return
    }

    if (e.key === 'Backspace' && text === '' && !e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault()
      mergeBlockBackward(block.id)
      return
    }

    if (e.metaKey || e.ctrlKey) {
      if (e.key.toLowerCase() === 'b') {
        e.preventDefault()
        document.execCommand('bold', false)
      } else if (e.key.toLowerCase() === 'i') {
        e.preventDefault()
        document.execCommand('italic', false)
      }
    }
  }, [block.id, splitBlock, mergeBlockBackward, readOnly])

  return (
    <div
      ref={ref}
      className={`block-heading-editable block-editable block-richtext heading-level-${level} ${isFocused ? 'block-editable--focused' : ''}`}
      contentEditable={!readOnly}
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
