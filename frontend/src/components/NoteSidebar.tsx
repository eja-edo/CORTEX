import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { Bold, Check, Italic, List, Plus, Search, SquareArrowOutUpRight, Strikethrough, Trash2, Underline, X } from 'lucide-react'
import { applyMarkdownShortcutOnEnter, htmlToMarkdown, markdownToHtml, plainTextFromMarkdown } from '../utils/noteMarkdown'

export type NoteItem = {
  id: string
  date: string
  contentMd: string
}

interface NoteSidebarProps {
  notes: NoteItem[]
  onNoteChange: (id: string, contentMd: string) => void
  onCreateNote: () => void
  onDeleteNote?: (id: string) => void
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function openNotePopoutWindow(date: string, contentHtml: string): void {
  const w = window.open('', `cortex-note-${Date.now()}`, 'popup=yes,width=400,height=500,left=120,top=100,resizable=yes,scrollbars=yes')
  if (!w) { window.alert('Allow pop-ups for this page.'); return }
  try { w.opener = null } catch { /* ignore */ }
  w.document.open()
  w.document.write(`<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(date)}</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; padding: 20px 24px;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 14px; line-height: 1.6; color: #37352f; background: #fff; }
  .date { font-size: 11px; color: #9b9a97; margin-bottom: 14px; }
  .body p { margin: 0 0 8px; } .body ul { padding-left: 18px; } .body li { margin: 3px 0; }
</style></head><body><div class="date">${escapeHtml(date)}</div><div id="r" class="body"></div></body></html>`)
  w.document.close()
  const root = w.document.getElementById('r')
  if (root) root.innerHTML = contentHtml
}

function getTitleFromMd(md: string): string {
  const plain = plainTextFromMarkdown(md)
  return plain.split('\n').find(l => l.trim()) || 'Untitled'
}

function highlightMatch(text: string, query: string): string {
  if (!query.trim()) return escapeHtml(text)
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const regex = new RegExp(`(${escaped})`, 'gi')
  return escapeHtml(text).replace(
    new RegExp(`(${escapeHtml(query).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'),
    (_, m) => `<mark class="note-search-highlight">${m}</mark>`
  ).replace(regex, (_, m) => `<mark class="note-search-highlight">${escapeHtml(m)}</mark>`)
}

function NoteEditor({
  noteId, contentMd, isExpanded, editorRef, onFlush,
}: {
  noteId: string
  contentMd: string
  isExpanded: boolean
  editorRef: RefObject<HTMLDivElement | null>
  onFlush: (html: string) => void
}) {
  const lastRenderedNoteId = useRef<string | null>(null)
  const wasExpanded = useRef(false)
  const flushTimerRef = useRef<number | null>(null)

  useEffect(() => {
    const el = editorRef.current
    if (!el) return
    if (!isExpanded) { wasExpanded.current = false; return }
    const noteChanged = lastRenderedNoteId.current !== noteId
    const justExpanded = !wasExpanded.current
    if (justExpanded || noteChanged) {
      el.innerHTML = markdownToHtml(contentMd)
      lastRenderedNoteId.current = noteId
      wasExpanded.current = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noteId, isExpanded, editorRef])

  useEffect(() => () => { if (flushTimerRef.current) window.clearTimeout(flushTimerRef.current) }, [])

  const queueFlush = useCallback(() => {
    if (flushTimerRef.current) window.clearTimeout(flushTimerRef.current)
    flushTimerRef.current = window.setTimeout(() => {
      const el = editorRef.current
      if (el) onFlush(el.innerHTML)
      flushTimerRef.current = null
    }, 200)
  }, [editorRef, onFlush])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Enter' || e.shiftKey) return
    const el = editorRef.current
    if (!el) return
    if (applyMarkdownShortcutOnEnter(el)) { e.preventDefault(); queueFlush() }
  }, [editorRef, queueFlush])

  return (
    <div
      ref={editorRef}
      className="note-card-editor"
      contentEditable
      suppressContentEditableWarning
      role="textbox"
      aria-multiline
      data-placeholder="Write something..."
      onKeyDown={handleKeyDown}
      onInput={queueFlush}
      onBlur={() => {
        if (flushTimerRef.current) { window.clearTimeout(flushTimerRef.current); flushTimerRef.current = null }
        const el = editorRef.current
        if (el) onFlush(el.innerHTML)
      }}
    />
  )
}

function NoteCardItem({
  note, isExpanded, onExpand, onCollapse, onNoteChange, onDeleteNote, searchQuery,
}: {
  note: NoteItem
  isExpanded: boolean
  onExpand: () => void
  onCollapse: () => void
  onNoteChange: (id: string, md: string) => void
  onDeleteNote?: (id: string) => void
  searchQuery: string
}) {
  const cardRef = useRef<HTMLElement>(null)
  const editorRef = useRef<HTMLDivElement>(null)
  const summaryButtonRef = useRef<HTMLButtonElement>(null)
  const expandId = `note-expand-${note.id}`
  const title = getTitleFromMd(note.contentMd)

  const collapseWithFocusRestore = useCallback(() => {
    const active = document.activeElement
    if (active instanceof HTMLElement && cardRef.current?.contains(active)) active.blur()
    onCollapse()
    window.requestAnimationFrame(() => summaryButtonRef.current?.focus())
  }, [onCollapse])

  useEffect(() => {
    if (!isExpanded) return
    const onPointerDown = (e: PointerEvent) => {
      if (cardRef.current?.contains(e.target as Node)) return
      collapseWithFocusRestore()
    }
    document.addEventListener('pointerdown', onPointerDown, true)
    return () => document.removeEventListener('pointerdown', onPointerDown, true)
  }, [isExpanded, collapseWithFocusRestore])

  const applyFormat = (command: string) => {
    const el = editorRef.current
    if (!el) return
    el.focus()
    document.execCommand(command, false)
    onNoteChange(note.id, htmlToMarkdown(el.innerHTML))
  }

  const handleFlush = useCallback((html: string) => {
    onNoteChange(note.id, htmlToMarkdown(html))
  }, [note.id, onNoteChange])

  const handlePopOut = (e: React.MouseEvent) => {
    e.stopPropagation()
    const el = editorRef.current
    const html = el?.innerHTML ?? markdownToHtml(note.contentMd)
    if (el) onNoteChange(note.id, htmlToMarkdown(html))
    openNotePopoutWindow(note.date, html)
  }

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!onDeleteNote) return
    if (window.confirm(`Xoa note "${title}"?`)) onDeleteNote(note.id)
  }

  const emoji = note.contentMd.includes('**') ? '📋' : note.contentMd.includes('http') ? '🔗' : '📝'

  return (
    <article ref={cardRef} className={`note-card${isExpanded ? ' note-card--expanded' : ''}`}>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <button
          ref={summaryButtonRef}
          type="button"
          className="note-card-summary-btn"
          style={{ flex: 1 }}
          aria-expanded={isExpanded}
          aria-controls={expandId}
          onClick={isExpanded ? collapseWithFocusRestore : onExpand}
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
            title="Xoa note"
            aria-label="Xoa note"
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
            <NoteEditor
              noteId={note.id}
              contentMd={note.contentMd}
              isExpanded={isExpanded}
              editorRef={editorRef}
              onFlush={handleFlush}
            />
            <div
              className="note-toolbar"
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => e.stopPropagation()}
            >
              {[
                { cmd: 'bold', icon: <Bold size={13} />, label: 'Bold' },
                { cmd: 'italic', icon: <Italic size={13} />, label: 'Italic' },
                { cmd: 'underline', icon: <Underline size={13} />, label: 'Underline' },
                { cmd: 'strikeThrough', icon: <Strikethrough size={13} />, label: 'Strike' },
                { cmd: 'insertUnorderedList', icon: <List size={13} />, label: 'List' },
              ].map(({ cmd, icon, label }) => (
                <button key={cmd} type="button" className="note-toolbar-btn" title={label} aria-label={label} onClick={() => applyFormat(cmd)}>
                  {icon}
                </button>
              ))}
              <div className="note-toolbar-sep" />
              <button type="button" className="note-toolbar-btn" title="Open in window" aria-label="Pop out" onClick={handlePopOut}>
                <SquareArrowOutUpRight size={13} />
              </button>
              {onDeleteNote && (
                <>
                  <div className="note-toolbar-sep" />
                  <button type="button" className="note-toolbar-btn" title="Xoa note" aria-label="Xoa note" onClick={handleDelete} style={{ color: 'var(--red)' }}>
                    <Trash2 size={13} />
                  </button>
                </>
              )}
              <div className="note-toolbar-spacer" />
              <button type="button" className="note-done-btn" onClick={collapseWithFocusRestore}>
                <Check size={12} /> Done
              </button>
            </div>
          </div>
        </div>
      </div>
    </article>
  )
}

export function NoteSidebar({ notes, onNoteChange, onCreateNote, onDeleteNote }: NoteSidebarProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [isSearchOpen, setIsSearchOpen] = useState(false)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const collapseExpanded = useCallback(() => setExpandedId(null), [])

  const filteredNotes = searchQuery.trim()
    ? notes.filter((note) => {
      const q = searchQuery.toLowerCase()
      const plain = plainTextFromMarkdown(note.contentMd).toLowerCase()
      return plain.includes(q)
    })
    : notes

  const handleSearchToggle = useCallback(() => {
    setIsSearchOpen((prev) => {
      if (prev) {
        setSearchQuery('')
        return false
      }
      return true
    })
  }, [])

  // Focus input when search opens
  useEffect(() => {
    if (isSearchOpen) {
      window.requestAnimationFrame(() => searchInputRef.current?.focus())
    }
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
            onClick={onCreateNote}
          >
            <Plus size={14} />
          </button>
        </div>
      </div>

      {/* Search bar — animated expand */}
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
            {filteredNotes.length === 0
              ? 'Không tìm thấy'
              : `${filteredNotes.length} kết quả`}
          </div>
        )}
      </div>

      <div className="note-list">
        {filteredNotes.length === 0 && searchQuery ? (
          <div className="note-search-empty">
            <Search size={18} strokeWidth={1.5} style={{ color: 'var(--text-disabled)' }} />
            <span>Không tìm thấy note nào<br />khớp với &ldquo;{searchQuery}&rdquo;</span>
          </div>
        ) : (
          filteredNotes.map((note) => (
            <NoteCardItem
              key={note.id}
              note={note}
              isExpanded={expandedId === note.id}
              onExpand={() => setExpandedId(note.id)}
              onCollapse={collapseExpanded}
              onNoteChange={onNoteChange}
              onDeleteNote={onDeleteNote}
              searchQuery={searchQuery}
            />
          ))
        )}
      </div>
    </aside>
  )
}