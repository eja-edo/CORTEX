import { useCallback, useEffect, useRef, useState } from 'react'
import {
    Bold,
    Code,
    Columns2,
    Eye,
    FileText,
    Heading1,
    Heading2,
    Italic,
    Link,
    List,
    ListOrdered,
    Minus,
    Quote,
    Strikethrough,
    Terminal,
    Underline,
} from 'lucide-react'
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

type ViewMode = 'split' | 'edit' | 'preview'

// ── Toolbar helpers ────────────────────────────────────────────

function wrapSel(ta: HTMLTextAreaElement, before: string, after: string, placeholder: string): string {
    const s = ta.selectionStart
    const e = ta.selectionEnd
    const selected = ta.value.slice(s, e) || placeholder
    return ta.value.slice(0, s) + before + selected + after + ta.value.slice(e)
}

function linePrefix(ta: HTMLTextAreaElement, prefix: string): string {
    const s = ta.selectionStart
    const lineStart = ta.value.lastIndexOf('\n', s - 1) + 1
    return ta.value.slice(0, lineStart) + prefix + ta.value.slice(lineStart)
}

function insertLinkMd(ta: HTMLTextAreaElement): string {
    const s = ta.selectionStart
    const e = ta.selectionEnd
    const selected = ta.value.slice(s, e) || 'link text'
    return ta.value.slice(0, s) + `[${selected}](url)` + ta.value.slice(e)
}

function insertCodeBlock(ta: HTMLTextAreaElement): string {
    const s = ta.selectionStart
    const selected = ta.value.slice(s, ta.selectionEnd) || ''
    const block = `\`\`\`\n${selected}\n\`\`\``
    return ta.value.slice(0, s) + block + ta.value.slice(ta.selectionEnd)
}

type ToolbarAction = {
    icon: React.ReactNode
    label: string
    apply: (ta: HTMLTextAreaElement) => { value: string; selStart?: number; selEnd?: number }
    group?: number
}

const TOOLBAR_ACTIONS: ToolbarAction[] = [
    {
        group: 1,
        icon: <Heading1 size={14} />,
        label: 'Heading 1',
        apply: ta => ({ value: linePrefix(ta, '# ') }),
    },
    {
        group: 1,
        icon: <Heading2 size={14} />,
        label: 'Heading 2',
        apply: ta => ({ value: linePrefix(ta, '## ') }),
    },
    {
        group: 2,
        icon: <Bold size={14} />,
        label: 'Bold (Ctrl+B)',
        apply: ta => {
            const v = wrapSel(ta, '**', '**', 'bold text')
            return { value: v, selStart: ta.selectionStart + 2, selEnd: ta.selectionStart + 2 + (ta.value.slice(ta.selectionStart, ta.selectionEnd) || 'bold text').length }
        },
    },
    {
        group: 2,
        icon: <Italic size={14} />,
        label: 'Italic (Ctrl+I)',
        apply: ta => ({ value: wrapSel(ta, '*', '*', 'italic') }),
    },
    {
        group: 2,
        icon: <Underline size={14} />,
        label: 'Underline',
        apply: ta => ({ value: wrapSel(ta, '<u>', '</u>', 'underline') }),
    },
    {
        group: 2,
        icon: <Strikethrough size={14} />,
        label: 'Strikethrough',
        apply: ta => ({ value: wrapSel(ta, '~~', '~~', 'strikethrough') }),
    },
    {
        group: 3,
        icon: <List size={14} />,
        label: 'Bullet list',
        apply: ta => ({ value: linePrefix(ta, '- ') }),
    },
    {
        group: 3,
        icon: <ListOrdered size={14} />,
        label: 'Numbered list',
        apply: ta => ({ value: linePrefix(ta, '1. ') }),
    },
    {
        group: 3,
        icon: <Quote size={14} />,
        label: 'Blockquote',
        apply: ta => ({ value: linePrefix(ta, '> ') }),
    },
    {
        group: 4,
        icon: <Code size={14} />,
        label: 'Inline code',
        apply: ta => ({ value: wrapSel(ta, '`', '`', 'code') }),
    },
    {
        group: 4,
        icon: <Terminal size={14} />,
        label: 'Code block',
        apply: ta => ({ value: insertCodeBlock(ta) }),
    },
    {
        group: 4,
        icon: <Link size={14} />,
        label: 'Link',
        apply: ta => ({ value: insertLinkMd(ta) }),
    },
    {
        group: 5,
        icon: <Minus size={14} />,
        label: 'Horizontal rule',
        apply: ta => {
            const s = ta.selectionStart
            const insertion = '\n---\n'
            return { value: ta.value.slice(0, s) + insertion + ta.value.slice(s) }
        },
    },
]

function MarkdownToolbar({
    textareaRef,
    onApply,
}: {
    textareaRef: React.RefObject<HTMLTextAreaElement | null>
    onApply: (newValue: string) => void
}) {
    const runAction = (action: ToolbarAction) => {
        const ta = textareaRef.current
        if (!ta) return
        const result = action.apply(ta)
        onApply(result.value)
        window.requestAnimationFrame(() => {
            ta.focus()
        })
    }

    let lastGroup = -1
    return (
        <div className="wne-toolbar">
            {TOOLBAR_ACTIONS.map((action, i) => {
                const showSep = lastGroup !== -1 && action.group !== lastGroup
                lastGroup = action.group ?? 0
                return (
                    <div key={i} style={{ display: 'contents' }}>
                        {showSep && <div className="wne-toolbar-sep" />}
                        <button
                            type="button"
                            className="wne-toolbar-btn"
                            title={action.label}
                            onMouseDown={e => {
                                e.preventDefault()
                                runAction(action)
                            }}
                        >
                            {action.icon}
                        </button>
                    </div>
                )
            })}
        </div>
    )
}

