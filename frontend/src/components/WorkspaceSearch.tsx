import { useCallback, useEffect, useRef, useState } from 'react'
import { Search, X, FileText, Clock, ArrowRight } from 'lucide-react'
import { plainTextFromMarkdown } from '../utils/noteMarkdown'

type NoteItem = {
    id: string
    date: string
    contentMd: string
    parentNoteId?: string | null
}

interface WorkspaceSearchProps {
    notes: NoteItem[]
    onOpenNote: (noteId: string) => void
    onClose: () => void
}

type SearchResult = {
    noteId: string
    title: string
    snippet: string
    date: string
}

function getTitleFromMd(md: string): string {
    const plain = plainTextFromMarkdown(md)
    return plain.split('\n').find(l => l.trim()) || 'Untitled'
}

function getSnippet(md: string, query: string, maxLen = 100): string {
    const plain = plainTextFromMarkdown(md)
    const lc = plain.toLowerCase()
    const idx = lc.indexOf(query.toLowerCase())
    if (idx === -1) return plain.slice(0, maxLen)
    const start = Math.max(0, idx - 30)
    const end = Math.min(plain.length, idx + query.length + 50)
    return (start > 0 ? '…' : '') + plain.slice(start, end) + (end < plain.length ? '…' : '')
}

function highlightText(text: string, query: string): React.ReactNode {
    if (!query.trim()) return text
    const parts = text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'))
    return parts.map((part, i) =>
        part.toLowerCase() === query.toLowerCase()
            ? <mark key={i} className="ws-search-hl">{part}</mark>
            : part
    )
}

export function WorkspaceSearch({ notes, onOpenNote, onClose }: WorkspaceSearchProps) {
    const [query, setQuery] = useState('')
    const [selectedIndex, setSelectedIndex] = useState(0)
    const inputRef = useRef<HTMLInputElement>(null)
    const resultsRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        inputRef.current?.focus()
    }, [])

    // Close on Escape
    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose()
        }
        document.addEventListener('keydown', handler)
        return () => document.removeEventListener('keydown', handler)
    }, [onClose])

    const results: SearchResult[] = query.trim()
        ? notes
            .filter(note => {
                const plain = plainTextFromMarkdown(note.contentMd).toLowerCase()
                return plain.includes(query.toLowerCase())
            })
            .slice(0, 10)
            .map(note => ({
                noteId: note.id,
                title: getTitleFromMd(note.contentMd),
                snippet: getSnippet(note.contentMd, query),
                date: note.date,
            }))
        : notes.slice(0, 6).map(note => ({
            noteId: note.id,
            title: getTitleFromMd(note.contentMd),
            snippet: plainTextFromMarkdown(note.contentMd).slice(0, 80),
            date: note.date,
        }))

    const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
        if (e.key === 'ArrowDown') {
            e.preventDefault()
            setSelectedIndex(i => Math.min(i + 1, results.length - 1))
        } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setSelectedIndex(i => Math.max(i - 1, 0))
        } else if (e.key === 'Enter' && results[selectedIndex]) {
            onOpenNote(results[selectedIndex].noteId)
            onClose()
        }
    }, [results, selectedIndex, onOpenNote, onClose])

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setSelectedIndex(0)
    }, [query])

    // Scroll selected into view
    useEffect(() => {
        const el = resultsRef.current?.querySelector(`[data-idx="${selectedIndex}"]`)
        el?.scrollIntoView({ block: 'nearest' })
    }, [selectedIndex])

    return (
        <div className="ws-search-backdrop" onClick={onClose}>
            <div className="ws-search-modal" onClick={e => e.stopPropagation()} onKeyDown={handleKeyDown}>
                <div className="ws-search-input-wrap">
                    <Search size={16} className="ws-search-input-icon" />
                    <input
                        ref={inputRef}
                        className="ws-search-input"
                        placeholder="Search notes…"
                        value={query}
                        onChange={e => setQuery(e.target.value)}
                    />
                    {query && (
                        <button type="button" className="ws-search-clear" onClick={() => setQuery('')}>
                            <X size={13} />
                        </button>
                    )}
                    <kbd className="ws-search-esc">Esc</kbd>
                </div>

                <div ref={resultsRef} className="ws-search-results">
                    {results.length === 0 ? (
                        <div className="ws-search-empty">
                            <Search size={20} strokeWidth={1.5} />
                            <span>No results for "{query}"</span>
                        </div>
                    ) : (
                        <>
                            {!query && (
                                <div className="ws-search-section-label">
                                    <Clock size={11} /> Recent notes
                                </div>
                            )}
                            {query && results.length > 0 && (
                                <div className="ws-search-section-label">
                                    <FileText size={11} /> {results.length} result{results.length !== 1 ? 's' : ''}
                                </div>
                            )}
                            {results.map((result, i) => (
                                <button
                                    key={result.noteId}
                                    type="button"
                                    data-idx={i}
                                    className={`ws-search-item ${i === selectedIndex ? 'selected' : ''}`}
                                    onClick={() => { onOpenNote(result.noteId); onClose() }}
                                    onMouseEnter={() => setSelectedIndex(i)}
                                >
                                    <div className="ws-search-item-icon">
                                        <FileText size={14} />
                                    </div>
                                    <div className="ws-search-item-body">
                                        <div className="ws-search-item-title">
                                            {query ? highlightText(result.title, query) : result.title}
                                        </div>
                                        <div className="ws-search-item-snippet">
                                            {query ? highlightText(result.snippet, query) : result.snippet}
                                        </div>
                                    </div>
                                    <div className="ws-search-item-meta">
                                        <span className="ws-search-item-date">{result.date}</span>
                                        <ArrowRight size={12} className="ws-search-item-arrow" />
                                    </div>
                                </button>
                            ))}
                        </>
                    )}
                </div>

                <div className="ws-search-footer">
                    <span><kbd>↑↓</kbd> navigate</span>
                    <span><kbd>↵</kbd> open</span>
                    <span><kbd>Esc</kbd> close</span>
                </div>
            </div>
        </div>
    )
}