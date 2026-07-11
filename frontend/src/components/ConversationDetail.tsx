import { useEffect, useState } from 'react'
import { ArrowLeft, Copy, Check, AlertCircle, Loader, MessageSquare, Quote } from 'lucide-react'
import type { ConversationDetailResponse, AgentMessage } from '../services/api'
import { getConversation } from '../services/api'
import '../styles/conversation-detail.css'

interface ConversationDetailProps {
    conversationId: string
    onBack: () => void
    className?: string
}

export function ConversationDetail({ conversationId, onBack, className = '' }: ConversationDetailProps) {
    const [conversation, setConversation] = useState<ConversationDetailResponse | null>(null)
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [copiedId, setCopiedId] = useState<string | null>(null)

    useEffect(() => {
        const loadConversation = async () => {
            setIsLoading(true)
            setError(null)
            try {
                const data = await getConversation(conversationId)
                setConversation(data)
            } catch (err) {
                setError(err instanceof Error ? err.message : 'Failed to load conversation')
            } finally {
                setIsLoading(false)
            }
        }

        loadConversation()
    }, [conversationId])

    const handleCopyMessage = (messageId: string, content: string) => {
        navigator.clipboard.writeText(content)
        setCopiedId(messageId)
        setTimeout(() => setCopiedId(null), 2000)
    }

    const formatDate = (dateString: string) => {
        return new Date(dateString).toLocaleString()
    }

    const renderMessageContent = (message: AgentMessage) => {
        switch (message.role) {
            case 'user':
                return (
                    <div className="conversation-message-content user-content">
                        <p>{message.content}</p>
                    </div>
                )
            case 'assistant':
                return (
                    <div className="conversation-message-content assistant-content">
                        <p>{message.content}</p>
                    </div>
                )
            case 'tool':
                return (
                    <div className="conversation-message-content tool-content">
                        <div className="tool-header">
                            <span className="tool-name">{message.tool_name}</span>
                        </div>
                        {message.tool_input && (
                            <div className="tool-section">
                                <div className="tool-section-label">Input:</div>
                                <pre className="tool-section-content">{message.tool_input}</pre>
                            </div>
                        )}
                        {message.tool_output && (
                            <div className="tool-section">
                                <div className="tool-section-label">Output:</div>
                                <pre className="tool-section-content">{message.tool_output}</pre>
                            </div>
                        )}
                    </div>
                )
            default:
                return <div className="conversation-message-content">{message.content}</div>
        }
    }

    if (isLoading) {
        return (
            <div className={`conversation-detail ${className}`}>
                <div className="conversation-detail-header">
                    <button onClick={onBack} className="conversation-detail-back" title="Go back">
                        <ArrowLeft size={20} />
                    </button>
                    <div className="conversation-detail-title-placeholder">
                        <Loader size={20} className="spinner" />
                    </div>
                </div>
                <div className="conversation-detail-loading">
                    <Loader size={24} className="spinner" />
                    Loading conversation...
                </div>
            </div>
        )
    }

    if (error || !conversation) {
        return (
            <div className={`conversation-detail ${className}`}>
                <div className="conversation-detail-header">
                    <button onClick={onBack} className="conversation-detail-back" title="Go back">
                        <ArrowLeft size={20} />
                    </button>
                </div>
                <div className="conversation-detail-error">
                    <AlertCircle size={32} />
                    <p>{error || 'Failed to load conversation'}</p>
                    <button onClick={onBack} className="conversation-detail-error-button">
                        Go Back
                    </button>
                </div>
            </div>
        )
    }

    return (
        <div className={`conversation-detail ${className}`}>
            <div className="conversation-detail-header">
                <button onClick={onBack} className="conversation-detail-back" title="Go back">
                    <ArrowLeft size={20} />
                </button>
                <div className="conversation-detail-title">
                    <h2>{conversation.title}</h2>
                    <div className="conversation-detail-metadata">
                        <span className="detail-meta-item">
                            <MessageSquare size={14} />
                            {conversation.message_count} messages
                        </span>
                        <span className="detail-meta-item">
                            {conversation.total_tokens.toLocaleString()} tokens
                        </span>
                        <span className="detail-meta-item">
                            {new Date(conversation.created_at).toLocaleDateString()}
                        </span>
                    </div>
                </div>
            </div>

            <div className="conversation-detail-content">
                {conversation.summary && (
                    <div className="conversation-summary-box">
                        <div className="summary-header">
                            <Quote size={16} />
                            <span>Summary</span>
                        </div>
                        <p className="summary-text">{conversation.summary}</p>
                    </div>
                )}

                <div className="conversation-messages">
                    {conversation.messages.length === 0 ? (
                        <div className="conversation-messages-empty">
                            <MessageSquare size={32} />
                            <p>No messages in this conversation</p>
                        </div>
                    ) : (
                        conversation.messages.map((message: AgentMessage) => (
                            <div key={message.id} className={`conversation-message ${message.role}`}>
                                <div className="conversation-message-header">
                                    <span className="message-role">{message.role}</span>
                                    <span className="message-time">{formatDate(message.created_at)}</span>
                                    <button
                                        className="message-copy-btn"
                                        onClick={() => handleCopyMessage(message.id, message.content)}
                                        title="Copy message"
                                    >
                                        {copiedId === message.id ? (
                                            <Check size={14} />
                                        ) : (
                                            <Copy size={14} />
                                        )}
                                    </button>
                                </div>
                                {renderMessageContent(message)}
                            </div>
                        ))
                    )}
                </div>
            </div>
        </div>
    )
}