// ── WorkspaceNoteEditor ───────────────────────────────────────

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
    const previewRef = useRef<HTMLDivElement>(null)
    const isSyncScrollingRef = useRef(false)

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

    useEffect(() => () => { if (timerRef.current) window.clearTimeout(timerRef.current) }, [])

    const flush = useCallback((value: string) => {
        onChange(note.id, value)
    }, [note.id, onChange])

    const queueFlush = useCallback((value: string) => {
        if (timerRef.current) window.clearTimeout(timerRef.current)
        timerRef.current = window.setTimeout(() => { flush(value); timerRef.current = null }, 300)
    }, [flush])

    const applyValue = useCallback((value: string) => {
        setLocalMd(value)
        queueFlush(value)
    }, [queueFlush])

    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        applyValue(e.target.value)
    }

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        const ta = e.currentTarget

        // Tab → 2 spaces
        if (e.key === 'Tab') {
            e.preventDefault()
            const start = ta.selectionStart
            const end = ta.selectionEnd
            const newVal = localMd.slice(0, start) + '  ' + localMd.slice(end)
            applyValue(newVal)
            window.requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = start + 2 })
            return
        }

        // Ctrl+B
        if (e.key === 'b' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault()
            applyValue(wrapSel(ta, '**', '**', 'bold'))
            return
        }
        // Ctrl+I
        if (e.key === 'i' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault()
            applyValue(wrapSel(ta, '*', '*', 'italic'))
            return
        }
        // Ctrl+K
        if (e.key === 'k' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault()
            applyValue(insertLinkMd(ta))
            return
        }
    }

    // Sync scroll: editor → preview
    const handleEditorScroll = useCallback(() => {
        if (isSyncScrollingRef.current) return
        const ta = textareaRef.current
        const preview = previewRef.current
        if (!ta || !preview || viewMode !== 'split') return

        isSyncScrollingRef.current = true
        const ratio = ta.scrollTop / (ta.scrollHeight - ta.clientHeight || 1)
        preview.scrollTop = ratio * (preview.scrollHeight - preview.clientHeight)
        window.requestAnimationFrame(() => { isSyncScrollingRef.current = false })
    }, [viewMode])

    // Sync scroll: preview → editor
    const handlePreviewScroll = useCallback(() => {
        if (isSyncScrollingRef.current) return
        const ta = textareaRef.current
        const preview = previewRef.current
        if (!ta || !preview || viewMode !== 'split') return

        isSyncScrollingRef.current = true
        const ratio = preview.scrollTop / (preview.scrollHeight - preview.clientHeight || 1)
        ta.scrollTop = ratio * (ta.scrollHeight - ta.clientHeight)
        window.requestAnimationFrame(() => { isSyncScrollingRef.current = false })
    }, [viewMode])

    const renderedHtml = md.render(localMd || '_Bắt đầu viết..._')

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
                <div className="wne-view-switcher">
                    <button type="button" className={`wne-view-btn ${viewMode === 'edit' ? 'active' : ''}`} onClick={() => setViewMode('edit')} title="Editor only">
                        <FileText size={14} /><span>Edit</span>
                    </button>
                    <button type="button" className={`wne-view-btn ${viewMode === 'split' ? 'active' : ''}`} onClick={() => setViewMode('split')} title="Split view">
                        <Columns2 size={14} /><span>Split</span>
                    </button>
                    <button type="button" className={`wne-view-btn ${viewMode === 'preview' ? 'active' : ''}`} onClick={() => setViewMode('preview')} title="Preview only">
                        <Eye size={14} /><span>Preview</span>
                    </button>
                </div>
            </header>

            {/* Markdown toolbar (editor/split only) */}
            {viewMode !== 'preview' && (
                <MarkdownToolbar textareaRef={textareaRef} onApply={applyValue} />
            )}

            {/* Body */}
            <div className={`wne-body wne-body--${viewMode}`}>
                {(viewMode === 'edit' || viewMode === 'split') && (
                    <div className="wne-pane wne-pane--editor">
                        {viewMode === 'split' && <div className="wne-pane-label">Markdown</div>}
                        <textarea
                            ref={textareaRef}
                            className="wne-textarea"
                            value={localMd}
                            onChange={handleChange}
                            onKeyDown={handleKeyDown}
                            onBlur={() => flush(localMd)}
                            onScroll={handleEditorScroll}
                            placeholder={'bắt đầu viết...'}
                            spellCheck={false}
                        />
                    </div>
                )}

                {viewMode === 'split' && <div className="wne-divider" />}

                {(viewMode === 'preview' || viewMode === 'split') && (
                    <div className="wne-pane wne-pane--preview">
                        {viewMode === 'split' && <div className="wne-pane-label">Preview</div>}
                        <div
                            ref={previewRef}
                            className="wne-preview-content"
                            onScroll={handlePreviewScroll}
                            dangerouslySetInnerHTML={{ __html: renderedHtml }}
                        />
                    </div>
                )}
            </div>
        </section>
    )
}