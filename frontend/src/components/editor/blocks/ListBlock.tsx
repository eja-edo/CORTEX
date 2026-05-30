import { useRef, useEffect, useCallback } from 'react'
import { useEditorStore } from '../../../stores/editorStore'
import { CheckSquare, Square } from 'lucide-react'
import type { BlockNode } from '../../../types/editor'

interface ListBlockProps {
  block: BlockNode
}

export function ListBlock({ block }: ListBlockProps) {
  const ref = useRef<HTMLDivElement>(null)
  const isTask = block.type === 'task_list'
  const isOrdered = block.type === 'ordered_list'
  const nesting = block.meta?.listNesting ?? 0

  const updateBlockContent = useEditorStore(s => s.updateBlockContent)
  const setFocusedBlock = useEditorStore(s => s.setFocusedBlock)
  const focusedBlockId = useEditorStore(s => s.focusedBlockId)
  const splitBlock = useEditorStore(s => s.splitBlock)
  const mergeBlockBackward = useEditorStore(s => s.mergeBlockBackward)
  const blocks = useEditorStore(s => s.blocks)
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

  const handleToggle = useCallback((e: React.MouseEvent) => {
    if (!isTask) return
    e.stopPropagation()
    const newChecked = !(block.meta?.checked ?? false)
    const updateRecursive = (list: BlockNode[]): boolean => {
      for (let i = 0; i < list.length; i++) {
        const b = list[i]
        if (!b) continue
        if (b.id === block.id) {
          list[i] = { ...b, meta: { ...b.meta, checked: newChecked } }
          return true
        }
        if (b.children && updateRecursive(b.children)) return true
      }
      return false
    }
    const newBlocks = structuredClone(blocks)
    updateRecursive(newBlocks)
    useEditorStore.getState().setBlocks(newBlocks)
  }, [block.id, block.meta, isTask, blocks])

  return (
    <div
      className={`block-list-editable`}
      style={{ paddingLeft: nesting * 20 }}
    >
      {isTask && (
        <span className="block-task-checkbox" onClick={handleToggle} contentEditable={false}>
          {block.meta?.checked ? <CheckSquare size={16} /> : <Square size={16} />}
        </span>
      )}
      {!isTask && (
        <span className="block-list-marker" contentEditable={false}>
          {isOrdered ? '1.' : '•'}
        </span>
      )}
      <div
        ref={ref}
        className={`block-editable ${isFocused ? 'block-editable--focused' : ''}`}
        contentEditable="plaintext-only"
        suppressContentEditableWarning
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        onFocus={() => setFocusedBlock(block.id)}
        onBlur={() => setFocusedBlock(null)}
      />
    </div>
  )
}
