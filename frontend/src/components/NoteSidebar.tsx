import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Bold, Check, ChevronRight, Code, Italic, Link, Minus, Plus, Search, Trash2, Type, X } from 'lucide-react'
import MarkdownIt from 'markdown-it'
import { plainTextFromMarkdown } from '../utils/noteMarkdown'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: true,
})

export type NoteItem = {
  id: string
  date: string
  contentMd: string
  parentNoteId?: string | null
}

interface NoteSidebarProps {
  notes: NoteItem[]
  onNoteChange: (id: string, contentMd: string) => void
  onCreateNote: (parentNoteId?: string) => void
  onMoveNote?: (noteId: string, parentNoteId: string | null) => Promise<void> | void
  onDeleteNote?: (id: string) => void
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function getTitleFromMd(md: string): string {
  const plain = plainTextFromMarkdown(md)
  return plain.split('\n').find(l => l.trim()) || 'Untitled'
}

function highlightMatch(text: string, query: string): string {
  if (!query.trim()) return escapeHtml(text)
  const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const regex = new RegExp(`(${escapedQuery})`, 'gi')
  return escapeHtml(text).replace(regex, '<mark class="note-search-highlight">$1</mark>')
}

// ── Markdown toolbar helpers ──────────────────────────────────

function wrapSelection(
  textarea: HTMLTextAreaElement,
  before: string,
  after: string,
  placeholder: string,
  onChange: (val: string) => void,
) {
  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  const selected = textarea.value.slice(start, end) || placeholder
  const newVal =
    textarea.value.slice(0, start) + before + selected + after + textarea.value.slice(end)
  onChange(newVal)
  window.requestAnimationFrame(() => {
    textarea.focus()
    textarea.selectionStart = start + before.length
    textarea.selectionEnd = start + before.length + selected.length
  })
}

function insertLinePrefix(
  textarea: HTMLTextAreaElement,
  prefix: string,
  onChange: (val: string) => void,
) {
  const start = textarea.selectionStart
  const lineStart = textarea.value.lastIndexOf('\n', start - 1) + 1
  const newVal =
    textarea.value.slice(0, lineStart) + prefix + textarea.value.slice(lineStart)
  onChange(newVal)
  window.requestAnimationFrame(() => {
    textarea.focus()
    textarea.selectionStart = start + prefix.length
    textarea.selectionEnd = start + prefix.length
  })
}

function insertLink(textarea: HTMLTextAreaElement, onChange: (val: string) => void) {
  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  const selected = textarea.value.slice(start, end)
  const linkText = selected || 'link text'
  const insertion = `[${linkText}](url)`
  const newVal = textarea.value.slice(0, start) + insertion + textarea.value.slice(end)
  onChange(newVal)
  window.requestAnimationFrame(() => {
    textarea.focus()
    // Select "url" for easy replacement
    const urlStart = start + linkText.length + 3
    textarea.selectionStart = urlStart
    textarea.selectionEnd = urlStart + 3
  })
}

// ── Mini toolbar component ────────────────────────────────────

function MiniToolbar({
  textareaRef,
  onChange,
}: {
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
  onChange: (val: string) => void
}) {
  const act = (fn: (ta: HTMLTextAreaElement) => void) => {
    if (textareaRef.current) fn(textareaRef.current)
  }

  const tools: Array<{ icon: ReactNode; title: string; action: (ta: HTMLTextAreaElement) => void }> = [
    { icon: <Bold size={11} />, title: 'Bold', action: ta => wrapSelection(ta, '**', '**', 'bold', onChange) },
    { icon: <Italic size={11} />, title: 'Italic', action: ta => wrapSelection(ta, '*', '*', 'italic', onChange) },
    { icon: <Code size={11} />, title: 'Inline code', action: ta => wrapSelection(ta, '`', '`', 'code', onChange) },
    { icon: <Link size={11} />, title: 'Link', action: ta => insertLink(ta, onChange) },
    { icon: <Type size={11} />, title: 'Heading', action: ta => insertLinePrefix(ta, '## ', onChange) },
    { icon: <Minus size={11} />, title: 'Divider', action: ta => wrapSelection(ta, '\n---\n', '', '', onChange) },
  ]

  return (
    <div className="note-mini-toolbar">
      {tools.map(t => (
        <button
          key={t.title}
          type="button"
          className="note-mini-toolbar-btn"
          title={t.title}
          onMouseDown={e => {
            e.preventDefault() // keep focus in textarea
            act(t.action)
          }}
        >
          {t.icon}
        </button>
      ))}
    </div>
  )
}

// ── NoteCardItem ──────────────────────────────────────────────

function NoteCardItem({
  note,
  hasChildren,
  isBranchCollapsed,
  onToggleBranch,
  isExpanded,
  onExpand,
  onCollapse,
  onNoteChange,
  onDeleteNote,
  onCreateNote,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDrop,
  isDragging,
  isDragTarget,
  searchQuery,
  depth,
}: {
  note: NoteItem
  hasChildren: boolean
  isBranchCollapsed: boolean
  onToggleBranch: () => void
  isExpanded: boolean
  onExpand: () => void
  onCollapse: () => void
  onNoteChange: (id: string, md: string) => void
  onDeleteNote?: (id: string) => void
  onCreateNote: (parentNoteId: string) => void
  onDragStart: () => void
  onDragEnd: () => void
  onDragOver: (event: React.DragEvent) => void
  onDrop: (event: React.DragEvent) => void
  isDragging: boolean
  isDragTarget: boolean
  searchQuery: string
  depth: number
}) {
  const cardRef = useRef<HTMLElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const summaryButtonRef = useRef<HTMLButtonElement>(null)
  const dragPreviewRef = useRef<HTMLElement | null>(null)
  const autosaveTimerRef = useRef<number | null>(null)
  const [localMd, setLocalMd] = useState(note.contentMd)
  const expandId = `note-expand-${note.id}`
  const title = getTitleFromMd(note.contentMd)

  useEffect(() => {
    if (!isExpanded) {
      setLocalMd(note.contentMd)
    }
  }, [note.contentMd, isExpanded])

  useEffect(() => {
    if (isExpanded) {
      setLocalMd(note.contentMd)
      window.requestAnimationFrame(() => {
        if (textareaRef.current) {
          textareaRef.current.focus()
          autoResize(textareaRef.current)
        }
      })
    }
  }, [isExpanded])

  useEffect(() => {
    return () => {
      if (autosaveTimerRef.current) {
        window.clearTimeout(autosaveTimerRef.current)
        autosaveTimerRef.current = null
      }
      if (dragPreviewRef.current) {
        dragPreviewRef.current.remove()
        dragPreviewRef.current = null
      }
    }
  }, [])

  const autoResize = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 300) + 'px'
  }

  const queueAutosave = useCallback((value: string) => {
    if (autosaveTimerRef.current) {
      window.clearTimeout(autosaveTimerRef.current)
    }
    autosaveTimerRef.current = window.setTimeout(() => {
      onNoteChange(note.id, value)
      autosaveTimerRef.current = null
    }, 350)
  }, [note.id, onNoteChange])

  const flushAutosave = useCallback((value: string) => {
    if (autosaveTimerRef.current) {
      window.clearTimeout(autosaveTimerRef.current)
      autosaveTimerRef.current = null
    }
    onNoteChange(note.id, value)
  }, [note.id, onNoteChange])

  const handleLocalChange = useCallback((newVal: string) => {
    setLocalMd(newVal)
    queueAutosave(newVal)
    if (textareaRef.current) {
      textareaRef.current.value = newVal
      autoResize(textareaRef.current)
    }
  }, [queueAutosave])

  const collapseAndSave = useCallback(() => {
    flushAutosave(localMd)
    const active = document.activeElement
    if (active instanceof HTMLElement && cardRef.current?.contains(active)) active.blur()
    onCollapse()
    window.requestAnimationFrame(() => summaryButtonRef.current?.focus())
  }, [flushAutosave, localMd, onCollapse])

  useEffect(() => {
    if (!isExpanded) return
    const onPointerDown = (e: PointerEvent) => {
      if (cardRef.current?.contains(e.target as Node)) return
      collapseAndSave()
    }
    document.addEventListener('pointerdown', onPointerDown, true)
    return () => document.removeEventListener('pointerdown', onPointerDown, true)
  }, [isExpanded, collapseAndSave])

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!onDeleteNote) return
    if (window.confirm(`Xóa note "${title}"?`)) onDeleteNote(note.id)
  }

  const renderedHtml = md.render(note.contentMd || '_Chưa có nội dung_')
  const emoji = note.contentMd.includes('**') ? '📋' : note.contentMd.includes('http') ? '🔗' : '📝'

  const handleDragStart = (event: React.DragEvent) => {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', note.id)

    const source = cardRef.current
    if (source) {
      const rect = source.getBoundingClientRect()
      const preview = source.cloneNode(true) as HTMLElement
      preview.classList.remove('note-card--dragging')
      preview.style.position = 'fixed'
      preview.style.top = '-10000px'
      preview.style.left = '-10000px'
      preview.style.width = `${Math.ceil(rect.width)}px`
      preview.style.maxWidth = `${Math.ceil(rect.width)}px`
      preview.style.margin = '0'
      preview.style.pointerEvents = 'none'
      preview.style.opacity = '1'
      preview.style.transform = 'none'
      preview.style.background = 'var(--bg-secondary)'
      preview.style.boxShadow = 'var(--shadow-sm)'
      preview.style.zIndex = '9999'
      document.body.appendChild(preview)
      dragPreviewRef.current = preview

      event.dataTransfer.setDragImage(preview, 20, 20)

      window.setTimeout(() => {
        if (dragPreviewRef.current) {
          dragPreviewRef.current.remove()
          dragPreviewRef.current = null
        }
      }, 0)
    }

    // Small delay so the ghost image captures before opacity change
    window.setTimeout(onDragStart, 0)
  }

  return (
    <article
      ref={cardRef}
      className={[
        'note-card',
        isExpanded ? 'note-card--expanded' : '',
        depth > 0 ? 'note-card--child' : '',
        isDragging ? 'note-card--dragging' : '',
        isDragTarget ? 'note-card--drop-target' : '',
      ].filter(Boolean).join(' ')}
      style={{ marginLeft: depth * 14 }}
      draggable
      onDragStart={handleDragStart}
      onDragEnd={onDragEnd}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <div style={{ display: 'flex', alignItems: 'center' }}>
        {hasChildren ? (
          <button
            type="button"
            className="note-branch-toggle"
            aria-label={isBranchCollapsed ? 'Expand branch' : 'Collapse branch'}
            onClick={(e) => { e.stopPropagation(); onToggleBranch() }}
          >
            <ChevronRight size={12} className={isBranchCollapsed ? '' : 'expanded'} />
          </button>
        ) : (
          <span className="note-branch-toggle-spacer" />
        )}
        <button
          ref={summaryButtonRef}
          type="button"
          className="note-card-summary-btn"
          style={{ flex: 1 }}
          aria-expanded={isExpanded}
          aria-controls={expandId}
          onClick={isExpanded ? collapseAndSave : onExpand}
        >
          <span className="note-icon">{emoji}</span>
          <div className="note-card-info">
            {searchQuery ? (
              <div className="note-card-title" dangerouslySetInnerHTML={{ __html: highlightMatch(title, searchQuery) }} />
            ) : (
              <div className="note-card-title">{title}</div>
            )}
            <div className="note-card-date">{note.date}</div>
          </div>
        </button>
        {onDeleteNote && (
          <button type="button" className="note-toolbar-btn" title="Xóa note" onClick={handleDelete} style={{ marginRight: 6, flexShrink: 0, color: 'var(--text-tertiary)' }}>
            <Trash2 size={13} />
          </button>
        )}
      </div>

      <div id={expandId} className="note-expandable" aria-hidden={!isExpanded} inert={!isExpanded}>
        <div className="note-expandable-inner">
          <div className="note-editor-wrap">
            {isExpanded ? (
              <div className="note-md-edit-area">
                {/* Mini toolbar */}
                <MiniToolbar textareaRef={textareaRef} onChange={handleLocalChange} />
                <textarea
                  ref={textareaRef}
                  className="note-md-textarea"
                  value={localMd}
                  placeholder="Write markdown…"
                  onChange={(e) => {
                    handleLocalChange(e.target.value)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Tab') {
                      e.preventDefault()
                      const el = e.currentTarget
                      const start = el.selectionStart
                      const end = el.selectionEnd
                      const newVal = localMd.slice(0, start) + '  ' + localMd.slice(end)
                      handleLocalChange(newVal)
                      window.requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = start + 2 })
                    }
                    if (e.key === 'Escape') collapseAndSave()
                  }}
                  spellCheck={false}
                />
                <div className="note-md-edit-hint">Markdown · Tab=2sp · Esc lưu</div>
              </div>
            ) : (
              <div className="note-md-preview" dangerouslySetInnerHTML={{ __html: renderedHtml }} />
            )}

            <div className="note-toolbar" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
              <button type="button" className="note-toolbar-btn" title="Add sub-note" onClick={(e) => { e.stopPropagation(); onCreateNote(note.id) }}>
                <Plus size={13} />
              </button>
              {onDeleteNote && (
                <>
                  <button type="button" className="note-toolbar-btn" title="Xóa" onClick={handleDelete} style={{ color: 'var(--red)' }}>
                    <Trash2 size={13} />
                  </button>
                  <div className="note-toolbar-sep" />
                </>
              )}
              <div className="note-toolbar-spacer" />
              <button type="button" className="note-done-btn" onClick={collapseAndSave}>
                <Check size={12} /> Done
              </button>
            </div>
          </div>
        </div>
      </div>
    </article>
  )
}

