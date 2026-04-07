import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { Bold, Check, Italic, List, Plus, Search, SquareArrowOutUpRight, Strikethrough, Underline } from 'lucide-react'

export type NoteItem = {
  id: string
  date: string
  contentHtml: string
}

interface NoteSidebarProps {
  notes: NoteItem[]
  onNoteChange: (id: string, contentHtml: string) => void
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

function plainTextFromHtml(html: string): string {
  if (!html.trim()) return ''
  const d = document.createElement('div')
  d.innerHTML = html
  return (d.innerText || d.textContent || '').trim()
}

/** Gets first non-empty line of plain text from HTML */
function getTitleFromHtml(html: string): string {
  const plain = plainTextFromHtml(html)
  return plain.split('\n').find(l => l.trim()) || 'Untitled'
}

function NoteEditor({
  noteId, contentHtml, isExpanded, editorRef,
}: { noteId: string; contentHtml: string; isExpanded: boolean; editorRef: RefObject<HTMLDivElement | null> }) {
  const lastExpanded = useRef(false)

  useEffect(() => {
    const el = editorRef.current
    if (!el) return
    if (isExpanded && !lastExpanded.current) {
      el.innerHTML = contentHtml
      lastExpanded.current = true
      return
    }
    if (!isExpanded) { lastExpanded.current = false; return }
    if (document.activeElement !== el && el.innerHTML !== contentHtml) {
      el.innerHTML = contentHtml
    }
  }, [contentHtml, isExpanded, noteId, editorRef])

  return (
    <div
      ref={editorRef}
      className="note-card-editor"
      contentEditable
      suppressContentEditableWarning
      role="textbox"
      aria-multiline
      data-placeholder="Write something…"
    />
  )
}

function NoteCardItem({
  note, isExpanded, onExpand, onCollapse, onNoteChange,
}: { note: NoteItem; isExpanded: boolean; onExpand: () => void; onCollapse: () => void; onNoteChange: (id: string, html: string) => void }) {
  const cardRef = useRef<HTMLElement>(null)
  const editorRef = useRef<HTMLDivElement>(null)
  const expandId = `note-expand-${note.id}`
  const title = getTitleFromHtml(note.contentHtml)

  useEffect(() => {
    if (!isExpanded) return
    return () => {
      const el = editorRef.current
      if (el) onNoteChange(note.id, el.innerHTML)
    }
  }, [isExpanded, note.id, onNoteChange])

  useEffect(() => {
    if (!isExpanded) return
    const onPointerDown = (e: PointerEvent) => {
      if (cardRef.current?.contains(e.target as Node)) return
      onCollapse()
    }
    document.addEventListener('pointerdown', onPointerDown, true)
    return () => document.removeEventListener('pointerdown', onPointerDown, true)
  }, [isExpanded, onCollapse])

  const applyFormat = (command: string, value?: string) => {
    const el = editorRef.current
    if (!el) return
    el.focus()
    document.execCommand(command, false, value)
  }

  const handlePopOut = (e: React.MouseEvent) => {
    e.stopPropagation()
    const el = editorRef.current
    const html = el?.innerHTML ?? note.contentHtml
    if (el) onNoteChange(note.id, html)
    openNotePopoutWindow(note.date, html)
  }

  // Pick emoji based on content
  const emoji = note.contentHtml.includes('<strong>') ? '📋' : note.contentHtml.includes('http') ? '🔗' : '📝'

  return (
    <article ref={cardRef} className={`note-card${isExpanded ? ' note-card--expanded' : ''}`}>
      {/* Summary row — always visible */}
      <button
        type="button"
        className="note-card-summary-btn"
        aria-expanded={isExpanded}
        aria-controls={expandId}
        onClick={isExpanded ? onCollapse : onExpand}
      >
        <span className="note-icon">{emoji}</span>
        <div className="note-card-info">
          <div className="note-card-title">{title}</div>
          <div className="note-card-date">{note.date}</div>
        </div>
      </button>

      {/* Expandable editor */}
      <div id={expandId} className="note-expandable" aria-hidden={!isExpanded} inert={!isExpanded}>
        <div className="note-expandable-inner">
          <div className="note-editor-wrap">
            <NoteEditor noteId={note.id} contentHtml={note.contentHtml} isExpanded={isExpanded} editorRef={editorRef} />
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
              <div className="note-toolbar-spacer" />
              <button type="button" className="note-done-btn" onClick={onCollapse}>
                <Check size={12} /> Done
              </button>
            </div>
          </div>
        </div>
      </div>
    </article>
  )
}

export function NoteSidebar({ notes, onNoteChange }: NoteSidebarProps) {
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
          <button type="button" className="sidebar-action-btn" aria-label="New note" title="New note">
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
          />
        ))}
      </div>
    </aside>
  )
}