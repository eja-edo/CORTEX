import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Columns2, Eye, FileText } from 'lucide-react'
import type { NoteItem } from './NoteSidebar'
import { plainTextFromMarkdown } from '../utils/noteMarkdown'
import { EditorSurface } from './editor/EditorSurface'
import '../styles/editor.css'

function noteTitleFromMd(content: string): string {
    const text = plainTextFromMarkdown(content)
    return text.split('\n').find(l => l.trim()) || 'Untitled'
}

type ViewMode = 'split' | 'edit' | 'preview'

// ── WorkspaceNoteEditor ───────────────────────────────────────

interface WorkspaceNoteEditorProps {
    note: NoteItem
    onChange: (id: string, contentMd: string) => void
    onAskAI?: () => void
    onSelectionChange?: (selectedText: string) => void
}

export function WorkspaceNoteEditor({
    note,
    onChange,
}: WorkspaceNoteEditorProps) {
    const [localMd, setLocalMd] = useState(note.contentMd)
    const [debouncedMd, setDebouncedMd] = useState(note.contentMd)
    const [viewMode, setViewMode] = useState<ViewMode>('split')
    const timerRef = useRef<number | null>(null)
    const debounceTimerRef = useRef<number | null>(null)
    const lastNoteIdRef = useRef<string | null>(null)
    const lastContentMdRef = useRef<string>(note.contentMd)
    const pendingFlushValueRef = useRef<string | null>(null)
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const previewRef = useRef<HTMLDivElement>(null)
    const selectionRef = useRef<{ start: number; end: number } | null>(null)
    const syncingScroll = useRef<'left' | 'right' | null>(null)

    // Debounce raw → blocks: wait 2s after last textarea change
    useEffect(() => {
        if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
        debounceTimerRef.current = window.setTimeout(() => {
            setDebouncedMd(localMd)
        }, 2000)
        return () => { if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current) }
    }, [localMd])

    // Sync blocks immediately when switching to a view that shows them
    const syncBlocks = useCallback(() => {
        setDebouncedMd(localMd)
    }, [localMd])

    // Force sync on view mode change if blocks pane will show
    useEffect(() => {
        if (viewMode !== 'edit') {
            // eslint-disable-next-line react-hooks/set-state-in-effect
            syncBlocks()
        }
    }, [viewMode, syncBlocks])

    const wordCount = useMemo(() => {
        const text = plainTextFromMarkdown(localMd)
        return text.trim().split(/\s+/).filter(Boolean).length
    }, [localMd])

    // Sync when switching notes — handles both new-note-switch and async content load
    useEffect(() => {
        if (lastNoteIdRef.current !== note.id) {
            // Switching to a different note: flush pending content for the old note first
            if (timerRef.current && pendingFlushValueRef.current !== null) {
                window.clearTimeout(timerRef.current)
                timerRef.current = null
                onChange(lastNoteIdRef.current, pendingFlushValueRef.current)
                pendingFlushValueRef.current = null
            }

            lastNoteIdRef.current = note.id
            lastContentMdRef.current = note.contentMd
            setLocalMd(note.contentMd)
        } else if (note.contentMd !== lastContentMdRef.current) {
            // Same note, content updated externally (e.g. fetchFullNote completed)
            const prevSynced = lastContentMdRef.current
            lastContentMdRef.current = note.contentMd
            setLocalMd((current) => (current === prevSynced ? note.contentMd : current))
        }
    }, [note.id, note.contentMd, onChange])

    // Sync scroll between textarea and preview in split mode
    useEffect(() => {
        if (viewMode !== 'split') return

        const textarea = textareaRef.current
        const preview = previewRef.current
        if (!textarea || !preview) return

        const onScroll = (source: 'left' | 'right') => {
            if (syncingScroll.current) return
            syncingScroll.current = source

            const el = source === 'left' ? textarea : preview
            const target = source === 'left' ? preview : textarea
            const ratio = el.scrollTop / (el.scrollHeight - el.clientHeight)
            target.scrollTop = ratio * (target.scrollHeight - target.clientHeight)

            syncingScroll.current = null
        }

        const onScrollLeft = () => onScroll('left')
        const onScrollRight = () => onScroll('right')

        textarea.addEventListener('scroll', onScrollLeft, { passive: true })
        preview.addEventListener('scroll', onScrollRight, { passive: true })

        return () => {
            textarea.removeEventListener('scroll', onScrollLeft)
            preview.removeEventListener('scroll', onScrollRight)
        }
    }, [viewMode])

    useEffect(() => () => {
        if (timerRef.current) window.clearTimeout(timerRef.current)
        if (debounceTimerRef.current) window.clearTimeout(debounceTimerRef.current)
    }, [])

    const flush = useCallback((value: string) => {
        onChange(note.id, value)
    }, [note.id, onChange])

    const AUTOSAVE_INTERVAL = Number(import.meta.env.VITE_AUTOSAVE_INTERVAL) || 350
    const queueFlush = useCallback((value: string) => {
        pendingFlushValueRef.current = value
        if (timerRef.current) window.clearTimeout(timerRef.current)
        timerRef.current = window.setTimeout(() => {
            flush(value)
            timerRef.current = null
            pendingFlushValueRef.current = null
        }, AUTOSAVE_INTERVAL)
    }, [flush, AUTOSAVE_INTERVAL])

    const applyValue = useCallback((value: string) => {
        setLocalMd(value)
        queueFlush(value)
    }, [queueFlush])

    // Preserve cursor position across controlled-value re-renders
    useLayoutEffect(() => {
        const el = textareaRef.current
        if (el && selectionRef.current) {
            const start = Math.min(selectionRef.current.start, el.value.length)
            const end = Math.min(selectionRef.current.end, el.value.length)
            el.selectionStart = start
            el.selectionEnd = end
            selectionRef.current = null
        }
    })

    // Tab key handler for raw textarea
    const handleTextareaKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        // Ctrl+S → sync blocks immediately
        if ((e.metaKey || e.ctrlKey) && e.key === 's') {
            e.preventDefault()
            syncBlocks()
            return
        }

        if (e.key !== 'Tab') return

        e.preventDefault()

        const el = e.currentTarget
        const start = el.selectionStart
        const end = el.selectionEnd
        const value = el.value

        // Get line boundaries
        const lineStart = value.lastIndexOf('\n', start - 1) + 1
        let lineEnd = value.indexOf('\n', lineStart)
        if (lineEnd === -1) lineEnd = value.length

        let newValue: string
        let newStart: number
        let newEnd: number

        if (e.shiftKey) {
            // Outdent: remove 2 leading spaces from current line
            const currentLine = value.slice(lineStart, lineEnd)
            const indentMatch = currentLine.match(/^ {1,2}/)
            if (indentMatch) {
                const removeLen = indentMatch[0].length
                newValue = value.slice(0, lineStart) + currentLine.slice(removeLen) + value.slice(lineEnd)
                newStart = Math.max(start - removeLen, lineStart)
                newEnd = Math.max(end - removeLen, lineStart)
            } else {
                return
            }
        } else {
            // Check if cursor is on a list line
            const currentLine = value.slice(lineStart, lineEnd)
            const listMatch = currentLine.match(/^(\s*)([-*+]|\d+\.)\s/)

            if (listMatch) {
                // Indent list item: add 2 spaces before the list marker
                const markerStart = lineStart + listMatch[1].length
                newValue = value.slice(0, markerStart) + '  ' + value.slice(markerStart)
                newStart = start + 2
                newEnd = end + 2
            } else {
                // Insert 2 spaces at cursor
                newValue = value.slice(0, start) + '  ' + value.slice(end)
                newStart = start + 2
                newEnd = newStart
            }
        }

        selectionRef.current = { start: newStart, end: newEnd }
        applyValue(newValue)
    }, [applyValue, syncBlocks])

    // Raw markdown textarea change
    const handleTextareaChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
        selectionRef.current = {
            start: e.target.selectionStart,
            end: e.target.selectionEnd,
        }
        const newMd = e.target.value
        applyValue(newMd)
    }, [applyValue])

    // Block editor save → sync markdown
    const handleBlockEditorSave = useCallback((md: string) => {
        setLocalMd(md)
        setDebouncedMd(md)
        queueFlush(md)
    }, [queueFlush])



    return (
        <section className="wne-root">
            {/* Header */}
            <header className="wne-header">
                <div className="wne-meta">
                    <h2 className="wne-title">{noteTitleFromMd(localMd)}</h2>
                    <div className="wne-info">
                        <span className="wne-date">{note.date}</span>
                        <span className="wne-sep">·</span>
                        <span className="wne-wordcount">{wordCount} từ</span>
                    </div>
                </div>
                <div className="wne-header-right">
                    <div className="wne-view-switcher">
                        <button type="button" className={`wne-view-btn ${viewMode === 'edit' ? 'active' : ''}`} onClick={() => setViewMode('edit')} title="Raw markdown only">
                            <FileText size={14} /><span>MD</span>
                        </button>
                        <button type="button" className={`wne-view-btn ${viewMode === 'split' ? 'active' : ''}`} onClick={() => setViewMode('split')} title="Split view">
                            <Columns2 size={14} /><span>Split</span>
                        </button>
                        <button type="button" className={`wne-view-btn ${viewMode === 'preview' ? 'active' : ''}`} onClick={() => setViewMode('preview')} title="Block editor">
                            <Eye size={14} /><span>Blocks</span>
                        </button>
                    </div>
                </div>
            </header>

            {/* Body */}
            <div className={`wne-body wne-body--${viewMode}`}>
                {/* EDITOR PANE: Raw markdown textarea */}
                {(viewMode === 'edit' || viewMode === 'split') && (
                    <div className="wne-pane wne-pane--editor">
                        {viewMode === 'split' && <div className="wne-pane-label">Markdown</div>}
                        <textarea
                            ref={textareaRef}
                            className="wne-textarea"
                            value={localMd}
                            onChange={handleTextareaChange}
                            onKeyDown={handleTextareaKeyDown}
                            placeholder="Raw markdown..."
                            spellCheck={false}
                        />
                    </div>
                )}

                {viewMode === 'split' && <div className="wne-divider" />}

                {/* PREVIEW PANE: Block editor (interactive) */}
                {(viewMode === 'preview' || viewMode === 'split') && (
                    <div className="wne-pane wne-pane--preview">
                        {viewMode === 'split' && <div className="wne-pane-label">Blocks</div>}
                        <div ref={previewRef} className="wne-preview-content">
                            <EditorSurface
                                initialMd={debouncedMd}
                                noteId={note.id}
                                onSave={handleBlockEditorSave}
                            />
                        </div>
                    </div>
                )}
            </div>
        </section>
    )
}