// ── NoteSidebar ───────────────────────────────────────────────

export function NoteSidebar({ notes, onNoteChange, onCreateNote, onMoveNote, onDeleteNote }: NoteSidebarProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [isSearchOpen, setIsSearchOpen] = useState(false)
  const [collapsedBranchIds, setCollapsedBranchIds] = useState<Set<string>>(new Set())
  const [draggingNoteId, setDraggingNoteId] = useState<string | null>(null)
  const [dropTargetId, setDropTargetId] = useState<string | 'root' | null>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const collapseExpanded = useCallback(() => setExpandedId(null), [])
  const disableBranchCollapse = searchQuery.trim().length > 0

  const noteMap = useMemo(() => new Map(notes.map((n) => [n.id, n] as const)), [notes])

  const visibleNoteIds = useMemo(() => {
    if (!searchQuery.trim()) return new Set(notes.map((n) => n.id))
    const query = searchQuery.toLowerCase()
    const visible = new Set<string>()
    for (const note of notes) {
      const plain = plainTextFromMarkdown(note.contentMd).toLowerCase()
      if (!plain.includes(query)) continue
      let current: NoteItem | undefined = note
      while (current) {
        if (visible.has(current.id)) break
        visible.add(current.id)
        current = current.parentNoteId ? noteMap.get(current.parentNoteId) : undefined
      }
    }
    return visible
  }, [notes, searchQuery, noteMap])

  const visibleNotesByParent = useMemo(() => {
    const map = new Map<string | null, NoteItem[]>()
    for (const note of notes) {
      if (!visibleNoteIds.has(note.id)) continue
      const key = note.parentNoteId ?? null
      const bucket = map.get(key)
      if (bucket) bucket.push(note)
      else map.set(key, [note])
    }
    return map
  }, [notes, visibleNoteIds])

  const descendantIdsByNote = useMemo(() => {
    const childrenByParent = new Map<string | null, string[]>()
    for (const note of notes) {
      const key = note.parentNoteId ?? null
      const bucket = childrenByParent.get(key)
      if (bucket) bucket.push(note.id)
      else childrenByParent.set(key, [note.id])
    }
    const descendants = new Map<string, Set<string>>()
    for (const note of notes) {
      const seen = new Set<string>()
      const stack = [...(childrenByParent.get(note.id) ?? [])]
      while (stack.length) {
        const id = stack.pop()
        if (!id || seen.has(id)) continue
        seen.add(id)
        for (const cid of childrenByParent.get(id) ?? []) stack.push(cid)
      }
      descendants.set(note.id, seen)
    }
    return descendants
  }, [notes])

  const canMoveNote = useCallback(
    (sourceId: string, targetParentId: string | null): boolean => {
      const src = noteMap.get(sourceId)
      if (!src) return false
      if ((src.parentNoteId ?? null) === targetParentId) return false
      if (targetParentId === sourceId) return false
      if (targetParentId && descendantIdsByNote.get(sourceId)?.has(targetParentId)) return false
      return true
    },
    [descendantIdsByNote, noteMap],
  )

  const handleMoveDrop = useCallback(
    async (targetParentId: string | null) => {
      if (!onMoveNote || !draggingNoteId) return
      if (!canMoveNote(draggingNoteId, targetParentId)) return
      await onMoveNote(draggingNoteId, targetParentId)
      if (targetParentId) {
        setCollapsedBranchIds(prev => {
          if (!prev.has(targetParentId)) return prev
          const next = new Set(prev)
          next.delete(targetParentId)
          return next
        })
      }
    },
    [canMoveNote, draggingNoteId, onMoveNote],
  )

  const renderChildren = useCallback(
    (parentId: string | null, depth: number): ReactNode => {
      const children = visibleNotesByParent.get(parentId) ?? []
      if (!children.length) return null

      return children.map((note) => {
        const hasChildren = (visibleNotesByParent.get(note.id)?.length ?? 0) > 0
        const isBranchCollapsed = !disableBranchCollapse && collapsedBranchIds.has(note.id)

        return (
          <div key={note.id}>
            <NoteCardItem
              note={note}
              hasChildren={hasChildren}
              isBranchCollapsed={isBranchCollapsed}
              onToggleBranch={() => {
                setCollapsedBranchIds(prev => {
                  const next = new Set(prev)
                  next.has(note.id) ? next.delete(note.id) : next.add(note.id)
                  return next
                })
              }}
              isExpanded={expandedId === note.id}
              onExpand={() => setExpandedId(note.id)}
              onCollapse={collapseExpanded}
              onNoteChange={onNoteChange}
              onDeleteNote={onDeleteNote}
              onCreateNote={onCreateNote}
              onDragStart={() => { setDraggingNoteId(note.id); setDropTargetId(null) }}
              onDragEnd={() => { setDraggingNoteId(null); setDropTargetId(null) }}
              onDragOver={(e) => {
                if (!draggingNoteId || !canMoveNote(draggingNoteId, note.id)) return
                e.preventDefault()
                e.stopPropagation()
                e.dataTransfer.dropEffect = 'move'
                setDropTargetId(note.id)
              }}
              onDrop={(e) => {
                e.preventDefault()
                e.stopPropagation()
                void handleMoveDrop(note.id)
                setDraggingNoteId(null)
                setDropTargetId(null)
              }}
              isDragging={draggingNoteId === note.id}
              isDragTarget={dropTargetId === note.id}
              searchQuery={searchQuery}
              depth={depth}
            />
            {!isBranchCollapsed ? renderChildren(note.id, depth + 1) : null}
          </div>
        )
      })
    },
    [
      visibleNotesByParent, disableBranchCollapse, collapsedBranchIds,
      expandedId, collapseExpanded, onNoteChange, onDeleteNote, onCreateNote,
      draggingNoteId, dropTargetId, canMoveNote, handleMoveDrop, searchQuery,
    ],
  )

  const rootNotes = useMemo(() => {
    return notes.filter(note => {
      if (!visibleNoteIds.has(note.id)) return false
      if (!note.parentNoteId) return true
      return !visibleNoteIds.has(note.parentNoteId)
    })
  }, [notes, visibleNoteIds])

  const handleSearchToggle = useCallback(() => {
    setIsSearchOpen(prev => {
      if (prev) { setSearchQuery(''); return false }
      return true
    })
  }, [])

  useEffect(() => {
    if (isSearchOpen) window.requestAnimationFrame(() => searchInputRef.current?.focus())
  }, [isSearchOpen])

  return (
    <aside className="note-sidebar">
      <div className="sidebar-section-header">
        <span className="sidebar-section-title">Notes</span>
        <div style={{ display: 'flex', gap: 2 }}>
          <button type="button" className={`sidebar-action-btn ${isSearchOpen ? 'active' : ''}`} title="Search" onClick={handleSearchToggle}>
            <Search size={14} />
          </button>
          <button type="button" className="sidebar-action-btn" title="New note" onClick={() => onCreateNote()}>
            <Plus size={14} />
          </button>
        </div>
      </div>

      <div className={`note-search-bar-wrap ${isSearchOpen ? 'open' : ''}`}>
        <div className="note-search-bar">
          <Search size={12} className="note-search-icon" />
          <input
            ref={searchInputRef}
            type="text"
            className="note-search-input"
            placeholder="Tìm kiếm notes…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Escape') {
                if (searchQuery) setSearchQuery(''); else setIsSearchOpen(false)
              }
            }}
          />
          {searchQuery && (
            <button type="button" className="note-search-clear" onClick={() => setSearchQuery('')}>
              <X size={11} />
            </button>
          )}
        </div>
        {searchQuery && (
          <div className="note-search-results-count">
            {visibleNoteIds.size === 0 ? 'Không tìm thấy' : `${visibleNoteIds.size} kết quả`}
          </div>
        )}
      </div>

      <div
        className="note-list"
        onDragOver={e => {
          if (!draggingNoteId || !canMoveNote(draggingNoteId, null)) return
          e.preventDefault()
          e.dataTransfer.dropEffect = 'move'
          setDropTargetId('root')
        }}
        onDragLeave={e => {
          // Only clear root target if leaving the note-list itself
          if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) {
            setDropTargetId(null)
          }
        }}
        onDrop={e => {
          e.preventDefault()
          void handleMoveDrop(null)
          setDraggingNoteId(null)
          setDropTargetId(null)
        }}
      >
        {/* Root drop zone indicator */}
        {draggingNoteId && onMoveNote && dropTargetId === 'root' && (
          <div className="note-root-drop-zone active">
            ↑ Drop to move to root
          </div>
        )}

        {visibleNoteIds.size === 0 && searchQuery ? (
          <div className="note-search-empty">
            <Search size={18} strokeWidth={1.5} style={{ color: 'var(--text-disabled)' }} />
            <span>Không tìm thấy note nào<br />khớp với &ldquo;{searchQuery}&rdquo;</span>
          </div>
        ) : (
          rootNotes.map(note => (
            <div key={note.id}>
              <NoteCardItem
                note={note}
                hasChildren={(visibleNotesByParent.get(note.id)?.length ?? 0) > 0}
                isBranchCollapsed={!disableBranchCollapse && collapsedBranchIds.has(note.id)}
                onToggleBranch={() => {
                  setCollapsedBranchIds(prev => {
                    const next = new Set(prev)
                    next.has(note.id) ? next.delete(note.id) : next.add(note.id)
                    return next
                  })
                }}
                isExpanded={expandedId === note.id}
                onExpand={() => setExpandedId(note.id)}
                onCollapse={collapseExpanded}
                onNoteChange={onNoteChange}
                onDeleteNote={onDeleteNote}
                onCreateNote={onCreateNote}
                onDragStart={() => { setDraggingNoteId(note.id); setDropTargetId(null) }}
                onDragEnd={() => { setDraggingNoteId(null); setDropTargetId(null) }}
                onDragOver={e => {
                  if (!draggingNoteId || !canMoveNote(draggingNoteId, note.id)) return
                  e.preventDefault()
                  e.stopPropagation()
                  e.dataTransfer.dropEffect = 'move'
                  setDropTargetId(note.id)
                }}
                onDrop={e => {
                  e.preventDefault()
                  e.stopPropagation()
                  void handleMoveDrop(note.id)
                  setDraggingNoteId(null)
                  setDropTargetId(null)
                }}
                isDragging={draggingNoteId === note.id}
                isDragTarget={dropTargetId === note.id}
                searchQuery={searchQuery}
                depth={0}
              />
              {!(!disableBranchCollapse && collapsedBranchIds.has(note.id)) ? renderChildren(note.id, 1) : null}
            </div>
          ))
        )}
      </div>
    </aside>
  )
}