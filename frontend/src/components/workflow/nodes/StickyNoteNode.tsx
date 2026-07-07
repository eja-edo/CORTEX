import { memo, useCallback, useRef, useState } from 'react'
import { Handle, Position, type NodeProps } from 'reactflow'
import { StickyNote } from 'lucide-react'

type StickyNoteData = {
  label: string
  content?: string
  color?: string
}

const COLORS: { name: string; bg: string; border: string }[] = [
  { name: 'yellow', bg: '#fef9c3', border: '#eab308' },
  { name: 'green', bg: '#dcfce7', border: '#22c55e' },
  { name: 'blue', bg: '#dbeafe', border: '#3b82f6' },
  { name: 'purple', bg: '#f3e8ff', border: '#a855f7' },
  { name: 'pink', bg: '#fce7f3', border: '#ec4899' },
  { name: 'gray', bg: '#f3f4f6', border: '#9ca3af' },
]

export const StickyNoteNode = memo(function StickyNoteNode({ data, selected }: NodeProps<StickyNoteData>) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(data.content ?? '')
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const currentColor = COLORS.find(c => c.name === (data.color ?? 'yellow')) ?? COLORS[0]

  const startEdit = useCallback(() => {
    setDraft(data.content ?? '')
    setEditing(true)
    setTimeout(() => inputRef.current?.focus(), 0)
  }, [data.content])

  const finishEdit = useCallback(() => {
    setEditing(false)
    if (draft !== data.content) {
      data.content = draft
    }
  }, [draft, data])

  return (
    <div
      className="wf-sticky-node"
      style={{
        background: currentColor.bg,
        borderColor: selected ? currentColor.border : 'transparent',
        boxShadow: selected ? `0 0 0 2px ${currentColor.border}` : 'none',
      }}
    >
      {/* Hidden handles so edges don't snap to this node */}
      <Handle type="target" position={Position.Left} className="wf-handle wf-handle--hidden" />
      <Handle type="source" position={Position.Right} className="wf-handle wf-handle--hidden" />

      <div className="wf-sticky-toolbar">
        {COLORS.map(c => (
          <button
            key={c.name}
            type="button"
            className="wf-sticky-color-btn"
            style={{ background: c.bg, border: `2px solid ${c.border}` }}
            onClick={() => { data.color = c.name }}
            title={c.name}
          />
        ))}
      </div>

      {editing ? (
        <textarea
          ref={inputRef}
          className="wf-sticky-textarea"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={finishEdit}
          onKeyDown={e => {
            if (e.key === 'Escape') finishEdit()
          }}
          placeholder="Write your note..."
        />
      ) : (
        <div className="wf-sticky-content" onDoubleClick={startEdit}>
          {data.content ? (
            <pre className="wf-sticky-text">{data.content}</pre>
          ) : (
            <span className="wf-sticky-placeholder">
              <StickyNote size={14} />
              Double-click to edit
            </span>
          )}
        </div>
      )}
    </div>
  )
})
