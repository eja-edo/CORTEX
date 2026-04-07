import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { clsx } from 'clsx'
import {
  Bold,
  Check,
  Italic,
  List,
  MoreHorizontal,
  Search,
  SquareArrowOutUpRight,
  Strikethrough,
  Underline,
} from 'lucide-react'

export type NoteItem = {
  id: string
  date: string
  /** Rich text (contenteditable HTML) */
  contentHtml: string
}

interface NoteSidebarProps {
  notes: NoteItem[]
  onNoteChange: (id: string, contentHtml: string) => void
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** Mở cửa sổ nhỏ ghim ngoài màn hình (giống Sticky Notes pop-out). */
function openNotePopoutWindow(date: string, contentHtml: string): void {
  const w = window.open(
    '',
    `cortex-note-${Date.now()}`,
    'popup=yes,width=400,height=500,left=120,top=100,resizable=yes,scrollbars=yes',
  )
  if (!w) {
    window.alert('Không mở được cửa sổ. Hãy cho phép pop-up cho trang này.')
    return
  }

  try {
    w.opener = null
  } catch {
    /* ignore */
  }

  w.document.open()
  w.document.write('<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8">')
  w.document.write(
    `<meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(date)} — Ghi chú</title>`,
  )
  w.document.write(`<style>
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; padding: 14px 16px 20px;
      font-family: "Plus Jakarta Sans", system-ui, -apple-system, sans-serif;
      background: linear-gradient(180deg, #f0e1ff 0%, #ead8ff 100%);
      color: #2d2141; border: 1px solid #d6c2f2; }
    .note-date { font-size: 12px; color: rgba(75, 60, 103, 0.75); margin-bottom: 10px; text-align: right; }
    .note-body { font-size: 14px; line-height: 1.45; outline: none; }
    .note-body p { margin: 0 0 0.55em; }
    .note-body p:last-child { margin-bottom: 0; }
    .note-body ul { margin: 0 0 0.55em; padding-left: 1.15rem; }
    .note-body li { margin: 0.12em 0; }
    .note-body a { color: #3d5a9e; }
  </style></head><body><div class="note-date">${escapeHtml(date)}</div><div id="note-root" class="note-body"></div></body></html>`)
  w.document.close()
  const root = w.document.getElementById('note-root')
  if (root) root.innerHTML = contentHtml
}

/** Plain text for aria-label only (preview shows HTML) */
function plainTextFromHtml(html: string): string {
  if (!html.trim()) return ''
  if (typeof document === 'undefined') {
    return html
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<\/p>/gi, '\n')
      .replace(/<[^>]+>/g, '')
      .replace(/\s+\n/g, '\n')
      .trim()
  }
  const d = document.createElement('div')
  d.innerHTML = html
  return (d.innerText || d.textContent || '').trim()
}

function NoteEditor({
  noteId,
  contentHtml,
  isExpanded,
  editorRef,
}: {
  noteId: string
  contentHtml: string
  isExpanded: boolean
  editorRef: RefObject<HTMLDivElement | null>
}) {
  const lastExpanded = useRef(false)

  useEffect(() => {
    const el = editorRef.current
    if (!el) return

    if (isExpanded && !lastExpanded.current) {
      el.innerHTML = contentHtml
      lastExpanded.current = true
      return
    }
    if (!isExpanded) {
      lastExpanded.current = false
      return
    }

    if (document.activeElement !== el && el.innerHTML !== contentHtml) {
      el.innerHTML = contentHtml
    }
  }, [contentHtml, isExpanded, noteId])

  return (
    <div
      ref={editorRef}
      className="note-card-editor"
      contentEditable
      suppressContentEditableWarning
      role="textbox"
      aria-multiline
      data-placeholder="Nhập nội dung…"
    />
  )
}

