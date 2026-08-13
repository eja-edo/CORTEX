import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUp, Square, Plus, Mic, FileText, ChevronDown, Check } from 'lucide-react'
import type { PendingChange, AvailableModel } from '../services/api'

interface ContextPill {
    id: string
    text: string
    label: string
}

interface StreamingComposerProps {
    input: string
    onInputChange: (value: string) => void
    onSend: (text: string) => void
    isLoading: boolean
    onStop: () => void
    addedPills: ContextPill[]
    onRemovePill: (id: string) => void
    onAddNotePill: () => void
    pendingSelection?: string
    onAddPendingSelection: () => void
    pendingChanges: PendingChange[]
    pendingChangesOpen: boolean
    onTogglePendingChanges: () => void
    onAcceptChange: (changeId: string, actionId: string) => void
    onUndoChange: (change: PendingChange) => void
    onAcceptAllChanges: () => void
    onUndoAllChanges: () => void
    selectedModel: string
    onModelChange: (model: string) => void
    availableModels: AvailableModel[]
}

export function StreamingComposer({
    input, onInputChange, onSend, isLoading, onStop,
    addedPills, onRemovePill, onAddNotePill,
    pendingSelection, onAddPendingSelection,
    pendingChanges, pendingChangesOpen, onTogglePendingChanges,
    onAcceptChange, onUndoChange, onAcceptAllChanges, onUndoAllChanges,
    selectedModel, onModelChange, availableModels,
}: StreamingComposerProps) {
    const inputRef = useRef<HTMLTextAreaElement>(null)
    const modelDropdownRef = useRef<HTMLDivElement>(null)
    const [modelDropdownOpen, setModelDropdownOpen] = useState(false)

    const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            onSend(input)
        }
    }, [onSend, input])

    useEffect(() => {
        inputRef.current?.focus()
    }, [])

    useEffect(() => {
        if (!modelDropdownOpen) return
        const handler = (e: MouseEvent) => {
            if (modelDropdownRef.current && !modelDropdownRef.current.contains(e.target as Node)) {
                setModelDropdownOpen(false)
            }
        }
        document.addEventListener('mousedown', handler)
        return () => document.removeEventListener('mousedown', handler)
    }, [modelDropdownOpen])

    return (
        <div className="ask-ai-input-area">
            {addedPills.length > 0 && (
                <div className="ask-ai-context-pills ask-ai-context-pills--bar">
                    {addedPills.map(pill => (
                        <div key={pill.id} className="ask-ai-context-pill ask-ai-context-pill--added">
                            <span className="ask-ai-context-pill-text" title={pill.text}>
                                {pill.label}
                            </span>
                            <button
                                type="button"
                                className="ask-ai-context-pill-action"
                                onClick={() => onRemovePill(pill.id)}
                                title="Remove from context"
                            >
                                ×
                            </button>
                        </div>
                    ))}
                </div>
            )}
            {pendingChanges.length > 0 && (
                <div className="ask-ai-changes-area">
                    <button
                        type="button"
                        className="ask-ai-changes-toggle"
                        onClick={onTogglePendingChanges}
                    >
                        <span>Pending Changes ({pendingChanges.length})</span>
                        <span className={`ask-ai-changes-toggle-icon ${pendingChangesOpen ? 'open' : ''}`}>▾</span>
                    </button>
                    {pendingChangesOpen && (
                        <div className="ask-ai-changes-list">
                            <div className="ask-ai-changes-bulk-actions">
                                <button type="button" className="ask-ai-changes-bulk-btn accept-all" onClick={onAcceptAllChanges}>
                                    Accept All
                                </button>
                                <button type="button" className="ask-ai-changes-bulk-btn undo-all" onClick={() => void onUndoAllChanges()}>
                                    Undo All
                                </button>
                            </div>
                            {pendingChanges.map(change => (
                                <div key={change.id} className="ask-ai-changes-item">
                                    <div className="ask-ai-changes-item-info">
                                        <span className="ask-ai-changes-item-icon">
                                            {change.toolName.includes('note') ? '📝' : '📅'}
                                        </span>
                                        <span className="ask-ai-changes-item-text">
                                            <strong>{change.description}</strong>: {change.title}
                                        </span>
                                    </div>
                                    <div className="ask-ai-changes-item-actions">
                                        <button
                                            type="button"
                                            className="ask-ai-changes-item-btn accept"
                                            onClick={() => onAcceptChange(change.id, change.actionId)}
                                        >
                                            Accept
                                        </button>
                                        <button
                                            type="button"
                                            className="ask-ai-changes-item-btn undo"
                                            onClick={() => void onUndoChange(change)}
                                        >
                                            Undo
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
            <div className="ask-ai-input-wrapper">
                <textarea
                    ref={inputRef}
                    className="ask-ai-input"
                    placeholder="Ask anything…"
                    value={input}
                    onChange={e => onInputChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    disabled={isLoading}
                />
                <button
                    type="button"
                    className="ask-ai-mic-btn"
                    title="Voice input"
                    disabled={isLoading}
                >
                    <Mic size={15} />
                </button>
            </div>
            <div className="ask-ai-bottom-bar">
                <div className="ask-ai-bottom-left">
                    <button
                        type="button"
                        className="ask-ai-bottom-icon-btn"
                        title="Add context"
                        onClick={onAddNotePill}
                    >
                        <Plus size={15} />
                    </button>
                    {pendingSelection && !addedPills.some(p => p.text === pendingSelection) && (
                        <button
                            type="button"
                            className="ask-ai-bottom-icon-btn"
                            title="Add selected text"
                            onClick={onAddPendingSelection}
                        >
                            <FileText size={14} />
                        </button>
                    )}
                </div>
                <div className="ask-ai-bottom-right">
                    <div className="ask-ai-model-select" ref={modelDropdownRef}>
                        <button
                            type="button"
                            className="ask-ai-model-trigger"
                            onClick={() => setModelDropdownOpen(v => !v)}
                            disabled={isLoading}
                            title="Select model"
                        >
                            <span className="ask-ai-model-trigger-label">
                                {availableModels.find(m => m.id === selectedModel)?.label || 'Auto'}
                            </span>
                            <ChevronDown size={11} className={`ask-ai-model-chevron ${modelDropdownOpen ? 'open' : ''}`} />
                        </button>
                        {modelDropdownOpen && (
                            <div className="ask-ai-model-dropdown">
                                {availableModels.map((m) => (
                                    <button
                                        key={m.id}
                                        type="button"
                                        className={`ask-ai-model-option ${m.id === selectedModel ? 'active' : ''}`}
                                        onClick={() => {
                                            onModelChange(m.id)
                                            setModelDropdownOpen(false)
                                        }}
                                    >
                                        <span className="ask-ai-model-option-label">{m.label}</span>
                                        {m.id === selectedModel && <Check size={12} className="ask-ai-model-option-check" />}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                    {isLoading ? (
                        <button
                            type="button"
                            className="ask-ai-stop-btn"
                            onClick={onStop}
                            title="Stop generating"
                        >
                            <Square size={13} />
                        </button>
                    ) : (
                        <button
                            type="button"
                            className={`ask-ai-send-btn ${input.trim() ? 'active' : ''}`}
                            onClick={() => onSend(input)}
                            disabled={!input.trim()}
                            title="Send"
                        >
                            <ArrowUp size={16} />
                        </button>
                    )}
                </div>
            </div>
        </div>
    )
}
