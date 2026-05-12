import { useCallback, useEffect, useRef, useState } from 'react'
import { Bot, Send, X, Sparkles, RefreshCw, Copy, Check } from 'lucide-react'
import { streamAgentMessage, listConversations, getConversation, type ConversationListItem } from '../services/api'
import { useConversationStore } from '../stores/conversationStore'

interface AskAIProps {
    noteContent?: string
    noteTitle?: string
    pendingSelection?: string
    onClose: () => void
    onInsert?: (text: string) => void
}

type ContextPill = {
    id: string
    text: string
    label: string
}

type Message = {
    id: string
    role: 'user' | 'assistant'
    content: string
    loading?: boolean
    thinkingOpen?: boolean
    thinkingSteps?: Array<{
        id: string
        type: 'tool_start' | 'tool_result'
        toolName: string
        toolArgs?: Record<string, unknown>
        result?: unknown
    }>
}

export function AskAI({ noteContent, noteTitle, pendingSelection, onClose, onInsert }: AskAIProps) {
    const STORAGE_KEY = 'cortex_chatbot_state'

    const [messages, setMessages] = useState<Message[]>([])
    const [input, setInput] = useState('')
    const [isLoading, setIsLoading] = useState(false)
    const [copiedId, setCopiedId] = useState<string | null>(null)
    const [conversationId, setConversationId] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [sessions, setSessions] = useState<ConversationListItem[]>([])
    const [sessionsLoading, setSessionsLoading] = useState(true)
    const [sessionsLoadingMore, setSessionsLoadingMore] = useState(false)
    const [sessionsOffset, setSessionsOffset] = useState(0)
    const [isInitializing, setIsInitializing] = useState(true) // Track if we're loading from localStorage
    const [addedPills, setAddedPills] = useState<ContextPill[]>([
        ...(noteContent ? [{ id: 'note', text: noteContent, label: `📝 ${noteTitle || 'Note'}` }] : []),
    ])
    const inputRef = useRef<HTMLTextAreaElement>(null)
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const { updateTokenUsage } = useConversationStore()

    useEffect(() => {
        inputRef.current?.focus()
    }, [])

    // Load state from localStorage on mount
    useEffect(() => {
        try {
            const savedState = localStorage.getItem(STORAGE_KEY)
            if (savedState) {
                const state = JSON.parse(savedState)
                if (state.conversationId) {
                    setConversationId(state.conversationId)
                }
                if (state.messages && Array.isArray(state.messages)) {
                    setMessages(state.messages)
                }
            }
        } catch (err) {
            console.error('Failed to load chatbot state from localStorage:', err)
        } finally {
            // Mark initialization as complete
            setIsInitializing(false)
        }
    }, [])

    // Save state to localStorage whenever messages or conversationId changes
    // But skip saving during initial load
    useEffect(() => {
        if (isInitializing) {
            return
        }

        try {
            const state = {
                conversationId,
                messages,
            }
            localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
        } catch (err) {
            console.error('Failed to save chatbot state to localStorage:', err)
        }
    }, [conversationId, messages, isInitializing])

    // Fetch sessions on component mount
    useEffect(() => {
        const fetchSessions = async () => {
            try {
                setSessionsLoading(true)
                const response = await listConversations(5, 0) // Limit to 5 recent sessions
                setSessions(response.conversations)
            } catch (err) {
                console.error('❌ Failed to fetch sessions:', err)
                setSessions([])
            } finally {
                setSessionsLoading(false)
            }
        }

        fetchSessions()
    }, [])


    // Build minimal runtime UI context (collected at send time)
    const buildRuntimeContextText = useCallback(() => {
        if (typeof window === 'undefined') return ''
        try {
            const url = window.location.href
            const locale = navigator.language || 'unknown'
            const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
            const now = new Date()
            const timeIso = now.toISOString()
            return `URL: ${url}\nTime: ${timeIso}\nTimezone: ${tz}\nLocale: ${locale}`
        } catch (e) {
            return ''
        }
    }, [])

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

    // Load a session/conversation
    const loadSession = useCallback(async (sessionId: string) => {
        try {
            setIsLoading(true)
            const conversation = await getConversation(sessionId)

            // Convert conversation messages to Message format
            const loadedMessages: Message[] = conversation.messages.map(msg => ({
                id: msg.id,
                role: msg.role as 'user' | 'assistant',
                content: msg.content,
            }))

            setMessages(loadedMessages)
            setConversationId(sessionId)
            setSessions([]) // Clear sessions list after selection
        } catch (err) {
            setError(`Failed to load session: ${err instanceof Error ? err.message : 'Unknown error'}`)
        } finally {
            setIsLoading(false)
        }
    }, [])

    // Load more sessions
    const loadMoreSessions = useCallback(async () => {
        try {
            setSessionsLoadingMore(true)
            const newOffset = sessionsOffset + 5
            const response = await listConversations(10, newOffset)
            if (response.conversations.length > 0) {
                setSessions(prev => [...prev, ...response.conversations])
                setSessionsOffset(newOffset)
            }
        } catch (err) {
            console.error('Failed to load more sessions:', err)
        } finally {
            setSessionsLoadingMore(false)
        }
    }, [sessionsOffset])

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [messages])

    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && !isLoading) onClose()
        }
        document.addEventListener('keydown', handler)
        return () => document.removeEventListener('keydown', handler)
    }, [onClose, isLoading])

    const sendMessage = useCallback(async (text: string) => {
        if (!text.trim() || isLoading) return
        const userMsg = text.trim()
        setInput('')
        setError(null)

        const userMsgObj: Message = {
            id: Date.now().toString(),
            role: 'user',
            content: userMsg,
        }
        const loadingMsgObj: Message = {
            id: (Date.now() + 1).toString(),
            role: 'assistant',
            content: '',
            loading: true,
            thinkingOpen: false,
            thinkingSteps: [],
        }

        setMessages(prev => [...prev, userMsgObj, loadingMsgObj])
        setIsLoading(true)

        try {
            // Prepare combined message: include user-selected context (pills) and runtime UI context
            const runtimeText = buildRuntimeContextText()
            const pillsText = addedPills.length > 0 ? addedPills.map(p => p.text).join('\n\n---\n\n') : ''
            let finalMessage = userMsg
            const parts: string[] = []
            if (pillsText) parts.push(`Context:\n\n${pillsText}`)
            if (runtimeText) parts.push(`Runtime UI Context:\n\n${runtimeText}`)
            if (parts.length > 0) finalMessage = `${parts.join('\n\n')}\n\n${userMsg}`

            // Call streaming agent API
            let fullReply = ''
            let finalConversationId: string | null = null
            let thinkingSteps: Message['thinkingSteps'] = []

            for await (const event of streamAgentMessage(finalMessage, conversationId || undefined)) {
                if (event.type === 'text' && event.text) {
                    fullReply += event.text
                    setMessages(prev =>
                        prev.map(m => m.id === loadingMsgObj.id
                            ? { ...m, content: fullReply, loading: false, thinkingSteps }
                            : m
                        )
                    )
                } else if (event.type === 'tool_start' && event.tool_name) {
                    const stepId = `step-${Date.now()}-${Math.random()}`
                    const step = {
                        id: stepId,
                        type: 'tool_start' as const,
                        toolName: event.tool_name,
                        toolArgs: event.tool_args,
                    }
                    thinkingSteps = [...thinkingSteps, step]
                    setMessages(prev =>
                        prev.map(m => m.id === loadingMsgObj.id
                            ? { ...m, thinkingSteps, loading: true }
                            : m
                        )
                    )
                } else if (event.type === 'tool_result' && event.tool_name) {
                    const step = {
                        id: `result-${Date.now()}-${Math.random()}`,
                        type: 'tool_result' as const,
                        toolName: event.tool_name,
                        result: event.result,
                    }
                    thinkingSteps = [...thinkingSteps, step]
                    setMessages(prev =>
                        prev.map(m => m.id === loadingMsgObj.id
                            ? { ...m, thinkingSteps }
                            : m
                        )
                    )
                } else if (event.type === 'done' && event.conversation_id) {
                    finalConversationId = event.conversation_id
                }
            }

            // Update conversation ID if this is the first message
            if (!conversationId && finalConversationId) {
                setConversationId(finalConversationId)
            }

            // Update token usage in store
            updateTokenUsage(0) // Placeholder - real implementation would get actual usage

            setMessages(prev =>
                prev.map(m => m.id === loadingMsgObj.id
                    ? { ...m, content: fullReply, loading: false, thinkingSteps }
                    : m
                )
            )
        } catch (err) {
            const errorMsg = err instanceof Error ? err.message : 'Failed to get response. Please try again.'
            setError(errorMsg)
            setMessages(prev =>
                prev.map(m => m.id === loadingMsgObj.id
                    ? { ...m, content: errorMsg, loading: false }
                    : m
                )
            )
        } finally {
            setIsLoading(false)
        }
    }, [isLoading, conversationId, updateTokenUsage, addedPills, buildRuntimeContextText])

    const toggleThinking = useCallback((messageId: string) => {
        setMessages(prev => prev.map(m =>
            m.id === messageId
                ? { ...m, thinkingOpen: !m.thinkingOpen }
                : m
        ))
    }, [])

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            void sendMessage(input)
        }
    }

    const handleCopy = async (id: string, content: string) => {
        await navigator.clipboard.writeText(content)
        setCopiedId(id)
        setTimeout(() => setCopiedId(null), 2000)
    }

    const renderMarkdown = (text: string): string => {
        return text
            .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="lang-$1">$2</code></pre>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/^### (.+)$/gm, '<h3>$1</h3>')
            .replace(/^## (.+)$/gm, '<h2>$1</h2>')
            .replace(/^# (.+)$/gm, '<h1>$1</h1>')
            .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
            .replace(/(<li>.*<\/li>\n?)+/g, s => `<ul>${s}</ul>`)
            .replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>')
            .replace(/\n\n/g, '</p><p>')
            .replace(/^(?!<[huplo]|<\/[huplo]|<pre|<\/pre)(.+)$/gm, '<p>$1</p>')
    }

    return (
        <div className="ask-ai-backdrop" onClick={onClose}>
            <div className="ask-ai-panel" onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div className="ask-ai-header">
                    <div className="ask-ai-header-left">
                        <div className="ask-ai-icon">
                            <Sparkles size={14} />
                        </div>
                        <span className="ask-ai-title">Ask AI</span>
                    </div>
                    <div className="ask-ai-header-actions">
                        {messages.length > 0 && (
                            <button
                                type="button"
                                className="ask-ai-icon-btn"
                                title="Clear conversation"
                                onClick={() => setMessages([])}
                            >
                                <RefreshCw size={13} />
                            </button>
                        )}
                        <button type="button" className="ask-ai-icon-btn" onClick={onClose}>
                            <X size={14} />
                        </button>
                    </div>
                </div>

                {/* Messages */}
                <div className="ask-ai-messages">
                    {error && (
                        <div className="ask-ai-error-banner">
                            <span>{error}</span>
                            <button onClick={() => setError(null)} className="ask-ai-error-close">
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
                                {noteContent ? 'I have context from your current note.' : 'Select a session or ask anything.'}
                            </div>
                            {/* Display Sessions */}
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
                                            onClick={() => void loadSession(session.id)}
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
                                        onClick={() => void loadMoreSessions()}
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
                                {msg.role === 'assistant' && (
                                    <div className="ask-ai-msg-icon">
                                        <Sparkles size={12} />
                                    </div>
                                )}
                                <div className="ask-ai-msg-bubble">
                                    {msg.loading ? (
                                        <div className="ask-ai-thinking-container">
                                            <div className="ask-ai-thinking">
                                                <span /><span /><span />
                                            </div>
                                            {msg.thinkingSteps && msg.thinkingSteps.length > 0 && (
                                                <div className="ask-ai-thinking-wrapper">
                                                    <button
                                                        type="button"
                                                        className="ask-ai-thinking-toggle"
                                                        onClick={() => toggleThinking(msg.id)}
                                                    >
                                                        {msg.loading ? 'Thinking' : 'Thoughts'}
                                                        <span className={`ask-ai-thinking-toggle-icon ${msg.thinkingOpen ? 'open' : ''}`}>
                                                            ▾
                                                        </span>
                                                    </button>
                                                    {msg.thinkingOpen && (
                                                        <div className="ask-ai-thinking-steps">
                                                            {msg.thinkingSteps.map(step => (
                                                                <div key={step.id} className="ask-ai-thinking-step">
                                                                    {step.type === 'tool_start' && (
                                                                        <div className="ask-ai-step-item">
                                                                            <span className="ask-ai-step-badge">📌</span>
                                                                            <span className="ask-ai-step-text">
                                                                                Using <strong>{step.toolName}</strong>
                                                                                {step.toolArgs && Object.keys(step.toolArgs).length > 0 && (
                                                                                    <code style={{ marginLeft: '4px', fontSize: '11px' }}>
                                                                                        {JSON.stringify(step.toolArgs).slice(0, 60)}...
                                                                                    </code>
                                                                                )}
                                                                            </span>
                                                                        </div>
                                                                    )}
                                                                    {step.type === 'tool_result' && (
                                                                        <div className="ask-ai-step-item">
                                                                            <span className="ask-ai-step-badge">✓</span>
                                                                            <span className="ask-ai-step-text">
                                                                                Got result from <strong>{step.toolName}</strong>
                                                                                {step.result ? (() => {
                                                                                    const resultStr = typeof step.result === 'string'
                                                                                        ? step.result
                                                                                        : JSON.stringify(step.result);
                                                                                    return (
                                                                                        <code style={{ marginLeft: '4px', fontSize: '11px' }}>
                                                                                            {resultStr.slice(0, 60)}...
                                                                                        </code>
                                                                                    );
                                                                                })() : null}
                                                                            </span>
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    ) : (
                                        <>
                                            {msg.role === 'assistant' ? (
                                                <div
                                                    className="ask-ai-msg-content"
                                                    dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
                                                />
                                            ) : (
                                                <div className="ask-ai-msg-content">{msg.content}</div>
                                            )}

                                            {msg.role === 'assistant' && !msg.loading && (
                                                <div className="ask-ai-msg-actions">
                                                    <button
                                                        type="button"
                                                        className="ask-ai-msg-action-btn"
                                                        title="Copy"
                                                        onClick={() => void handleCopy(msg.id, msg.content)}
                                                    >
                                                        {copiedId === msg.id ? <Check size={11} /> : <Copy size={11} />}
                                                    </button>
                                                    {onInsert && (
                                                        <button
                                                            type="button"
                                                            className="ask-ai-msg-action-btn"
                                                            title="Insert into note"
                                                            onClick={() => onInsert(msg.content)}
                                                        >
                                                            Insert
                                                        </button>
                                                    )}
                                                </div>
                                            )}
                                        </>
                                    )}
                                </div>
                            </div>
                        ))
                    )}
                    <div ref={messagesEndRef} />
                </div>

                {/* Input */}
                <div className="ask-ai-input-area">
                    {pendingSelection && !addedPills.some(p => p.text === pendingSelection) ||
                        !pendingSelection && noteContent && !addedPills.some(p => p.text === noteContent) ||
                        addedPills.length > 0 ? (
                        <div className="ask-ai-context-area">
                            <div className="ask-ai-context-pills">
                                {/* Pending Selection - only show if not already added */}
                                {pendingSelection && !addedPills.some(p => p.text === pendingSelection) && (
                                    <div className="ask-ai-context-pill ask-ai-context-pill--pending">
                                        <span className="ask-ai-context-pill-text" title={pendingSelection}>
                                            {pendingSelection.slice(0, 40) + (pendingSelection.length > 40 ? '…' : '')}
                                        </span>
                                        <button
                                            type="button"
                                            className="ask-ai-context-pill-action"
                                            onClick={addPendingSelection}
                                            title="Add to context"
                                        >
                                            +
                                        </button>
                                    </div>
                                )}

                                {/* Add Full Note - only show if no pending and note not added */}
                                {!pendingSelection && noteContent && !addedPills.some(p => p.text === noteContent) && (
                                    <div className="ask-ai-context-pill ask-ai-context-pill--pending">
                                        <span className="ask-ai-context-pill-text" title="Add full note content">
                                            Add full note
                                        </span>
                                        <button
                                            type="button"
                                            className="ask-ai-context-pill-action"
                                            onClick={() => {
                                                setAddedPills(prev => [...prev, {
                                                    id: Date.now().toString(),
                                                    text: noteContent,
                                                    label: `📝 ${noteTitle || 'Note'}`,
                                                }])
                                            }}
                                            title="Add to context"
                                        >
                                            +
                                        </button>
                                    </div>
                                )}

                                {/* Added Pills */}
                                {addedPills.map(pill => (
                                    <div key={pill.id} className="ask-ai-context-pill ask-ai-context-pill--added">
                                        <span className="ask-ai-context-pill-text" title={pill.text}>
                                            {pill.label}
                                        </span>
                                        <button
                                            type="button"
                                            className="ask-ai-context-pill-action"
                                            onClick={() => setAddedPills(prev => prev.filter(p => p.id !== pill.id))}
                                            title="Remove from context"
                                        >
                                            ×
                                        </button>
                                    </div>
                                ))}
                                {/* runtime context is collected automatically on send; no manual refresh UI */}
                            </div>
                        </div>
                    ) : null}
                    <div className="ask-ai-input-wrapper">
                        <textarea
                            ref={inputRef}
                            className="ask-ai-input"
                            placeholder="Ask anything… (Enter to send, Shift+Enter for newline)"
                            value={input}
                            onChange={e => setInput(e.target.value)}
                            onKeyDown={handleKeyDown}
                            rows={1}
                            disabled={isLoading}
                        />
                        <button
                            type="button"
                            className={`ask-ai-send-btn ${input.trim() && !isLoading ? 'active' : ''}`}
                            onClick={() => void sendMessage(input)}
                            disabled={!input.trim() || isLoading}
                        >
                            <Send size={14} />
                        </button>
                    </div>
                </div>
            </div>
        </div>
    )
}