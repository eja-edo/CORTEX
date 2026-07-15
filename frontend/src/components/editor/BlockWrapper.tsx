import { useCallback, useContext, type ReactNode } from 'react'
import { useEditorStore } from '../../stores/editorStore'
import { GripVertical, Plus } from 'lucide-react'
import type { BlockNode, SyntheticListenerMap } from '../../types/editor'
import { ReadOnlyCtx } from './EditorSurface'

interface BlockWrapperProps {
  block: BlockNode
  children: ReactNode
  dragHandleListeners?: SyntheticListenerMap
}

export function BlockWrapper({ block, children, dragHandleListeners }: BlockWrapperProps) {
  const openSlashMenu = useEditorStore(s => s.openSlashMenu)
  const readOnly = useContext(ReadOnlyCtx)

  const handleAddBelow = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    openSlashMenu(block.id, e.clientX, e.clientY)
  }, [block.id, openSlashMenu])

  return (
    <div
      className="editor-block"
      data-block-id={block.id}
      data-block-type={block.type}
    >
      {!readOnly && (
        <div className="editor-block-gutter" contentEditable={false}>
          <button
            type="button"
            className="editor-block-drag-handle"
            tabIndex={-1}
            aria-label="Drag block"
            {...dragHandleListeners}
          >
            <GripVertical size={14} />
          </button>
          <button
            type="button"
            className="editor-block-add-btn"
            tabIndex={-1}
            aria-label="Add block below"
            onClick={handleAddBelow}
          >
            <Plus size={12} />
          </button>
        </div>
      )}
      <div className="editor-block-content">
        {children}
      </div>
    </div>
  )
}
