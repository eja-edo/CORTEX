import { useRef, useEffect, useCallback } from 'react'
import type { BlockNode } from '../../../types/editor'
import { useEditorStore } from '../../../stores/editorStore'

interface HeadingBlockProps {
  block: BlockNode
}

export function HeadingBlock({ block }: HeadingBlockProps) {
  const ref = useRef<HTMLDivElement>(null)
  const level = block.type === 'heading_1' ? 1 : block.type === 'heading_2' ? 2 : 3
  const updateBlockContent = useEditorStore(s => s.updateBlockContent)
  const setFocusedBlock = useEditorStore(s => s.setFocusedBlock)
  const focusedBlockId = useEditorStore(s => s.focusedBlockId)
  const splitBlock = useEditorStore(s => s.splitBlock)
  const mergeBlockBackward = useEditorStore(s => s.mergeBlockBackward)
  const isFocused = focusedBlockId === block.id

  useEffect(() => {
    if (ref.current && ref.current.textContent !== block.content) {
      ref.current.textContent = block.content
    }
  }, [block.content])

  useEffect(() => {
    if (isFocused && ref.current) {
      ref.current.focus()
    }
  }, [isFocused])

  const handleInput = useCallback((e: React.FormEvent<HTMLDivElement>) => {
    const text = (e.target as HTMLDivElement).textContent ?? ''
    updateBlockContent(block.id, text)
  }, [block.id, updateBlockContent])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    const text = ref.current?.textContent ?? ''

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
  }, [block.id, splitBlock, mergeBlockBackward])

  return (
    <div
      ref={ref}
      className={`block-heading-editable block-editable heading-level-${level} ${isFocused ? 'block-editable--focused' : ''}`}
      contentEditable="plaintext-only"
      suppressContentEditableWarning
      onInput={handleInput}
      onKeyDown={handleKeyDown}
      onFocus={() => setFocusedBlock(block.id)}
      onBlur={() => setFocusedBlock(null)}
    />
  )
}
