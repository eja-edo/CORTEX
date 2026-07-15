import { useState, useRef, useEffect, useCallback, useContext } from 'react'
import { ChevronRight } from 'lucide-react'
import type { BlockNode } from '../../../types/editor'
import { useEditorStore } from '../../../stores/editorStore'
import { BlockRenderer } from '../BlockRenderer'
import { ReadOnlyCtx } from '../EditorSurface'

interface ToggleBlockProps {
  block: BlockNode
}

export function ToggleBlock({ block }: ToggleBlockProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [isOpen, setIsOpen] = useState(false)
  const readOnly = useContext(ReadOnlyCtx)
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
    if (!readOnly && isFocused && ref.current) {
      ref.current.focus()
    }
  }, [isFocused, readOnly])

  const handleInput = useCallback((e: React.FormEvent<HTMLDivElement>) => {
    if (readOnly) return
    const text = (e.target as HTMLDivElement).textContent ?? ''
    updateBlockContent(block.id, text)
  }, [block.id, updateBlockContent, readOnly])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (readOnly) return
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
  }, [block.id, splitBlock, mergeBlockBackward, readOnly])

  return (
    <div className="block-toggle">
      <div className="block-toggle-header">
        <span
          contentEditable={false}
          className="block-toggle-chevron-wrap"
          onClick={() => setIsOpen(!isOpen)}
        >
          <ChevronRight
            size={16}
            className={`block-toggle-chevron ${isOpen ? 'open' : ''}`}
          />
        </span>
        <div
          ref={ref}
          className={`block-editable ${isFocused ? 'block-editable--focused' : ''}`}
          contentEditable={readOnly ? "false" : "plaintext-only"}
          suppressContentEditableWarning
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          onFocus={() => { if (!readOnly) setFocusedBlock(block.id) }}
          onBlur={() => { if (!readOnly) setFocusedBlock(null) }}
          data-placeholder="Toggle title..."
        />
      </div>
      {isOpen && block.children && block.children.length > 0 && (
        <div className="block-toggle-content">
          {block.children.map(child => (
            <BlockRenderer key={child.id} block={child} />
          ))}
        </div>
      )}
    </div>
  )
}
