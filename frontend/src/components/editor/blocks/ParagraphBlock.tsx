import { useRef, useEffect, useCallback } from 'react'
import type { BlockNode } from '../../../types/editor'
import { useEditorStore } from '../../../stores/editorStore'

interface ParagraphBlockProps {
  block: BlockNode
}

export function ParagraphBlock({ block }: ParagraphBlockProps) {
  const ref = useRef<HTMLDivElement>(null)
  const updateBlockContent = useEditorStore(s => s.updateBlockContent)
  const setFocusedBlock = useEditorStore(s => s.setFocusedBlock)
  const focusedBlockId = useEditorStore(s => s.focusedBlockId)
  const splitBlock = useEditorStore(s => s.splitBlock)
  const mergeBlockBackward = useEditorStore(s => s.mergeBlockBackward)
  const openSlashMenu = useEditorStore(s => s.openSlashMenu)
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

    if (e.key === '/' && text === '' && !e.shiftKey && !e.metaKey && !e.ctrlKey) {
      e.preventDefault()
      const rect = ref.current?.getBoundingClientRect()
      if (rect) {
        openSlashMenu(block.id, rect.left, rect.bottom)
      }
    }
  }, [block.id, splitBlock, mergeBlockBackward, openSlashMenu])

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    e.preventDefault()
    const text = e.clipboardData.getData('text/plain')
    document.execCommand('insertText', false, text)
  }, [])

  return (
    <div
      ref={ref}
      className={`block-paragraph block-editable ${isFocused ? 'block-editable--focused' : ''}`}
      contentEditable="plaintext-only"
      suppressContentEditableWarning
      onInput={handleInput}
      onKeyDown={handleKeyDown}
      onFocus={() => setFocusedBlock(block.id)}
      onBlur={() => setFocusedBlock(null)}
      onPaste={handlePaste}
    />
  )
}
