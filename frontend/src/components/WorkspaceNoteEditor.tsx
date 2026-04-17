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

// ── Toolbar action types ───────────────────────────────────────

type ApplyResult = {
    value: string
    // After applying, where should the selection be?
    selStart: number
    selEnd: number
}

// Helper: wrap selected text (or insert placeholder) with before/after markers
function wrapSelection(
    ta: HTMLTextAreaElement,
    before: string,
    after: string,
    placeholder: string,
): ApplyResult {
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const selected = ta.value.slice(start, end)
    const text = selected || placeholder
    const newVal = ta.value.slice(0, start) + before + text + after + ta.value.slice(end)

    // If there was a selection, keep it selected inside markers
    // If we used placeholder, select just the placeholder text
    const selStart = start + before.length
    const selEnd = selStart + text.length
    return { value: newVal, selStart, selEnd }
}

// Helper: prefix current line
function prefixLine(ta: HTMLTextAreaElement, prefix: string): ApplyResult {
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const lineStart = ta.value.lastIndexOf('\n', start - 1) + 1
    const newVal = ta.value.slice(0, lineStart) + prefix + ta.value.slice(lineStart)
    return {
        value: newVal,
        selStart: start + prefix.length,
        selEnd: end + prefix.length,
    }
}

// Helper: insert link markdown
function insertLink(ta: HTMLTextAreaElement): ApplyResult {
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const selected = ta.value.slice(start, end)
    const linkText = selected || 'link text'
    const insertion = `[${linkText}](url)`
    const newVal = ta.value.slice(0, start) + insertion + ta.value.slice(end)
    // Select "url" for easy replacement
    const urlStart = start + linkText.length + 3 // after "[linkText]("
    return {
        value: newVal,
        selStart: urlStart,
        selEnd: urlStart + 3, // "url"
    }
}

// Helper: insert code block
function insertCodeBlock(ta: HTMLTextAreaElement): ApplyResult {
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const selected = ta.value.slice(start, end)
    const inner = selected || 'code here'
    const block = `\`\`\`\n${inner}\n\`\`\``
    const newVal = ta.value.slice(0, start) + block + ta.value.slice(end)
    // Select inner content
    return {
        value: newVal,
        selStart: start + 4, // after "```\n"
        selEnd: start + 4 + inner.length,
    }
}

// Helper: insert horizontal rule
function insertHr(ta: HTMLTextAreaElement): ApplyResult {
    const start = ta.selectionStart
    const insertion = '\n---\n'
    const newVal = ta.value.slice(0, start) + insertion + ta.value.slice(start)
    // Place cursor after the rule
    const newPos = start + insertion.length
    return { value: newVal, selStart: newPos, selEnd: newPos }
}

type ToolbarAction = {
    icon: React.ReactNode
    label: string
    apply: (ta: HTMLTextAreaElement) => ApplyResult
    group?: number
}

const TOOLBAR_ACTIONS: ToolbarAction[] = [
    {
        group: 1,
        icon: <Heading1 size={14} />,
        label: 'Heading 1',
        apply: ta => prefixLine(ta, '# '),
    },
    {
        group: 1,
        icon: <Heading2 size={14} />,
        label: 'Heading 2',
        apply: ta => prefixLine(ta, '## '),
    },
    {
        group: 2,
        icon: <Bold size={14} />,
        label: 'Bold (Ctrl+B)',
        apply: ta => wrapSelection(ta, '**', '**', 'bold text'),
    },
    {
        group: 2,
        icon: <Italic size={14} />,
        label: 'Italic (Ctrl+I)',
        apply: ta => wrapSelection(ta, '*', '*', 'italic'),
    },
    {
        group: 2,
        icon: <Underline size={14} />,
        label: 'Underline',
        apply: ta => wrapSelection(ta, '<u>', '</u>', 'underline'),
    },
    {
        group: 2,
        icon: <Strikethrough size={14} />,
        label: 'Strikethrough',
        apply: ta => wrapSelection(ta, '~~', '~~', 'strikethrough'),
    },
    {
        group: 3,
        icon: <List size={14} />,
        label: 'Bullet list',
        apply: ta => prefixLine(ta, '- '),
    },
    {
        group: 3,
        icon: <ListOrdered size={14} />,
        label: 'Numbered list',
        apply: ta => prefixLine(ta, '1. '),
    },
    {
        group: 3,
        icon: <Quote size={14} />,
        label: 'Blockquote',
        apply: ta => prefixLine(ta, '> '),
    },
    {
        group: 4,
        icon: <Code size={14} />,
        label: 'Inline code',
        apply: ta => wrapSelection(ta, '`', '`', 'code'),
    },
    {
        group: 4,
        icon: <Terminal size={14} />,
        label: 'Code block',
        apply: ta => insertCodeBlock(ta),
    },
    {
        group: 4,
        icon: <Link size={14} />,
        label: 'Link (Ctrl+K)',
        apply: ta => insertLink(ta),
    },
    {
        group: 5,
        icon: <Minus size={14} />,
        label: 'Horizontal rule',
        apply: ta => insertHr(ta),
    },
]

