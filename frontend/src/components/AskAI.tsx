import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, ArrowUp, X, Sparkles, RefreshCw, Copy, Check, Square, Plus, Mic, FileText, ChevronDown } from 'lucide-react'
import { streamAgentMessage, listConversations, getConversation, revertAction, ApiError, type ConversationListItem, type StreamEvent, type PendingChange, type TokenUsage } from '../services/api'
import { useConversationStore } from '../stores/conversationStore'
import { knowledgeRoute, noteRoute, scheduleRoute } from '../services/routes'

interface AskAIProps {
    noteContent?: string
    noteTitle?: string
    pendingSelection?: string
    onClose: () => void
    onInsert?: (text: string) => void
    workspaceId?: string
    onToolNavigate?: (toolName: string) => Promise<void>
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

const DISMISSED_KEY = 'cortex_dismissed_actions'
const MODEL_KEY = 'cortex_chat_model'

const AVAILABLE_MODELS: { id: string; label: string }[] = [
    { id: 'auto', label: 'Auto (round-robin)' },
    { id: 'models/gemma-4-31b-it', label: 'Gemma 4 31B' },
    { id: 'models/gemma-4-26b-a4b-it', label: 'Gemma 4 26B' },
]

function getDismissedActionIds(): string[] {
    try {
        const raw = localStorage.getItem(DISMISSED_KEY)
        return raw ? JSON.parse(raw) : []
    } catch { return [] }
}

function persistDismissedActionId(actionId: string): void {
    try {
        const ids = getDismissedActionIds()
        if (!ids.includes(actionId)) {
            ids.push(actionId)
            localStorage.setItem(DISMISSED_KEY, JSON.stringify(ids))
        }
    } catch (err) {
        console.error('Failed to persist dismissed action:', err)
    }
}

function clearDismissedActionIds(): void {
    try {
        localStorage.removeItem(DISMISSED_KEY)
    } catch (err) {
        console.error('Failed to clear dismissed actions:', err)
    }
}

function buildPendingChange(
    toolName: string,
    result: unknown,
    toolArgs?: Record<string, unknown>,
): PendingChange | null {
    const resultData = result as Record<string, unknown> | undefined
    const actionId = resultData?.action_id as string | undefined
    const entityId = resultData?.id as string | undefined
    if (!actionId) return null

    let title = ''
    let description = ''

    switch (toolName) {
        case 'create_note': {
            const content = (toolArgs?.content as string) || ''
            title = content.split('\n')[0]?.slice(0, 50) || 'Untitled'
            description = 'Created note'
            break
        }
        case 'update_note': {
            const content = (toolArgs?.content as string) || ''
            title = content.split('\n')[0]?.slice(0, 50) || 'Untitled'
            description = 'Updated note'
            break
        }
        case 'create_schedule': {
            title = (resultData?.title as string) || 'Untitled'
            description = 'Created schedule'
            break
        }
        case 'update_schedule': {
            title = (resultData?.title as string) || 'Untitled'
            description = 'Updated schedule'
            break
        }
        default:
            return null
    }

    return {
        id: `change-${Date.now()}-${Math.random()}`,
        toolName,
        actionId,
        entityId: entityId || '',
        title: title.slice(0, 60),
        description,
    }
}

export function AskAI({ noteContent, noteTitle, pendingSelection, onClose, onInsert, workspaceId, onToolNavigate }: AskAIProps) {
    const STORAGE_KEY = 'cortex_chatbot_state'

    const [messages, setMessages] = useState<Message[]>([])
    const [input, setInput] = useState('')
    const [isLoading, setIsLoading] = useState(false)
    const [copiedId, setCopiedId] = useState<string | null>(null)
    const [conversationId, setConversationId] = useState<string | null>(null)
    const [conversationTitle, setConversationTitle] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [sessions, setSessions] = useState<ConversationListItem[]>([])
    const [sessionsLoading, setSessionsLoading] = useState(true)
    const [sessionsLoadingMore, setSessionsLoadingMore] = useState(false)
    const [sessionsOffset, setSessionsOffset] = useState(0)
    const [isInitializing, setIsInitializing] = useState(true) // Track if we're loading from localStorage
    const [addedPills, setAddedPills] = useState<ContextPill[]>([
        ...(noteContent ? [{ id: 'note', text: noteContent, label: `📝 ${noteTitle || 'Note'}` }] : []),
    ])
    const [displayIndex, setDisplayIndex] = useState(0)
    const [fullReplyRef, setFullReplyRef] = useState('')
    const [pendingChanges, setPendingChanges] = useState<PendingChange[]>([])
    const [pendingChangesOpen, setPendingChangesOpen] = useState(true)
    const inputRef = useRef<HTMLTextAreaElement>(null)
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const abortRef = useRef<AbortController | null>(null)
    const [selectedModel, setSelectedModel] = useState<string>(
        () => localStorage.getItem(MODEL_KEY) || 'auto'
    )
    const [lastUsage, setLastUsage] = useState<TokenUsage | null>(null)
    const [lastModelUsed, setLastModelUsed] = useState<string | null>(null)
    const [modelDropdownOpen, setModelDropdownOpen] = useState(false)
    const modelDropdownRef = useRef<HTMLDivElement>(null)
    const { updateTokenUsage } = useConversationStore()
    const navigate = useNavigate()

    // Helper: Save conversationId synchronously to localStorage
    const saveConversationIdToStorage = useCallback((id: string) => {
        try {
            const state = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
            state.conversationId = id
            localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
            console.debug(`💾 Saved conversationId to localStorage: ${id}`)
        } catch (err) {
            console.error('Failed to save conversationId to localStorage:', err)
        }
    }, [STORAGE_KEY])

    // Helper: Clear conversationId from localStorage
    const clearConversationIdFromStorage = useCallback(() => {
        try {
            localStorage.removeItem(STORAGE_KEY)
            console.debug('🗑️ Cleared conversationId from localStorage')
        } catch (err) {
            console.error('Failed to clear conversationId from localStorage:', err)
        }
    }, [STORAGE_KEY])

    useEffect(() => {
        inputRef.current?.focus()
    }, [])

    // Typing effect animation
    useEffect(() => {
        if (displayIndex < fullReplyRef.length) {
            const timer = setTimeout(() => {
                setDisplayIndex(prev => prev + 1)
            }, 10) // 20ms delay between each character
            return () => clearTimeout(timer)
        }
    }, [displayIndex, fullReplyRef.length])

    // Load state from localStorage on mount and restore conversation from backend
    useEffect(() => {
        let canceled = false

        const restoreConversation = async (savedConversationId: string) => {
            try {
                console.debug(`📥 Restoring conversation: ${savedConversationId}`)
                const conversation = await getConversation(savedConversationId)
                if (canceled) return

                console.info(`✅ Restored ${conversation.messages.length} messages for conversation ${savedConversationId}`)
                setMessages(conversation.messages.map(msg => ({
                    id: msg.id,
                    role: msg.role as 'user' | 'assistant',
                    content: msg.content,
                })))
                setConversationTitle(conversation.title ?? null)

                // Restore pending changes from tool messages
                const dismissedIds = getDismissedActionIds()
                const restoredChanges: PendingChange[] = []
                for (const msg of conversation.messages) {
                    if (msg.role === 'tool' && msg.tool_name && msg.tool_output) {
                        const output = msg.tool_output ? JSON.parse(msg.tool_output) as Record<string, unknown> : null
                        const result = output?.result as Record<string, unknown> | undefined
                        const actionId = result?.action_id as string | undefined
                        if (actionId && !dismissedIds.includes(actionId)) {
                            const change = buildPendingChange(
                                msg.tool_name,
                                result,
                                msg.tool_input as Record<string, unknown> | undefined,
                            )
                            if (change) {
                                change.id = `restored-${actionId}`
                                restoredChanges.push(change)
                            }
                        }
                    }
                }
                if (restoredChanges.length > 0) {
                    setPendingChanges(restoredChanges)
                }
            } catch (err) {
                console.error('❌ Failed to restore conversation from backend:', err)
                // Clear localStorage if restoration fails to avoid infinite retry loop
                clearConversationIdFromStorage()
            }
        }

        const init = async () => {
            try {
                const savedState = localStorage.getItem(STORAGE_KEY)
                if (savedState) {
                    const state = JSON.parse(savedState)
                    if (state.conversationId) {
                        console.info(`🔄 Found saved conversationId in localStorage: ${state.conversationId}`)
                        setConversationId(state.conversationId)
                        if (state.conversationTitle) {
                            setConversationTitle(state.conversationTitle)
                        }
                        // Restore messages from backend (single source of truth)
                        await restoreConversation(state.conversationId)
                    } else {
                        console.debug('No conversationId in localStorage')
                    }
                } else {
                    console.debug('No saved state in localStorage')
                }
            } catch (err) {
                console.error('Failed to load chatbot state from localStorage:', err)
            } finally {
                if (!canceled) {
                    setIsInitializing(false)
                }
            }
        }

        void init()
        return () => {
            canceled = true
        }
    }, [clearConversationIdFromStorage])

    // Save conversation title to localStorage (conversationId saved synchronously in stream handler)
    useEffect(() => {
        if (isInitializing || !conversationId) {
            return
        }

        try {
            const state = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
            if (conversationTitle) {
                state.conversationTitle = conversationTitle
            }
            localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
            console.debug(`💾 Saved conversationTitle to localStorage: ${conversationTitle}`)
        } catch (err) {
            console.error('Failed to save conversationTitle to localStorage:', err)
        }
    }, [conversationTitle, isInitializing, conversationId])

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


    useEffect(() => {
        if (isInitializing || !conversationId || conversationTitle) return

        let canceled = false
        const fetchTitle = async () => {
            try {
                const conversation = await getConversation(conversationId)
                if (!canceled) {
                    setConversationTitle(conversation.title ?? null)
                }
            } catch (err) {
                console.error('Failed to load conversation title:', err)
            }
        }

        fetchTitle()
        return () => {
            canceled = true
        }
    }, [conversationId, conversationTitle, isInitializing])

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
        } catch {
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
            console.debug(`📥 Loading session: ${sessionId}`)
            const conversation = await getConversation(sessionId)

            // Convert conversation messages to Message format
            const loadedMessages: Message[] = conversation.messages.map(msg => ({
                id: msg.id,
                role: msg.role as 'user' | 'assistant',
                content: msg.content,
            }))

            setMessages(loadedMessages)
            setConversationId(sessionId)
            // Save conversationId synchronously to localStorage
            saveConversationIdToStorage(sessionId)
            setConversationTitle(conversation.title ?? null)
            setSessions([]) // Clear sessions list after selection

            // Restore pending changes from tool messages
            const dismissedIds = getDismissedActionIds()
            const loadedChanges: PendingChange[] = []
            for (const msg of conversation.messages) {
                if (msg.role === 'tool' && msg.tool_name && msg.tool_output) {
                    const output = msg.tool_output ? JSON.parse(msg.tool_output) as Record<string, unknown> : null
                    const result = output?.result as Record<string, unknown> | undefined
                    const actionId = result?.action_id as string | undefined
                    if (actionId && !dismissedIds.includes(actionId)) {
                        const change = buildPendingChange(
                            msg.tool_name,
                            result,
                            msg.tool_input as Record<string, unknown> | undefined,
                        )
                        if (change) {
                            change.id = `restored-${actionId}`
                            loadedChanges.push(change)
                        }
                    }
                }
            }
            setPendingChanges(loadedChanges)
            console.info(`✅ Loaded session ${sessionId} with ${loadedMessages.length} messages`)
        } catch (err) {
            setError(`Failed to load session: ${err instanceof Error ? err.message : 'Unknown error'}`)
            console.error('Failed to load session:', err)
        } finally {
            setIsLoading(false)
        }
    }, [saveConversationIdToStorage])

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

    const handleNewSession = useCallback(() => {
        abortRef.current?.abort()
        abortRef.current = null
        setMessages([])
        setConversationId(null)
        setConversationTitle(null)
        setError(null)
        setIsLoading(false)
        setCopiedId(null)
        setPendingChanges([])
        setLastUsage(null)
        setLastModelUsed(null)
        clearDismissedActionIds()
        clearConversationIdFromStorage()
    }, [clearConversationIdFromStorage])

    const stopGeneration = useCallback(() => {
        abortRef.current?.abort()
        abortRef.current = null
        setIsLoading(false)
    }, [])

    const handleModelChange = useCallback((model: string) => {
        setSelectedModel(model)
        try {
            localStorage.setItem(MODEL_KEY, model)
        } catch {
            // ignore persistence errors
        }
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

    const sendMessage = useCallback(async (text: string) => {
        if (!text.trim() || isLoading) return
        const userMsg = text.trim()
        setInput('')
        setError(null)
            setDisplayIndex(0)
            setFullReplyRef('')
            setLastUsage(null)

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
            // Build structured context dict (pills + runtime) instead of concatenating into message
            const runtimeText = buildRuntimeContextText()
            const pillsArray = addedPills.map(p => ({ id: p.id, text: p.text, label: p.label }))
            const context: Record<string, unknown> = {}
            if (pillsArray.length > 0) context.pills = pillsArray
            if (runtimeText) context.runtime = runtimeText

            // Call streaming agent API
            let fullReply = ''
            let finalConversationId: string | null = null
            let thinkingSteps: Message['thinkingSteps'] = []
            let currentToolArgs: Record<string, unknown> | undefined

            const controller = new AbortController()
            abortRef.current = controller

            const handleToolNavigation = (event: StreamEvent) => {
                if (!event.tool_name) return
                if (event.error) return

                const isSuccess = event.success !== false
                if (!isSuccess) return

                const result = event.result as Record<string, unknown> | undefined

                if (event.tool_name === 'create_note') {
                    const noteId = result?.id as string | undefined
                    const wsId = (result?.workspace_id as string | undefined) || workspaceId
                    if (noteId && wsId) {
                        console.debug('Tool navigation: create_note', { noteId, wsId })
                        onToolNavigate?.('create_note').catch(() => { })
                        navigate(noteRoute(wsId, noteId))
                    }
                    return
                }

                if (event.tool_name === 'create_schedule' || event.tool_name === 'update_schedule' || event.tool_name === 'get_schedules') {
                    console.debug('Tool navigation: schedule', { tool: event.tool_name })
                    onToolNavigate?.('schedule').catch(() => { })
                    navigate(scheduleRoute())
                    return
                }

                if (event.tool_name === 'summarize_asset') {
                    const assetId = result?.id as string | undefined
                    const wsId = (result?.workspace_id as string | undefined) || workspaceId
                    if (assetId && wsId) {
                        console.debug('Tool navigation: summarize_asset', { assetId, wsId })
                        onToolNavigate?.('knowledge').catch(() => { })
                        navigate(knowledgeRoute(wsId, assetId))
                    }
                }
            }

            for await (const event of streamAgentMessage(
                userMsg,
                conversationId || undefined,
                workspaceId,
                context,
                {
                    model: selectedModel === 'auto' ? undefined : selectedModel,
                    signal: controller.signal,
                },
            )) {
                if (event.type === 'text' && event.text) {
                    fullReply += event.text
                    setFullReplyRef(fullReply)
                    setMessages(prev =>
                        prev.map(m => m.id === loadingMsgObj.id
                            ? { ...m, content: fullReply, loading: false, thinkingSteps }
                            : m
                        )
                    )
                } else if (event.type === 'tool_start' && event.tool_name) {
                    currentToolArgs = event.tool_args
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
                    handleToolNavigation(event)

                    // Track pending change for mutating tools
                    if (currentToolArgs) {
                        const resultData = event.result as Record<string, unknown> | undefined
                        const actionId = resultData?.action_id as string | undefined
                        if (actionId) {
                            const change = buildPendingChange(event.tool_name, event.result, currentToolArgs)
                            if (change) {
                                setPendingChanges(prev => [...prev, change])
                            }
                        }
                    }
                    currentToolArgs = undefined
                } else if (event.type === 'title_generated' && event.title) {
                    setConversationTitle(event.title)
                } else if (event.type === 'done' && event.conversation_id) {
                    finalConversationId = event.conversation_id
                    if (event.usage) {
                        setLastUsage(event.usage)
                        if (typeof event.usage.total_tokens === 'number') {
                            updateTokenUsage(event.usage.total_tokens)
                        }
                    }
                    if (event.model_used) {
                        setLastModelUsed(event.model_used)
                    }
                    // Save conversationId to localStorage immediately (synchronously)
                    // This prevents data loss if user reloads right after sending a message
                    saveConversationIdToStorage(event.conversation_id)
                    console.info(`✅ Received conversationId from stream and saved to localStorage: ${event.conversation_id}`)
                }
            }

            // Update conversation ID if this is the first message
            if (!conversationId && finalConversationId) {
                console.debug(`Setting conversationId state: ${finalConversationId}`)
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
            abortRef.current = null
            setIsLoading(false)
        }
    }, [isLoading, conversationId, updateTokenUsage, addedPills, buildRuntimeContextText, navigate, workspaceId, onToolNavigate, saveConversationIdToStorage, selectedModel])

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

    const acceptChange = useCallback((changeId: string, actionId: string) => {
        persistDismissedActionId(actionId)
        setPendingChanges(prev => prev.filter(c => c.id !== changeId))
    }, [])

    const undoChange = useCallback(async (change: PendingChange) => {
        try {
            await revertAction(change.actionId)
            persistDismissedActionId(change.actionId)
            setPendingChanges(prev => prev.filter(c => c.id !== change.id))
        } catch (err) {
            if (err instanceof ApiError && err.status === 400) {
                persistDismissedActionId(change.actionId)
                setPendingChanges(prev => prev.filter(c => c.id !== change.id))
            } else {
                console.error('Failed to revert action:', err)
            }
        }
    }, [])

    const acceptAllChanges = useCallback(() => {
        for (const change of pendingChanges) {
            persistDismissedActionId(change.actionId)
        }
        setPendingChanges([])
    }, [pendingChanges])

    const undoAllChanges = useCallback(async () => {
        const changes = [...pendingChanges]
        for (const change of changes) {
            try {
                await revertAction(change.actionId)
                persistDismissedActionId(change.actionId)
            } catch (err) {
                if (err instanceof ApiError && err.status === 400) {
                    persistDismissedActionId(change.actionId)
                } else {
                    console.error(`Failed to revert ${change.actionId}:`, err)
                }
            }
        }
        setPendingChanges([])
    }, [pendingChanges])

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
                        <div className="ask-ai-title-container">
                            <span className="ask-ai-title">Ask AI</span>
                            <span className="ask-ai-subtitle">
                                {conversationTitle ? conversationTitle : 'Chat with your AI assistant'}
                            </span>
                        </div>
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
                        <button
                            type="button"
                            className="ask-ai-icon-btn"
                            title="New session"
                            onClick={handleNewSession}
                        >
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
                        messages.map((msg, index) => (
                            <div key={msg.id} className={`ask-ai-msg ask-ai-msg--${msg.role}`}>
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
                                                    dangerouslySetInnerHTML={{
                                                        __html: renderMarkdown(
                                                            index === messages.length - 1 && fullReplyRef
                                                                ? fullReplyRef.slice(0, displayIndex)
                                                                : msg.content
                                                        )
                                                    }}
                                                />
                                            ) : (
                                                <div className="ask-ai-msg-content">
                                                    {index === messages.length - 1 && fullReplyRef
                                                        ? fullReplyRef.slice(0, displayIndex)
                                                        : msg.content
                                                    }
                                                </div>
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
                    {/* Context pills (between textarea and bottom bar) */}
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
                                        onClick={() => setAddedPills(prev => prev.filter(p => p.id !== pill.id))}
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
                                onClick={() => setPendingChangesOpen(!pendingChangesOpen)}
                            >
                                <span>Pending Changes ({pendingChanges.length})</span>
                                <span className={`ask-ai-changes-toggle-icon ${pendingChangesOpen ? 'open' : ''}`}>▾</span>
                            </button>
                            {pendingChangesOpen && (
                                <div className="ask-ai-changes-list">
                                    <div className="ask-ai-changes-bulk-actions">
                                        <button type="button" className="ask-ai-changes-bulk-btn accept-all" onClick={acceptAllChanges}>
                                            Accept All
                                        </button>
                                        <button type="button" className="ask-ai-changes-bulk-btn undo-all" onClick={() => void undoAllChanges()}>
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
                                                    onClick={() => acceptChange(change.id, change.actionId)}
                                                >
                                                    Accept
                                                </button>
                                                <button
                                                    type="button"
                                                    className="ask-ai-changes-item-btn undo"
                                                    onClick={() => void undoChange(change)}
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
                    {/* Textarea area */}
                    <div className="ask-ai-input-wrapper">
                        <textarea
                            ref={inputRef}
                            className="ask-ai-input"
                            placeholder="Ask anything…"
                            value={input}
                            onChange={e => setInput(e.target.value)}
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
                    {/* Bottom bar */}
                    <div className="ask-ai-bottom-bar">
                        <div className="ask-ai-bottom-left">
                            <button
                                type="button"
                                className="ask-ai-bottom-icon-btn"
                                title="Add context"
                                onClick={() => {
                                    if (noteContent && !addedPills.some(p => p.text === noteContent)) {
                                        setAddedPills(prev => [...prev, {
                                            id: Date.now().toString(),
                                            text: noteContent,
                                            label: `\u{1F4DD} ${noteTitle || 'Note'}`,
                                        }])
                                    }
                                }}
                            >
                                <Plus size={15} />
                            </button>
                            {pendingSelection && !addedPills.some(p => p.text === pendingSelection) && (
                                <button
                                    type="button"
                                    className="ask-ai-bottom-icon-btn"
                                    title="Add selected text"
                                    onClick={addPendingSelection}
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
                                        {AVAILABLE_MODELS.find(m => m.id === selectedModel)?.label || 'Auto'}
                                    </span>
                                    <ChevronDown size={11} className={`ask-ai-model-chevron ${modelDropdownOpen ? 'open' : ''}`} />
                                </button>
                                {modelDropdownOpen && (
                                    <div className="ask-ai-model-dropdown">
                                        {AVAILABLE_MODELS.map((m) => (
                                            <button
                                                key={m.id}
                                                type="button"
                                                className={`ask-ai-model-option ${m.id === selectedModel ? 'active' : ''}`}
                                                onClick={() => {
                                                    handleModelChange(m.id)
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
                                    onClick={stopGeneration}
                                    title="Stop generating"
                                >
                                    <Square size={13} />
                                </button>
                            ) : (
                                <button
                                    type="button"
                                    className={`ask-ai-send-btn ${input.trim() ? 'active' : ''}`}
                                    onClick={() => void sendMessage(input)}
                                    disabled={!input.trim()}
                                    title="Send"
                                >
                                    <ArrowUp size={16} />
                                </button>
                            )}
                        </div>
                    </div>
                </div>
                {lastUsage && (
                    <div className="ask-ai-usage">
                        <span className="ask-ai-usage-model">
                            {lastModelUsed ? (AVAILABLE_MODELS.find(m => m.id === lastModelUsed)?.label || lastModelUsed) : 'Auto'}
                        </span>
                        <span className="ask-ai-usage-stat">↑ {lastUsage.prompt_tokens}</span>
                        <span className="ask-ai-usage-stat">↓ {lastUsage.completion_tokens}</span>
                        <span className="ask-ai-usage-stat ask-ai-usage-total">∑ {lastUsage.total_tokens}</span>
                    </div>
                )}
            </div>
        </div>
    )
}