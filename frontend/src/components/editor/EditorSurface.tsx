import { useEffect, useCallback, useRef, useMemo, useLayoutEffect } from 'react'
import { DndContext, closestCenter, PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useEditorStore } from '../../stores/editorStore'
import type { BlockNode, SyntheticListenerMap } from '../../types/editor'
import { BlockRenderer } from './BlockRenderer'
import { SlashMenu } from './SlashMenu'
import { BubbleToolbar } from './BubbleToolbar'

interface EditorSurfaceProps {
  initialMd: string
  noteId?: string
  onSave: (md: string) => void
}

function SortableBlock({ block }: { block: BlockNode }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: block.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }

  return (
    <div ref={setNodeRef} style={style} {...attributes}>
      <BlockRenderer block={block} dragHandleListeners={listeners as SyntheticListenerMap} />
    </div>
  )
}

export function EditorSurface({ initialMd, noteId, onSave }: EditorSurfaceProps) {
  const blocks = useEditorStore(s => s.blocks)
  const initializeFromMarkdown = useEditorStore(s => s.initializeFromMarkdown)
  const focusedBlockId = useEditorStore(s => s.focusedBlockId)
  const serializeAndNotify = useEditorStore(s => s.serializeAndNotify)
  const closeSlashMenu = useEditorStore(s => s.closeSlashMenu)
  const reorderBlock = useEditorStore(s => s.reorderBlock)

  const surfaceRef = useRef<HTMLDivElement>(null)
  const prevMdRef = useRef<string | null>(null)
  const lastSerializedMdRef = useRef<string | null>(null)
  const suppressAutoSaveRef = useRef(false)

  // Initialize blocks from markdown when content changes externally
  // Skip re-init while user is focused on a block
  // Also skip if the markdown was just serialized from blocks (avoid circular sync)
  useEffect(() => {
    if (initialMd !== prevMdRef.current && !focusedBlockId) {
      if (initialMd === lastSerializedMdRef.current) {
        prevMdRef.current = initialMd
        return
      }
      prevMdRef.current = initialMd
      suppressAutoSaveRef.current = true
      initializeFromMarkdown(initialMd, noteId)
    }
  }, [initialMd, initializeFromMarkdown, focusedBlockId, noteId])

  const onSaveRef = useRef(onSave)
  useLayoutEffect(() => {
    onSaveRef.current = onSave
  })

  // Ctrl+S to save
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault()
        serializeAndNotify((md) => {
          lastSerializedMdRef.current = md
          onSaveRef.current(md)
        })
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [serializeAndNotify])

  // Debounced auto-save when blocks change
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prevBlocksRef = useRef<string>('')

  useEffect(() => {
    // Suppress auto-save after blocks were re-initialized from external markdown
    if (suppressAutoSaveRef.current) {
      suppressAutoSaveRef.current = false
      return
    }

    const serialized = JSON.stringify(blocks)
    if (serialized === prevBlocksRef.current) return
    prevBlocksRef.current = serialized

    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      serializeAndNotify((md) => {
        lastSerializedMdRef.current = md
        onSaveRef.current(md)
      })
    }, 2000)
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    }
  }, [blocks, serializeAndNotify])

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },
    }),
  )

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return

    const oldIndex = blocks.findIndex(b => b.id === active.id)
    const newIndex = blocks.findIndex(b => b.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return

    reorderBlock(oldIndex, newIndex)
  }, [blocks, reorderBlock])

  const blockIds = useMemo(() => blocks.map(b => b.id), [blocks])

  return (
    <div
      ref={surfaceRef}
      className="editor-surface"
      onClick={() => closeSlashMenu()}
    >
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext items={blockIds} strategy={verticalListSortingStrategy}>
          <div className="editor-block-list">
            {blocks.map(block => (
              <SortableBlock key={block.id} block={block} />
            ))}
          </div>
        </SortableContext>
      </DndContext>

      {blocks.length === 0 && (
        <div className="editor-empty-state">
          Empty block. Start typing...
        </div>
      )}

      <SlashMenu />
      <BubbleToolbar onFormat={() => {}} />
    </div>
  )
}