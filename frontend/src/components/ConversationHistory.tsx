import { useState, useEffect } from 'react'
import { MessageCircle, Trash2, AlertCircle, Loader } from 'lucide-react'
import type { ConversationListItem } from '../types'
import { listConversations, deleteConversation } from '../services/api'
import '../styles/conversation-history.css'

interface ConversationHistoryProps {
    onSelectConversation: (conversationId: string) => void
    onRefresh?: () => void
    className?: string
}

export function ConversationHistory({ onSelectConversation, onRefresh, className = '' }: ConversationHistoryProps) {
    const [conversations, setConversations] = useState<ConversationListItem[]>([])
    const [isLoading, setIsLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [hasMore, setHasMore] = useState(false)
    const [offset, setOffset] = useState(0)
    const [deletingId, setDeletingId] = useState<string | null>(null)
    const [searchQuery, setSearchQuery] = useState('')

    const limit = 50

    const loadConversations = async (newOffset = 0) => {
        setIsLoading(true)
        setError(null)
        try {
            const response = await listConversations(limit, newOffset)
            if (newOffset === 0) {
                setConversations(response.conversations)
            } else {
                setConversations(prev => [...prev, ...response.conversations])
            }
            setHasMore(response.pagination.remaining > 0)
            setOffset(newOffset)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to load conversations')
        } finally {
            setIsLoading(false)
        }
    }

    useEffect(() => {
        loadConversations(0)
    }, [])

    const handleDelete = async (conversationId: string, e: React.MouseEvent) => {
        e.stopPropagation()
        if (!window.confirm('Are you sure you want to delete this conversation? This action cannot be undone.')) {
            return
        }

        setDeletingId(conversationId)
        try {
            await deleteConversation(conversationId)
            setConversations(prev => prev.filter(c => c.id !== conversationId))
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to delete conversation')
        } finally {
            setDeletingId(null)
        }
    }

    const handleLoadMore = () => {
        loadConversations(offset + limit)
    }

    const filteredConversations = conversations.filter(conv =>
        conv.title.toLowerCase().includes(searchQuery.toLowerCase())
    )

    const formatDate = (dateString: string) => {
        const date = new Date(dateString)
        const now = new Date()
        const diffMs = now.getTime() - date.getTime()
        const diffMins = Math.floor(diffMs / 60000)
        const diffHours = Math.floor(diffMs / 3600000)
        const diffDays = Math.floor(diffMs / 86400000)

        if (diffMins < 1) return 'just now'
        if (diffMins < 60) return `${diffMins}m ago`
        if (diffHours < 24) return `${diffHours}h ago`
        if (diffDays < 7) return `${diffDays}d ago`
        return date.toLocaleDateString()
    }

    return (
        <div className={`conversation-history ${className}`}>
            <div className="conversation-history-header">
                <h3 className="conversation-history-title">
                    <MessageCircle size={18} />
                    Conversations
                </h3>
            </div>

            <div className="conversation-search">
                <input
                    type="text"
                    placeholder="Search conversations..."
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    className="conversation-search-input"
                />
            </div>

            {error && (
                <div className="conversation-error">
                    <AlertCircle size={16} />
                    {error}
                </div>
            )}

            {isLoading && conversations.length === 0 ? (
                <div className="conversation-loading">
                    <Loader size={20} className="spinner" />
                    Loading conversations...
                </div>
            ) : filteredConversations.length === 0 ? (
                <div className="conversation-empty">
                    <MessageCircle size={32} />
                    <p>{searchQuery ? 'No conversations match your search' : 'No conversations yet'}</p>
                    <p className="conversation-empty-hint">Start a new conversation with the AI assistant</p>
                </div>
            ) : (
                <>
                    <div className="conversation-list">
                        {filteredConversations.map(conv => (
                            <div
                                key={conv.id}
                                className="conversation-item"
                                onClick={() => onSelectConversation(conv.id)}
                            >
                                <div className="conversation-item-content">
                                    <div className="conversation-item-title">{conv.title}</div>
                                    <div className="conversation-item-meta">
                                        <span className="conversation-item-messages">
                                            {conv.message_count} message{conv.message_count !== 1 ? 's' : ''}
                                        </span>
                                        {conv.has_summary && (
                                            <span className="conversation-item-summary-badge">Summary</span>
                                        )}
                                        <span className="conversation-item-date">
                                            {formatDate(conv.updated_at)}
                                        </span>
                                    </div>
                                </div>
                                <button
                                    className="conversation-item-delete"
                                    onClick={e => handleDelete(conv.id, e)}
                                    disabled={deletingId === conv.id}
                                    title="Delete conversation"
                                    aria-label="Delete conversation"
                                >
                                    {deletingId === conv.id ? (
                                        <Loader size={16} className="spinner" />
                                    ) : (
                                        <Trash2 size={16} />
                                    )}
                                </button>
                            </div>
                        ))}
                    </div>

                    {hasMore && (
                        <button
                            className="conversation-load-more"
                            onClick={handleLoadMore}
                            disabled={isLoading}
                        >
                            {isLoading ? (
                                <>
                                    <Loader size={16} className="spinner" />
                                    Loading...
                                </>
                            ) : (
                                'Load More'
                            )}
                        </button>
                    )}
                </>
            )}
        </div>
    )
}
