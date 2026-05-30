import { useRef, useEffect, useCallback } from 'react'
import { Info, AlertTriangle, Lightbulb, AlertCircle, Ban } from 'lucide-react'
import type { BlockNode } from '../../../types/editor'
import { useEditorStore } from '../../../stores/editorStore'

interface CalloutBlockProps {
  block: BlockNode
}

const CALLOUT_ICONS: Record<string, { icon: typeof Info; color: string }> = {
  NOTE: { icon: Info, color: '#3b82f6' },
  TIP: { icon: Lightbulb, color: '#10b981' },
  WARNING: { icon: AlertTriangle, color: '#f59e0b' },
  IMPORTANT: { icon: AlertCircle, color: '#8b5cf6' },
  CAUTION: { icon: Ban, color: '#ef4444' },
}

export function CalloutBlock({ block }: CalloutBlockProps) {
  const ref = useRef<HTMLDivElement>(null)
  const calloutType = block.meta?.calloutType ?? 'NOTE'
  const calloutConfig = CALLOUT_ICONS[calloutType] ?? CALLOUT_ICONS.NOTE
  const CalloutIcon = calloutConfig.icon
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
    <div className={`block-callout block-callout--${calloutType.toLowerCase()}`}>
      <div className="block-callout-icon" contentEditable={false}>
        <CalloutIcon size={20} style={{ color: calloutConfig.color }} />
      </div>
      <div className="block-callout-content">
        <div className="block-callout-label" contentEditable={false}>{calloutType}</div>
        <div
          ref={ref}
          className={`block-editable ${isFocused ? 'block-editable--focused' : ''}`}
          contentEditable="plaintext-only"
          suppressContentEditableWarning
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          onFocus={() => setFocusedBlock(block.id)}
          onBlur={() => setFocusedBlock(null)}
          data-placeholder="Callout text..."
        />
      </div>
    </div>
  )
}