function NoteCardItem({
  note,
  isExpanded,
  onExpand,
  onCollapse,
  onNoteChange,
}: {
  note: NoteItem
  isExpanded: boolean
  onExpand: () => void
  onCollapse: () => void
  onNoteChange: (id: string, html: string) => void
}) {
  const cardRef = useRef<HTMLElement>(null)
  const editorRef = useRef<HTMLDivElement>(null)
  const expandId = `note-expand-${note.id}`

  /** Chỉ đẩy state lên App khi đóng / chuyển note — tránh re-render cả App mỗi phím gõ (gây lag). */
  useEffect(() => {
    if (!isExpanded) return
    return () => {
      const el = editorRef.current
      if (el) onNoteChange(note.id, el.innerHTML)
    }
  }, [isExpanded, note.id, onNoteChange])

  /** Ấn ra ngoài thẻ đang mở → thu gọn (đóng) ghi chú. */
  useEffect(() => {
    if (!isExpanded) return
    const onPointerDown = (e: PointerEvent) => {
      const t = e.target as Node
      if (cardRef.current?.contains(t)) return
      onCollapse()
    }
    document.addEventListener('pointerdown', onPointerDown, true)
    return () => document.removeEventListener('pointerdown', onPointerDown, true)
  }, [isExpanded, onCollapse])

  const previewHtml =
    note.contentHtml.trim().length > 0
      ? note.contentHtml
      : '<span class="note-card-empty-preview">Ghi chú trống</span>'

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

  return (
    <article ref={cardRef} className={clsx('note-card', isExpanded && 'note-card--expanded')}>
      <div className={clsx('note-card-top', !isExpanded && 'note-card-top--collapsed')}>
        <div className="note-card-date">{note.date}</div>
        {isExpanded ? (
          <div className="note-card-actions">
            <button type="button" className="ghost icon-only" aria-label="More options">
              <MoreHorizontal size={16} />
            </button>
            <button
              type="button"
              className="ghost icon-only"
              aria-label="Ghim cửa sổ ngoài màn hình"
              title="Ghim ra ngoài"
              onClick={handlePopOut}
            >
              <SquareArrowOutUpRight size={16} />
            </button>
          </div>
        ) : null}
      </div>

      {!isExpanded ? (
        <button
          type="button"
          className="note-card-summary"
          aria-expanded={false}
          aria-controls={expandId}
          aria-label={plainTextFromHtml(note.contentHtml) || 'Ghi chú trống'}
          onClick={onExpand}
        >
          <div
            className="note-card-summary-preview note-card-summary-preview--rich"
            dangerouslySetInnerHTML={{ __html: previewHtml }}
          />
        </button>
      ) : null}

      <div
        id={expandId}
        className="note-card-expandable"
        aria-hidden={!isExpanded}
        inert={!isExpanded}
      >
        <div className="note-card-expandable-inner">
          <div className="note-card-body note-card-body--expanded">
            <NoteEditor
              noteId={note.id}
              contentHtml={note.contentHtml}
              isExpanded={isExpanded}
              editorRef={editorRef}
            />
          </div>
          <div
            className="note-card-toolbar"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            <div className="note-card-toolbar-formats">
              <button
                type="button"
                className="ghost icon-only"
                aria-label="Bold"
                title="Bold"
                onClick={() => applyFormat('bold')}
              >
                <Bold size={15} />
              </button>
              <button
                type="button"
                className="ghost icon-only"
                aria-label="Italic"
                title="Italic"
                onClick={() => applyFormat('italic')}
              >
                <Italic size={15} />
              </button>
              <button
                type="button"
                className="ghost icon-only"
                aria-label="Underline"
                title="Underline"
                onClick={() => applyFormat('underline')}
              >
                <Underline size={15} />
              </button>
              <button
                type="button"
                className="ghost icon-only"
                aria-label="Strikethrough"
                title="Strikethrough"
                onClick={() => applyFormat('strikeThrough')}
              >
                <Strikethrough size={15} />
              </button>
              <button
                type="button"
                className="ghost icon-only"
                aria-label="Bulleted list"
                title="List"
                onClick={() => applyFormat('insertUnorderedList')}
              >
                <List size={15} />
              </button>
            </div>
            <span className="note-card-toolbar-divider" aria-hidden />
            <button type="button" className="note-card-screenshot">
              <span className="note-card-screenshot-icon" aria-hidden>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <path d="M9 9h6v6H9z" />
                </svg>
              </span>
              Screenshot
            </button>
            <button
              type="button"
              className="ghost icon-only note-card-done"
              aria-label="Thu gọn ghi chú"
              title="Xong"
              onClick={onCollapse}
            >
              <Check size={18} strokeWidth={2.5} />
            </button>
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
    <aside className="panel note-sidebar">
      <div className="note-sidebar-header">
        <h2>Recent notes</h2>
        <button type="button" className="ghost icon-only" aria-label="Search notes">
          <Search size={16} />
        </button>
      </div>

      <div className="note-list">
        {notes.map((note) => {
          const isExpanded = expandedId === note.id
          return (
            <NoteCardItem
              key={note.id}
              note={note}
              isExpanded={isExpanded}
              onExpand={() => setExpandedId(note.id)}
              onCollapse={collapseExpanded}
              onNoteChange={onNoteChange}
            />
          )
        })}
      </div>
    </aside>
  )
}
