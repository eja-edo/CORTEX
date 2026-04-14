import { useCallback, useEffect, useRef, useState } from 'react'
import { Columns2, Eye, FileText } from 'lucide-react'
import MarkdownIt from 'markdown-it'
import type { NoteItem } from './NoteSidebar'
import { plainTextFromMarkdown } from '../utils/noteMarkdown'

const md = new MarkdownIt({
    html: false,
    linkify: true,
    typographer: true,
    breaks: true,
})

function noteTitleFromMd(content: string): string {
    if (!content) return 'Untitled note'
    const text = plainTextFromMarkdown(content).replace(/\s+/g, ' ').trim()
    return text.slice(0, 64) || 'Untitled note'
}

function formatNoteDate(date: string): string {
    return date
}

type ViewMode = 'split' | 'edit' | 'preview'

export function WorkspaceNoteEditor({
    note,
    onChange,
}: {
    note: NoteItem
    onChange: (id: string, contentMd: string) => void
}) {
    const [localMd, setLocalMd] = useState(note.contentMd)
    const [viewMode, setViewMode] = useState<ViewMode>('split')
    const [wordCount, setWordCount] = useState(0)
    const timerRef = useRef<number | null>(null)
    const lastNoteIdRef = useRef<string | null>(null)
    const textareaRef = useRef<HTMLTextAreaElement>(null)

    // Sync when switching notes
    useEffect(() => {
        if (lastNoteIdRef.current === note.id) return
        lastNoteIdRef.current = note.id
        setLocalMd(note.contentMd)
    }, [note.id, note.contentMd])

    // Word count
    useEffect(() => {
        const text = plainTextFromMarkdown(localMd)
        setWordCount(text.trim().split(/\s+/).filter(Boolean).length)
    }, [localMd])

    // Cleanup timer
    useEffect(() => () => { if (timerRef.current) window.clearTimeout(timerRef.current) }, [])

    const flush = useCallback((value: string) => {
        onChange(note.id, value)
    }, [note.id, onChange])

    const queueFlush = useCallback((value: string) => {
        if (timerRef.current) window.clearTimeout(timerRef.current)
        timerRef.current = window.setTimeout(() => {
            flush(value)
            timerRef.current = null
        }, 300)
    }, [flush])

    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        const value = e.target.value
        setLocalMd(value)
        queueFlush(value)
    }

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Tab') {
            e.preventDefault()
            const el = e.currentTarget
            const start = el.selectionStart
            const end = el.selectionEnd
            const newVal = localMd.slice(0, start) + '  ' + localMd.slice(end)
            setLocalMd(newVal)
            queueFlush(newVal)
            window.requestAnimationFrame(() => {
                el.selectionStart = el.selectionEnd = start + 2
            })
        }
    }

    const renderedHtml = md.render(localMd || '_Bắt đầu viết..._')

    return (
        <section className="wne-root">
            {/* Header */}
            <header className="wne-header">
                <div className="wne-meta">
                    <h2 className="wne-title">{noteTitleFromMd(localMd)}</h2>
                    <div className="wne-info">
                        <span className="wne-date">{formatNoteDate(note.date)}</span>
                        <span className="wne-sep">·</span>
                        <span className="wne-wordcount">{wordCount} từ</span>
                    </div>
                </div>
                <div className="wne-view-switcher">
                    <button
                        type="button"
                        className={`wne-view-btn ${viewMode === 'edit' ? 'active' : ''}`}
                        onClick={() => setViewMode('edit')}
                        title="Editor only"
                    >
                        <FileText size={14} />
                        <span>Edit</span>
                    </button>
                    <button
                        type="button"
                        className={`wne-view-btn ${viewMode === 'split' ? 'active' : ''}`}
                        onClick={() => setViewMode('split')}
                        title="Split view"
                    >
                        <Columns2 size={14} />
                        <span>Split</span>
                    </button>
                    <button
                        type="button"
                        className={`wne-view-btn ${viewMode === 'preview' ? 'active' : ''}`}
                        onClick={() => setViewMode('preview')}
                        title="Preview only"
                    >
                        <Eye size={14} />
                        <span>Preview</span>
                    </button>
                </div>
            </header>

            {/* Body */}
            <div className={`wne-body wne-body--${viewMode}`}>
                {/* Editor pane */}
                {(viewMode === 'edit' || viewMode === 'split') && (
                    <div className="wne-pane wne-pane--editor">
                        {viewMode === 'split' && (
                            <div className="wne-pane-label">Markdown</div>
                        )}
                        <textarea
                            ref={textareaRef}
                            className="wne-textarea"
                            value={localMd}
                            onChange={handleChange}
                            onKeyDown={handleKeyDown}
                            onBlur={() => flush(localMd)}
                            placeholder={'# Tiêu đề\n\nBắt đầu viết markdown...\n\n**Bold**, *italic*, `code`\n\n- List item 1\n- List item 2'}
                            spellCheck={false}
                        />
                    </div>
                )}

                {/* Divider for split mode */}
                {viewMode === 'split' && <div className="wne-divider" />}

                {/* Preview pane */}
                {(viewMode === 'preview' || viewMode === 'split') && (
                    <div className="wne-pane wne-pane--preview">
                        {viewMode === 'split' && (
                            <div className="wne-pane-label">Preview</div>
                        )}
                        <div
                            className="wne-preview-content"
                            dangerouslySetInnerHTML={{ __html: renderedHtml }}
                        />
                    </div>
                )}
            </div>
        </section>
    )
}