import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { Bold, Check, Italic, List, Plus, Search, SquareArrowOutUpRight, Strikethrough, Trash2, Underline } from 'lucide-react'
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

/** Gets first non-empty line of plain text from markdown */
function getTitleFromMd(md: string): string {
  const plain = plainTextFromMarkdown(md)
  return plain.split('\n').find(l => l.trim()) || 'Untitled'
}

function NoteEditor({
  noteId, contentMd, isExpanded, editorRef, onMarkdownEnter,
}: {
  noteId: string
  contentMd: string
  isExpanded: boolean
  editorRef: RefObject<HTMLDivElement | null>
  onMarkdownEnter: (e: React.KeyboardEvent<HTMLDivElement>) => void
}) {
  const lastExpanded = useRef(false)

  useEffect(() => {
    const el = editorRef.current
    if (!el) return
    const contentHtml = markdownToHtml(contentMd)
    if (isExpanded && !lastExpanded.current) {
      el.innerHTML = contentHtml
      lastExpanded.current = true
      return
    }
    if (!isExpanded) { lastExpanded.current = false; return }
    if (document.activeElement !== el && el.innerHTML !== contentHtml) {
      el.innerHTML = contentHtml
    }
  }, [contentMd, isExpanded, noteId, editorRef])

  return (
    <div
      ref={editorRef}
      className="note-card-editor"
      contentEditable
      suppressContentEditableWarning
      role="textbox"
      aria-multiline
      data-placeholder="Write something…"
      onKeyDown={onMarkdownEnter}
    />
  )
}

function NoteCardItem({
  note, isExpanded, onExpand, onCollapse, onNoteChange, onDeleteNote,
}: {
  note: NoteItem
  isExpanded: boolean
  onExpand: () => void
  onCollapse: () => void
  onNoteChange: (id: string, md: string) => void
  onDeleteNote?: (id: string) => void
}) {
  const cardRef = useRef<HTMLElement>(null)
  const editorRef = useRef<HTMLDivElement>(null)
  const summaryButtonRef = useRef<HTMLButtonElement>(null)
  const expandId = `note-expand-${note.id}`
  const title = getTitleFromMd(note.contentMd)

  const collapseWithFocusRestore = useCallback(() => {
    const active = document.activeElement
    if (active instanceof HTMLElement && cardRef.current?.contains(active)) {
      active.blur()
    }
    onCollapse()
    window.requestAnimationFrame(() => summaryButtonRef.current?.focus())
  }, [onCollapse])

  useEffect(() => {
    if (!isExpanded) return
    return () => {
      const el = editorRef.current
      if (el) onNoteChange(note.id, htmlToMarkdown(el.innerHTML))
    }
  }, [isExpanded, note.id, onNoteChange])

  useEffect(() => {
    if (!isExpanded) return
    const onPointerDown = (e: PointerEvent) => {
      if (cardRef.current?.contains(e.target as Node)) return
      collapseWithFocusRestore()
    }
    document.addEventListener('pointerdown', onPointerDown, true)
    return () => document.removeEventListener('pointerdown', onPointerDown, true)
  }, [isExpanded, collapseWithFocusRestore])

  const applyFormat = (command: string, value?: string) => {
    const el = editorRef.current
    if (!el) return
    el.focus()
    document.execCommand(command, false, value)
  }

  const handleMarkdownEnter = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Enter' || e.shiftKey) return
    const el = editorRef.current
    if (!el) return
    const applied = applyMarkdownShortcutOnEnter(el)
    if (applied) e.preventDefault()
  }

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
    if (window.confirm(`Xóa note "${title}"?`)) {
      onDeleteNote(note.id)
    }
  }

  // Pick emoji based on content
  const emoji = note.contentMd.includes('**') ? '📋' : note.contentMd.includes('http') ? '🔗' : '📝'

  return (
    <article ref={cardRef} className={`note-card${isExpanded ? ' note-card--expanded' : ''}`}>
      {/* Summary row — always visible */}
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
            <div className="note-card-title">{title}</div>
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

      {/* Expandable editor */}
      <div id={expandId} className="note-expandable" aria-hidden={!isExpanded} inert={!isExpanded}>
        <div className="note-expandable-inner">
          <div className="note-editor-wrap">
            <NoteEditor
              noteId={note.id}
              contentMd={note.contentMd}
              isExpanded={isExpanded}
              editorRef={editorRef}
              onMarkdownEnter={handleMarkdownEnter}
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
  const collapseExpanded = useCallback(() => setExpandedId(null), [])

  return (
    <aside className="note-sidebar">
      <div className="sidebar-section-header">
        <span className="sidebar-section-title">Notes</span>
        <div style={{ display: 'flex', gap: 2 }}>
          <button type="button" className="sidebar-action-btn" aria-label="Search notes" title="Search">
            <Search size={14} />
          </button>
          <button type="button" className="sidebar-action-btn" aria-label="New note" title="New note" onClick={onCreateNote}>
            <Plus size={14} />
          </button>
        </div>
      </div>

      <div className="note-list">
        {notes.map((note) => (
          <NoteCardItem
            key={note.id}
            note={note}
            isExpanded={expandedId === note.id}
            onExpand={() => setExpandedId(note.id)}
            onCollapse={collapseExpanded}
            onNoteChange={onNoteChange}
            onDeleteNote={onDeleteNote}
          />
        ))}
      </div>
    </aside>
  )
}