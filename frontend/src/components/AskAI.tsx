import { useCallback, useEffect, useRef, useState } from 'react'
import { Bot, Send, X, Sparkles, RefreshCw, Copy, Check } from 'lucide-react'

interface AskAIProps {
    noteContent?: string
    noteTitle?: string
    onClose: () => void
    onInsert?: (text: string) => void
}

type Message = {
    id: string
    role: 'user' | 'assistant'
    content: string
    loading?: boolean
}

const SYSTEM_PROMPT = `You are an intelligent writing assistant embedded in a note-taking workspace called Cortex. You help users think, write, research, and organize their notes.

When given note context, you can reference it. Be concise, insightful, and practical. Use markdown in your responses when it helps clarity (headers, bullets, code blocks). Don't be verbose.`

const QUICK_PROMPTS = [
    { label: 'Summarize', prompt: 'Summarize this note in 3 bullet points' },
    { label: 'Improve writing', prompt: 'Improve the writing style and clarity of this note' },
    { label: 'Find action items', prompt: 'Extract all action items and tasks from this note' },
    { label: 'Generate outline', prompt: 'Create a structured outline based on this note' },
    { label: 'Explain concepts', prompt: 'Explain the key concepts in this note simply' },
]

export function AskAI({ noteContent, noteTitle, onClose, onInsert }: AskAIProps) {
    const [messages, setMessages] = useState<Message[]>([])
    const [input, setInput] = useState('')
    const [isLoading, setIsLoading] = useState(false)
    const [copiedId, setCopiedId] = useState<string | null>(null)
    const inputRef = useRef<HTMLTextAreaElement>(null)
    const messagesEndRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        inputRef.current?.focus()
    }, [])

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

    const buildMessages = useCallback((userMsg: string) => {
        const msgs: Array<{ role: string; content: string }> = []

        // Add note context as first user message if available
        if (noteContent) {
            msgs.push({
                role: 'user',
                content: `Here is my current note${noteTitle ? ` titled "${noteTitle}"` : ''}:\n\n${noteContent}\n\nPlease use this as context for our conversation.`,
            })
            msgs.push({
                role: 'assistant',
                content: 'I\'ve read your note and I\'m ready to help. What would you like to know or do with it?',
            })
        }

        // Add conversation history
        for (const msg of messages) {
            if (!msg.loading) {
                msgs.push({ role: msg.role, content: msg.content })
            }
        }

        // Add new user message
        msgs.push({ role: 'user', content: userMsg })

        return msgs
    }, [messages, noteContent, noteTitle])

    const sendMessage = useCallback(async (text: string) => {
        if (!text.trim() || isLoading) return
        const userMsg = text.trim()
        setInput('')

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
        }

        setMessages(prev => [...prev, userMsgObj, loadingMsgObj])
        setIsLoading(true)

        try {
            const builtMessages = buildMessages(userMsg)

            const response = await fetch('https://api.anthropic.com/v1/messages', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    model: 'claude-sonnet-4-20250514',
                    max_tokens: 1000,
                    system: SYSTEM_PROMPT,
                    messages: builtMessages,
                }),
            })

            const data = await response.json()
            const content = data.content
                ?.filter((b: { type: string }) => b.type === 'text')
                .map((b: { text: string }) => b.text)
                .join('') ?? 'Sorry, I could not generate a response.'

            setMessages(prev =>
                prev.map(m => m.id === loadingMsgObj.id
                    ? { ...m, content, loading: false }
                    : m
                )
            )
        } catch {
            setMessages(prev =>
                prev.map(m => m.id === loadingMsgObj.id
                    ? { ...m, content: 'Failed to get response. Please try again.', loading: false }
                    : m
                )
            )
        } finally {
            setIsLoading(false)
        }
    }, [isLoading, buildMessages])

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
                        {noteTitle && (
                            <span className="ask-ai-context-pill">
                                📝 {noteTitle.slice(0, 24)}{noteTitle.length > 24 ? '…' : ''}
                            </span>
                        )}
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
                    {messages.length === 0 ? (
                        <div className="ask-ai-empty">
                            <div className="ask-ai-empty-icon">
                                <Bot size={28} strokeWidth={1.5} />
                            </div>
                            <div className="ask-ai-empty-title">How can I help?</div>
                            <div className="ask-ai-empty-sub">
                                {noteContent ? 'I have context from your current note.' : 'Ask anything or select a quick action.'}
                            </div>
                            {noteContent && (
                                <div className="ask-ai-quick-actions">
                                    {QUICK_PROMPTS.map(qp => (
                                        <button
                                            key={qp.label}
                                            type="button"
                                            className="ask-ai-quick-btn"
                                            onClick={() => void sendMessage(qp.prompt)}
                                        >
                                            {qp.label}
                                        </button>
                                    ))}
                                </div>
                            )}
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
                                        <div className="ask-ai-thinking">
                                            <span /><span /><span />
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
    )
}