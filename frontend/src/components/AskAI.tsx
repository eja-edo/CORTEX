import { useEffect, useState, useCallback } from 'react'
import { Sparkles, RefreshCw, X } from 'lucide-react'
import { useAgentStream } from '../hooks/useAgentStream'
import { MessageList } from './MessageList'
import { StreamingComposer } from './StreamingComposer'
import { TokenBudgetBar } from './TokenBudgetBar'

interface AskAIProps {
    noteContent?: string
    noteTitle?: string
    pendingSelection?: string
    onClose: () => void
    onInsert?: (text: string) => void
    workspaceId?: string
    onToolNavigate?: (toolName: string) => Promise<void>
    onNoteDiff?: (noteId: string, proposalId: string) => void
}

type ContextPill = {
    id: string
    text: string
    label: string
}

export function AskAI({ noteContent, noteTitle, pendingSelection, onClose, onInsert, workspaceId, onToolNavigate, onNoteDiff }: AskAIProps) {
    const stream = useAgentStream({ workspaceId, noteContent, noteTitle, pendingSelection, onToolNavigate, onNoteDiff })

    const [input, setInput] = useState('')
    const [addedPills, setAddedPills] = useState<ContextPill[]>([
        ...(noteContent ? [{ id: 'note', text: noteContent, label: `📝 ${noteTitle || 'Note'}` }] : []),
    ])
    const [pendingChangesOpen, setPendingChangesOpen] = useState(true)

    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && !stream.isLoading) onClose()
        }
        document.addEventListener('keydown', handler)
        return () => document.removeEventListener('keydown', handler)
    }, [onClose, stream.isLoading])

    const addPendingSelection = useCallback(() => {
        if (!pendingSelection || !pendingSelection.trim()) return
        const label = pendingSelection.slice(0, 40) + (pendingSelection.length > 40 ? '…' : '')
        const existingPill = addedPills.find(p => p.text === pendingSelection)
        if (!existingPill) {
            setAddedPills(prev => [...prev, {
                id: Date.now().toString(),
                text: pendingSelection,
                label: `📌 ${label}`,
            }])
        }
    }, [pendingSelection, addedPills])

    const addNotePill = useCallback(() => {
        if (noteContent && !addedPills.some(p => p.text === noteContent)) {
            setAddedPills(prev => [...prev, {
                id: Date.now().toString(),
                text: noteContent,
                label: `📝 ${noteTitle || 'Note'}`,
            }])
        }
    }, [noteContent, noteTitle, addedPills])

    return (
        <div className="ask-ai-backdrop" onClick={onClose}>
            <div className="ask-ai-panel" onClick={e => e.stopPropagation()}>
                <div className="ask-ai-header">
                    <div className="ask-ai-header-left">
                        <div className="ask-ai-icon">
                            <Sparkles size={14} />
                        </div>
                        <div className="ask-ai-title-container">
                            <span className="ask-ai-title">Ask AI</span>
                            <span className="ask-ai-subtitle">
                                {stream.conversationTitle ? stream.conversationTitle : 'Chat with your AI assistant'}
                            </span>
                        </div>
                    </div>
                    <div className="ask-ai-header-actions">
                        {stream.messages.length > 0 && (
                            <button
                                type="button"
                                className="ask-ai-icon-btn"
                                title="Clear conversation"
                                onClick={() => stream.setMessages([])}
                            >
                                <RefreshCw size={13} />
                            </button>
                        )}
                        <button
                            type="button"
                            className="ask-ai-icon-btn"
                            title="New session"
                            onClick={stream.handleNewSession}
                        >
                            <X size={14} />
                        </button>
                    </div>
                </div>

                <MessageList
                    messages={stream.messages}
                    error={stream.error}
                    onDismissError={() => stream.setError(null)}
                    sessions={stream.sessions}
                    sessionsLoading={stream.sessionsLoading}
                    sessionsLoadingMore={stream.sessionsLoadingMore}
                    onLoadSession={stream.loadSession}
                    onLoadMoreSessions={stream.loadMoreSessions}
                    onInsert={onInsert}
                    messagesEndRef={stream.messagesEndRef}
                />

                <StreamingComposer
                    input={input}
                    onInputChange={setInput}
                    onSend={(text) => {
                        stream.sendMessage(text, addedPills)
                    }}
                    isLoading={stream.isLoading}
                    onStop={stream.stopGeneration}
                    addedPills={addedPills}
                    onRemovePill={(id) => setAddedPills(prev => prev.filter(p => p.id !== id))}
                    onAddNotePill={addNotePill}
                    pendingSelection={pendingSelection}
                    onAddPendingSelection={addPendingSelection}
                    pendingChanges={stream.pendingChanges}
                    pendingChangesOpen={pendingChangesOpen}
                    onTogglePendingChanges={() => setPendingChangesOpen(v => !v)}
                    onAcceptChange={(changeId, actionId) => stream.acceptChange(changeId, actionId)}
                    onUndoChange={(change) => { void stream.undoChange(change) }}
                    onAcceptAllChanges={stream.acceptAllChanges}
                    onUndoAllChanges={() => { void stream.undoAllChanges() }}
                    selectedModel={stream.selectedModel}
                    onModelChange={stream.handleModelChange}
                />

                <TokenBudgetBar lastUsage={stream.lastUsage} lastModelUsed={stream.lastModelUsed} />
            </div>
        </div>
    )
}
