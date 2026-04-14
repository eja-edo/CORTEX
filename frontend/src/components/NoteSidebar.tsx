import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Check, ChevronRight, Plus, Search, Trash2, X } from 'lucide-react'
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
  const [localMd, setLocalMd] = useState(note.contentMd)
  const expandId = `note-expand-${note.id}`
  const title = getTitleFromMd(note.contentMd)

  // Sync localMd when note changes from outside (e.g. initial load)
  useEffect(() => {
    if (!isExpanded) {
      setLocalMd(note.contentMd)
    }
  }, [note.contentMd, isExpanded])

  // When expanded, populate textarea with current markdown
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

  const autoResize = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 280) + 'px'
  }

  const collapseAndSave = useCallback(() => {
    onNoteChange(note.id, localMd)
    const active = document.activeElement
    if (active instanceof HTMLElement && cardRef.current?.contains(active)) active.blur()
    onCollapse()
    window.requestAnimationFrame(() => summaryButtonRef.current?.focus())
  }, [localMd, note.id, onNoteChange, onCollapse])

  // Click outside to collapse & save
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
    onDragStart()
  }

  return (
    <article
      ref={cardRef}
      className={`note-card${isExpanded ? ' note-card--expanded' : ''}${depth > 0 ? ' note-card--child' : ''}${isDragging ? ' note-card--dragging' : ''}${isDragTarget ? ' note-card--drop-target' : ''}`}
      style={{ marginLeft: depth * 12 }}
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
            title={isBranchCollapsed ? 'Expand branch' : 'Collapse branch'}
            onClick={(event) => {
              event.stopPropagation()
              onToggleBranch()
            }}
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
              <div
                className="note-card-title"
                dangerouslySetInnerHTML={{ __html: highlightMatch(title, searchQuery) }}
              />
            ) : (
              <div className="note-card-title">{title}</div>
            )}
            <div className="note-card-date">{note.date}</div>
          </div>
        </button>
        {onDeleteNote && (
          <button
            type="button"
            className="note-toolbar-btn"
            title="Xóa note"
            aria-label="Xóa note"
            onClick={handleDelete}
            style={{ marginRight: 6, flexShrink: 0, color: 'var(--text-tertiary)' }}
          >
            <Trash2 size={13} />
          </button>
        )}
      </div>

      <div id={expandId} className="note-expandable" aria-hidden={!isExpanded} inert={!isExpanded}>
        <div className="note-expandable-inner">
          <div className="note-editor-wrap">
            {isExpanded ? (
              /* ── EDIT MODE: raw markdown textarea ── */
              <div className="note-md-edit-area">
                <textarea
                  ref={textareaRef}
                  className="note-md-textarea"
                  value={localMd}
                  placeholder="Write markdown here… e.g. # Title, **bold**, - list"
                  onChange={(e) => {
                    setLocalMd(e.target.value)
                    autoResize(e.target)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Tab') {
                      e.preventDefault()
                      const el = e.currentTarget
                      const start = el.selectionStart
                      const end = el.selectionEnd
                      const newVal = localMd.slice(0, start) + '  ' + localMd.slice(end)
                      setLocalMd(newVal)
                      window.requestAnimationFrame(() => {
                        el.selectionStart = el.selectionEnd = start + 2
                      })
                    }
                    if (e.key === 'Escape') collapseAndSave()
                  }}
                  spellCheck={false}
                />
                <div className="note-md-edit-hint">
                  Markdown · Tab = 2 spaces · Esc để lưu
                </div>
              </div>
            ) : (
              /* ── VIEW MODE: rendered markdown preview ── */
              <div
                className="note-md-preview"
                dangerouslySetInnerHTML={{ __html: renderedHtml }}
              />
            )}

            <div className="note-toolbar" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
              <button
                type="button"
                className="note-toolbar-btn"
                title="Add sub-note"
                aria-label="Add sub-note"
                onClick={(e) => {
                  e.stopPropagation()
                  onCreateNote(note.id)
                }}
              >
                <Plus size={13} />
              </button>
              {onDeleteNote && (
                <>
                  <button
                    type="button"
                    className="note-toolbar-btn"
                    title="Xóa note"
                    aria-label="Xóa note"
                    onClick={handleDelete}
                    style={{ color: 'var(--red)' }}
                  >
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

export function NoteSidebar({ notes, onNoteChange, onCreateNote, onMoveNote, onDeleteNote }: NoteSidebarProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [isSearchOpen, setIsSearchOpen] = useState(false)
  const [collapsedBranchIds, setCollapsedBranchIds] = useState<Set<string>>(new Set())
  const [draggingNoteId, setDraggingNoteId] = useState<string | null>(null)
  const [dropTargetParentId, setDropTargetParentId] = useState<string | null>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const collapseExpanded = useCallback(() => setExpandedId(null), [])
  const disableBranchCollapse = searchQuery.trim().length > 0

  const noteMap = useMemo(
    () => new Map(notes.map((note) => [note.id, note] as const)),
    [notes],
  )

  const visibleNoteIds = useMemo(() => {
    if (!searchQuery.trim()) return new Set(notes.map((note) => note.id))

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
  }, [notes, searchQuery])

  const visibleNotesByParent = useMemo(() => {
    const map = new Map<string | null, NoteItem[]>()
    for (const note of notes) {
      if (!visibleNoteIds.has(note.id)) continue
      const parentKey = (note.parentNoteId ?? null)
      const bucket = map.get(parentKey)
      if (bucket) {
        bucket.push(note)
      } else {
        map.set(parentKey, [note])
      }
    }
    return map
  }, [notes, visibleNoteIds])

  const descendantIdsByNote = useMemo(() => {
    const childrenByParent = new Map<string | null, string[]>()
    for (const note of notes) {
      const parentKey = note.parentNoteId ?? null
      const bucket = childrenByParent.get(parentKey)
      if (bucket) {
        bucket.push(note.id)
      } else {
        childrenByParent.set(parentKey, [note.id])
      }
    }

    const descendants = new Map<string, Set<string>>()
    for (const note of notes) {
      const seen = new Set<string>()
      const stack = [...(childrenByParent.get(note.id) ?? [])]
      while (stack.length) {
        const currentId = stack.pop()
        if (!currentId || seen.has(currentId)) continue
        seen.add(currentId)
        for (const childId of childrenByParent.get(currentId) ?? []) {
          stack.push(childId)
        }
      }
      descendants.set(note.id, seen)
    }
    return descendants
  }, [notes])

  const canMoveNote = useCallback(
    (sourceNoteId: string, targetParentId: string | null): boolean => {
      const sourceNote = noteMap.get(sourceNoteId)
      if (!sourceNote) return false
      if ((sourceNote.parentNoteId ?? null) === targetParentId) return false
      if (targetParentId === sourceNoteId) return false
      if (targetParentId && descendantIdsByNote.get(sourceNoteId)?.has(targetParentId)) return false
      return true
    },
    [descendantIdsByNote, noteMap],
  )

  const handleMoveDrop = useCallback(
    async (targetParentId: string | null) => {
      if (!onMoveNote || !draggingNoteId) return
      if (!canMoveNote(draggingNoteId, targetParentId)) return
      await onMoveNote(draggingNoteId, targetParentId)
      setCollapsedBranchIds((prev) => {
        if (!targetParentId) return prev
        if (!prev.has(targetParentId)) return prev
        const next = new Set(prev)
        next.delete(targetParentId)
        return next
      })
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
                setCollapsedBranchIds((prev) => {
                  const next = new Set(prev)
                  if (next.has(note.id)) {
                    next.delete(note.id)
                  } else {
                    next.add(note.id)
                  }
                  return next
                })
              }}
              isExpanded={expandedId === note.id}
              onExpand={() => setExpandedId(note.id)}
              onCollapse={collapseExpanded}
              onNoteChange={onNoteChange}
              onDeleteNote={onDeleteNote}
              onCreateNote={onCreateNote}
              onDragStart={() => {
                setDraggingNoteId(note.id)
                setDropTargetParentId(null)
              }}
              onDragEnd={() => {
                setDraggingNoteId(null)
                setDropTargetParentId(null)
              }}
              onDragOver={(event) => {
                if (!draggingNoteId || !canMoveNote(draggingNoteId, note.id)) return
                event.preventDefault()
                setDropTargetParentId(note.id)
              }}
              onDrop={(event) => {
                event.preventDefault()
                void handleMoveDrop(note.id)
                setDraggingNoteId(null)
                setDropTargetParentId(null)
              }}
              isDragging={draggingNoteId === note.id}
              isDragTarget={dropTargetParentId === note.id}
              searchQuery={searchQuery}
              depth={depth}
            />
            {!isBranchCollapsed ? renderChildren(note.id, depth + 1) : null}
          </div>
        )
      })
    },
    [
      visibleNotesByParent,
      disableBranchCollapse,
      collapsedBranchIds,
      expandedId,
      collapseExpanded,
      onNoteChange,
      onDeleteNote,
      onCreateNote,
      draggingNoteId,
      dropTargetParentId,
      canMoveNote,
      handleMoveDrop,
      searchQuery,
    ],
  )

  const rootNotes = useMemo(() => {
    return notes.filter((note) => {
      if (!visibleNoteIds.has(note.id)) return false
      if (!note.parentNoteId) return true
      return !visibleNoteIds.has(note.parentNoteId)
    })
  }, [notes, visibleNoteIds])

  const handleSearchToggle = useCallback(() => {
    setIsSearchOpen((prev) => {
      if (prev) { setSearchQuery(''); return false }
      return true
    })
  }, [])

  useEffect(() => {
    if (isSearchOpen) window.requestAnimationFrame(() => searchInputRef.current?.focus())
  }, [isSearchOpen])

  const handleClearSearch = useCallback(() => {
    setSearchQuery('')
    searchInputRef.current?.focus()
  }, [])

  return (
    <aside className="note-sidebar">
      <div className="sidebar-section-header">
        <span className="sidebar-section-title">Notes</span>
        <div style={{ display: 'flex', gap: 2 }}>
          <button
            type="button"
            className={`sidebar-action-btn ${isSearchOpen ? 'active' : ''}`}
            aria-label="Search notes"
            title="Search"
            onClick={handleSearchToggle}
          >
            <Search size={14} />
          </button>
          <button
            type="button"
            className="sidebar-action-btn"
            aria-label="New note"
            title="New note"
            onClick={() => onCreateNote()}
          >
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
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                if (searchQuery) { setSearchQuery('') } else { setIsSearchOpen(false) }
              }
            }}
          />
          {searchQuery && (
            <button type="button" className="note-search-clear" onClick={handleClearSearch} aria-label="Clear search">
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

      <div className="note-list">
        {draggingNoteId && onMoveNote ? (
          <div
            className={`note-root-drop-zone${dropTargetParentId === null ? ' active' : ''}`}
            onDragOver={(event) => {
              if (!draggingNoteId || !canMoveNote(draggingNoteId, null)) return
              event.preventDefault()
              setDropTargetParentId(null)
            }}
            onDrop={(event) => {
              event.preventDefault()
              void handleMoveDrop(null)
              setDraggingNoteId(null)
              setDropTargetParentId(null)
            }}
          >
            Drop here để đưa note về root
          </div>
        ) : null}
        {visibleNoteIds.size === 0 && searchQuery ? (
          <div className="note-search-empty">
            <Search size={18} strokeWidth={1.5} style={{ color: 'var(--text-disabled)' }} />
            <span>Không tìm thấy note nào<br />khớp với &ldquo;{searchQuery}&rdquo;</span>
          </div>
        ) : (
          rootNotes.map((note) => (
            <div key={note.id}>
              <NoteCardItem
                note={note}
                hasChildren={(visibleNotesByParent.get(note.id)?.length ?? 0) > 0}
                isBranchCollapsed={!disableBranchCollapse && collapsedBranchIds.has(note.id)}
                onToggleBranch={() => {
                  setCollapsedBranchIds((prev) => {
                    const next = new Set(prev)
                    if (next.has(note.id)) {
                      next.delete(note.id)
                    } else {
                      next.add(note.id)
                    }
                    return next
                  })
                }}
                isExpanded={expandedId === note.id}
                onExpand={() => setExpandedId(note.id)}
                onCollapse={collapseExpanded}
                onNoteChange={onNoteChange}
                onDeleteNote={onDeleteNote}
                onCreateNote={onCreateNote}
                onDragStart={() => {
                  setDraggingNoteId(note.id)
                  setDropTargetParentId(null)
                }}
                onDragEnd={() => {
                  setDraggingNoteId(null)
                  setDropTargetParentId(null)
                }}
                onDragOver={(event) => {
                  if (!draggingNoteId || !canMoveNote(draggingNoteId, note.id)) return
                  event.preventDefault()
                  setDropTargetParentId(note.id)
                }}
                onDrop={(event) => {
                  event.preventDefault()
                  void handleMoveDrop(note.id)
                  setDraggingNoteId(null)
                  setDropTargetParentId(null)
                }}
                isDragging={draggingNoteId === note.id}
                isDragTarget={dropTargetParentId === note.id}
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