function MarkdownToolbar({
    textareaRef,
    onApply,
}: {
    textareaRef: React.RefObject<HTMLTextAreaElement | null>
    onApply: (newValue: string, selStart: number, selEnd: number) => void
}) {
    const runAction = (action: ToolbarAction) => {
        const ta = textareaRef.current
        if (!ta) return
        const result = action.apply(ta)
        onApply(result.value, result.selStart, result.selEnd)
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
                                // Prevent textarea from losing focus
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

interface WorkspaceNoteEditorProps {
    note: NoteItem
    onChange: (id: string, contentMd: string) => void
    onAskAI?: () => void
}

export function WorkspaceNoteEditor({
    note,
    onChange,
    onAskAI,
}: WorkspaceNoteEditorProps) {
    const [localMd, setLocalMd] = useState(note.contentMd)
    const [viewMode, setViewMode] = useState<ViewMode>('split')
    const [wordCount, setWordCount] = useState(0)
    const timerRef = useRef<number | null>(null)
    const lastNoteIdRef = useRef<string | null>(null)
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const previewRef = useRef<HTMLDivElement>(null)
    const isSyncScrollingRef = useRef(false)
    // Track pending cursor position to apply after React re-render
    const pendingSelectionRef = useRef<{ start: number; end: number } | null>(null)

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

    // Apply pending cursor selection after state update + DOM paint
    useEffect(() => {
        if (!pendingSelectionRef.current) return
        const { start, end } = pendingSelectionRef.current
        pendingSelectionRef.current = null
        const ta = textareaRef.current
        if (!ta) return
        // Use rAF to ensure DOM has updated
        window.requestAnimationFrame(() => {
            ta.focus()
            ta.setSelectionRange(start, end)
        })
    })

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

    // Called by toolbar: update value AND schedule cursor placement
    const applyToolbarAction = useCallback((newValue: string, selStart: number, selEnd: number) => {
        pendingSelectionRef.current = { start: selStart, end: selEnd }
        applyValue(newValue)
    }, [applyValue])

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
            pendingSelectionRef.current = { start: start + 2, end: start + 2 }
            applyValue(newVal)
            return
        }

        // Ctrl+B
        if (e.key === 'b' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault()
            const result = wrapSelection(ta, '**', '**', 'bold text')
            applyToolbarAction(result.value, result.selStart, result.selEnd)
            return
        }
        // Ctrl+I
        if (e.key === 'i' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault()
            const result = wrapSelection(ta, '*', '*', 'italic')
            applyToolbarAction(result.value, result.selStart, result.selEnd)
            return
        }
        // Ctrl+K
        if (e.key === 'k' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault()
            const result = insertLink(ta)
            applyToolbarAction(result.value, result.selStart, result.selEnd)
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
                <div className="wne-header-right">
                    {onAskAI && (
                        <button
                            type="button"
                            className="wne-ai-btn"
                            onClick={onAskAI}
                            title="Ask AI about this note"
                        >
                            <span className="wne-ai-btn-icon">✦</span>
                            Ask AI
                        </button>
                    )}
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
                </div>
            </header>

            {/* Markdown toolbar (editor/split only) */}
            {viewMode !== 'preview' && (
                <MarkdownToolbar textareaRef={textareaRef} onApply={applyToolbarAction} />
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