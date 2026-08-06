import { useCallback, useMemo, useState } from 'react'
import { Bot, Copy, Check, X } from 'lucide-react'
import type { ConversationListItem } from '../services/api'
import { renderMarkdownToSanitizedHtml } from '../utils/markdown/renderToHtml'
import { ToolExecutionIndicator } from './ToolExecutionIndicator'
import type { AgentMessage } from '../hooks/useAgentStream'

interface MessageListProps {
    messages: AgentMessage[]
    error: string | null
    onDismissError: () => void
    sessions: ConversationListItem[]
    sessionsLoading: boolean
    sessionsLoadingMore: boolean
    onLoadSession: (sessionId: string) => void
    onLoadMoreSessions: () => void
    onInsert?: (text: string) => void
    messagesEndRef: React.RefObject<HTMLDivElement | null>
}

export function MessageList({
    messages, error, onDismissError,
    sessions, sessionsLoading, sessionsLoadingMore,
    onLoadSession, onLoadMoreSessions,
    onInsert,
    messagesEndRef,
}: MessageListProps) {
    const [copiedId, setCopiedId] = useState<string | null>(null)
    // Thinking steps are expanded by default; this only records messages the
    // user explicitly toggled, so their choice wins over the default.
    const [thinkingOverrides, setThinkingOverrides] = useState<Record<string, boolean>>({})
    const renderMarkdown = useMemo(() => renderMarkdownToSanitizedHtml, [])

    const toggleThinking = useCallback((messageId: string) => {
        setThinkingOverrides(prev => ({ ...prev, [messageId]: !(prev[messageId] ?? true) }))
    }, [])

    const handleCopy = useCallback(async (id: string, content: string) => {
        await navigator.clipboard.writeText(content)
        setCopiedId(id)
        setTimeout(() => setCopiedId(null), 2000)
    }, [])

    return (
        <div className="ask-ai-messages">
            {error && (
                <div className="ask-ai-error-banner">
                    <span>{error}</span>
                    <button onClick={onDismissError} className="ask-ai-error-close">
                        <X size={14} />
                    </button>
                </div>
            )}
            {messages.length === 0 ? (
                <div className="ask-ai-empty">
                    <div className="ask-ai-empty-icon">
                        <Bot size={28} strokeWidth={1.5} />
                    </div>
                    <div className="ask-ai-empty-title">How can I help?</div>
                    <div className="ask-ai-empty-sub">
                        Select a session or ask anything.
                    </div>
                    <div className="ask-ai-quick-actions">
                        {sessionsLoading ? (
                            <div style={{ padding: '12px', textAlign: 'center', color: '#888', fontSize: '14px' }}>
                                Loading sessions...
                            </div>
                        ) : sessions.length > 0 ? (
                            sessions.map(session => (
                                <button
                                    key={session.id}
                                    type="button"
                                    className="ask-ai-quick-btn"
                                    onClick={() => onLoadSession(session.id)}
                                    title={`Last updated: ${new Date(session.updated_at).toLocaleString()}`}
                                >
                                    <div style={{ textAlign: 'left' }}>
                                        <div style={{ fontWeight: 500, marginBottom: '2px' }}>
                                            {session.title || 'Untitled Session'}
                                        </div>
                                        <div style={{ fontSize: '12px', color: '#999' }}>
                                            {session.message_count} messages
                                        </div>
                                    </div>
                                </button>
                            ))
                        ) : (
                            <div style={{ padding: '12px', textAlign: 'center', color: '#888', fontSize: '14px' }}>
                                No sessions yet
                            </div>
                        )}
                        {sessions.length > 0 && (
                            <button
                                type="button"
                                className="ask-ai-more-btn"
                                onClick={onLoadMoreSessions}
                                disabled={sessionsLoadingMore}
                            >
                                {sessionsLoadingMore ? 'Loading...' : 'More'}
                            </button>
                        )}
                    </div>
                </div>
            ) : (
                messages.map(msg => (
                    <div key={msg.id} className={`ask-ai-msg ask-ai-msg--${msg.role}`}>
                        <div className="ask-ai-msg-bubble">
                            {msg.role === 'user' ? (
                                <div className="ask-ai-msg-content">{msg.content}</div>
                            ) : (
                                <div className="ask-ai-stream">
                                    {msg.loading && (
                                        <ToolExecutionIndicator
                                            msg={{ ...msg, thinkingOpen: thinkingOverrides[msg.id] ?? true }}
                                            onToggleThinking={toggleThinking}
                                        />
                                    )}
                                    {(msg.thinkingSteps ?? []).filter(s => s.type === 'text').map(s => (
                                        <div key={s.id} className="ask-ai-step ask-ai-step--text">
                                            <span
                                                className="ask-ai-step-body ask-ai-step-body--text"
                                                dangerouslySetInnerHTML={{
                                                    __html: renderMarkdown(s.text ?? '')
                                                }}
                                            />
                                        </div>
                                    ))}
                                    {(msg.thinkingSteps ?? []).filter(s => s.type === 'text').length === 0 && msg.content && (
                                        <div className="ask-ai-step ask-ai-step--text">
                                            <span
                                                className="ask-ai-step-body ask-ai-step-body--text"
                                                dangerouslySetInnerHTML={{
                                                    __html: renderMarkdown(msg.content)
                                                }}
                                            />
                                        </div>
                                    )}

                                    {!msg.loading && (
                                        <div className="ask-ai-msg-actions">
                                            <button
                                                type="button"
                                                className="ask-ai-msg-action-btn"
                                                title="Copy full reply"
                                                onClick={() => {
                                                    const steppedText = (msg.thinkingSteps ?? [])
                                                        .filter(s => s.type === 'text')
                                                        .map(s => s.text ?? '')
                                                        .join('')
                                                    const text = steppedText || msg.content || ''
                                                    void handleCopy(msg.id, text)
                                                }}
                                            >
                                                {copiedId === msg.id ? <Check size={11} /> : <Copy size={11} />}
                                            </button>
                                            {onInsert && (
                                                <button
                                                    type="button"
                                                    className="ask-ai-msg-action-btn"
                                                    title="Insert into note"
                                                    onClick={() => {
                                                        const steppedText = (msg.thinkingSteps ?? [])
                                                            .filter(s => s.type === 'text')
                                                            .map(s => s.text ?? '')
                                                            .join('')
                                                        onInsert(steppedText || msg.content || '')
                                                    }}
                                                >
                                                    Insert
                                                </button>
                                            )}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                ))
            )}
            <div ref={messagesEndRef} />
        </div>
    )
}
