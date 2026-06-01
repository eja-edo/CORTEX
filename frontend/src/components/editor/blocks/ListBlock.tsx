import { useCallback } from 'react'
import { useEditorStore } from '../../../stores/editorStore'
import { CheckSquare, Square } from 'lucide-react'
import type { BlockNode } from '../../../types/editor'
import { useRichTextBlock } from '../../../hooks/useRichTextBlock'

interface ListBlockProps {
  block: BlockNode
  order?: number
}

export function ListBlock({ block, order }: ListBlockProps) {
  const isTask = block.type === 'task_list'
  const isOrdered = block.type === 'ordered_list'
  const nesting = block.meta?.listNesting ?? 0

  const splitBlock = useEditorStore(s => s.splitBlock)
  const mergeBlockBackward = useEditorStore(s => s.mergeBlockBackward)
  const exitListOnEmpty = useEditorStore(s => s.exitListOnEmpty)
  const blocks = useEditorStore(s => s.blocks)

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
    const text = e.currentTarget.textContent ?? ''

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (text.trim() === '') {
        exitListOnEmpty(block.id)
        return
      }
      splitBlock(block.id, text, '')
      return
    }

    if (e.key === 'Backspace' && text === '' && !e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault()
      mergeBlockBackward(block.id)
      return
    }

    // Keyboard shortcuts
    if (e.metaKey || e.ctrlKey) {
      if (e.key.toLowerCase() === 'b') {
        e.preventDefault()
        document.execCommand('bold', false)
      } else if (e.key.toLowerCase() === 'i') {
        e.preventDefault()
        document.execCommand('italic', false)
      }
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
        <span
          className="block-task-checkbox"
          onClick={handleToggle}
          contentEditable={false}
        >
          {block.meta?.checked ? <CheckSquare size={16} /> : <Square size={16} />}
        </span>
      )}
      {!isTask && (
        <span className="block-list-marker" contentEditable={false}>
          {isOrdered ? `${order ?? 1}.` : '•'}
        </span>
      )}
      <div
        ref={ref}
        className={`block-editable block-richtext ${isFocused ? 'block-editable--focused' : ''}`}
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
    </div>
  )
}