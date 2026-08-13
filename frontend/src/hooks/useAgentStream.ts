import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { streamAgentMessage, listConversations, getConversation, deleteConversation, revertAction, getAvailableModels, ApiError, type ConversationListItem, type StreamEvent, type PendingChange, type TokenUsage, type AskChoiceQuestion, type AvailableModel } from '../services/api'
import { useConversationStore } from '../stores/conversationStore'
import { knowledgeRoute, noteRoute, scheduleRoute } from '../services/routes'

// Stable ids for the step currently being streamed into, so it can be replaced
// on every delta and swapped out when the segment is finalized.
const LIVE_TEXT_ID = 'text-live'
const LIVE_THINKING_ID = 'thinking-live'

const DISMISSED_KEY = 'cortex_dismissed_actions'
const MODEL_KEY = 'cortex_chat_model'
const STORAGE_KEY = 'cortex_chatbot_state'

type ContextPill = {
    id: string
    text: string
    label: string
}

type PageContext =
    | { type: 'home'; route: 'home' }
    | { type: 'schedule'; route: 'schedule' }
    | { type: 'note'; route: 'note_detail'; note_id: string; note_title?: string }
    | { type: 'records'; route: 'records' }
    | { type: 'workflow'; route: 'workflow' | 'workflow_detail'; workflow_id?: string }

export type AgentMessage = {
    id: string
    role: 'user' | 'assistant'
    content: string
    loading?: boolean
    thinkingOpen?: boolean
    thinkingSteps?: Array<{
        id: string
        type: 'thinking' | 'text' | 'tool_start' | 'tool_result' | 'ask_choice'
        toolName?: string
        toolArgs?: Record<string, unknown>
        result?: unknown
        text?: string
        success?: boolean
        questions?: AskChoiceQuestion[]
        answers?: Record<string, string>
    }>
}

export type PendingChangeItem = PendingChange

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

const AUTO_MODEL_OPTION: AvailableModel = { id: 'auto', label: 'Auto (round-robin)' }

export function toolSemanticDescription(toolName: string, toolArgs?: Record<string, unknown>): string {
    if (!toolArgs) return ''
    const content = (toolArgs.content as string) || ''
    const title = (toolArgs.title as string) || ''
    const query = (toolArgs.query as string) || ''
    const noteId = (toolArgs.note_id as string) || ''

    switch (toolName) {
        case 'update_note': {
            const preview = previewContent(content)
            return preview ? `note "${preview}"` : (noteId ? 'note' : 'note')
        }
        case 'create_note': {
            const preview = previewContent(content)
            const t = title || preview
            return t ? `note mới "${t}"` : 'note mới'
        }
        case 'delete_note':
            return 'xóa note'
        case 'get_note': {
            const id = (toolArgs.note_id as string) ?? ''
            return id ? `xem note ${id.slice(0, 8)}…` : 'xem note'
        }
        case 'list_notes':
            return title ? `ds notes • ${title}` : 'ds notes'
        case 'search_notes': {
            return query ? `tìm "${query}"` : 'tìm notes'
        }
        case 'create_schedule': {
            return title ? `lịch "${title}"` : 'lịch mới'
        }
        case 'update_schedule':
            return title ? `cập nhật lịch "${title}"` : 'cập nhật lịch'
        case 'delete_schedule':
            return 'xóa lịch'
        case 'list_schedules':
            return 'ds lịch'
        case 'revert_action':
            return '(undo)'
        case 'web_search':
            return query ? `web search "${query}"` : 'web search'
        default:
            return ''
    }
}

function previewContent(content: string, maxLen = 60): string {
    if (!content || typeof content !== 'string') return ''
    const firstLine = content.split('\n').find(l => l.trim().replace(/^#+\s+/, '')) ?? content
    return firstLine.replace(/^#+\s+/, '').slice(0, maxLen).trim()
}

export function toolResultSummary(toolName: string, result: unknown, success: boolean): string {
    const r = result as Record<string, unknown> | undefined
    if (!success) {
        const err = (r?.error as string) ?? 'thất bại'
        return `✗ ${err.slice(0, 60)}`
    }
    switch (toolName) {
        case 'update_note':
        case 'create_note': {
            const v = r?.version as number | undefined
            const id = (r?.id as string)?.slice(0, 8)
            return v ? `v${v}${id ? ` • ${id}` : ''}` : 'xong'
        }
        case 'delete_note':
            return 'đã xóa'
        case 'search_notes':
        case 'list_notes': {
            const count = Array.isArray(r?.notes) ? (r.notes as unknown[]).length
                : Array.isArray(r?.results) ? (r.results as unknown[]).length
                : Array.isArray(result) ? (result as unknown[]).length
                : 0
            return `${count} kết quả`
        }
        case 'get_note':
            return r?.title ? `"${(r.title as string).slice(0, 30)}"` : 'ok'
        case 'create_schedule':
        case 'update_schedule': {
            const id = (r?.id as string)?.slice(0, 8)
            return id ? `id ${id}` : 'ok'
        }
        default:
            return 'xong'
    }
}

interface UseAgentStreamOptions {
    workspaceId?: string
    noteContent?: string
    noteTitle?: string
    pendingSelection?: string
    onToolNavigate?: (toolName: string) => Promise<void>
    onNoteDiff?: (noteId: string, proposalId: string) => void
    onPlanProposal?: (proposalId: string) => void
}

export function useAgentStream(options: UseAgentStreamOptions) {
    const { workspaceId, noteTitle, onToolNavigate, onNoteDiff, onPlanProposal } = options
    const navigate = useNavigate()
    const { updateTokenUsage } = useConversationStore()

    const [messages, setMessages] = useState<AgentMessage[]>([])
    const [isLoading, setIsLoading] = useState(false)
    const [conversationId, setConversationId] = useState<string | null>(null)
    const [conversationTitle, setConversationTitle] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [sessions, setSessions] = useState<ConversationListItem[]>([])
    const [sessionsLoading, setSessionsLoading] = useState(true)
    const [sessionsLoadingMore, setSessionsLoadingMore] = useState(false)
    const [sessionsOffset, setSessionsOffset] = useState(0)
    const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null)
    const [isInitializing, setIsInitializing] = useState(true)
    const [pendingChanges, setPendingChanges] = useState<PendingChange[]>([])
    const [selectedModel, setSelectedModel] = useState<string>(
        () => localStorage.getItem(MODEL_KEY) || 'auto'
    )
    const [availableModels, setAvailableModels] = useState<AvailableModel[]>([AUTO_MODEL_OPTION])
    const [lastUsage, setLastUsage] = useState<TokenUsage | null>(null)
    const [lastModelUsed, setLastModelUsed] = useState<string | null>(null)
    const abortRef = useRef<AbortController | null>(null)
    const messagesEndRef = useRef<HTMLDivElement>(null)

    const saveConversationIdToStorage = useCallback((id: string) => {
        try {
            const state = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
            state.conversationId = id
            localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
            console.debug(`💾 Saved conversationId to localStorage: ${id}`)
        } catch (err) {
            console.error('Failed to save conversationId to localStorage:', err)
        }
    }, [])

    const clearConversationIdFromStorage = useCallback(() => {
        try {
            localStorage.removeItem(STORAGE_KEY)
            console.debug('🗑️ Cleared conversationId from localStorage')
        } catch (err) {
            console.error('Failed to clear conversationId from localStorage:', err)
        }
    }, [])

    useEffect(() => {
        let canceled = false
        getAvailableModels()
            .then(models => {
                if (!canceled) setAvailableModels([AUTO_MODEL_OPTION, ...models])
            })
            .catch(err => console.error('Failed to load available models:', err))
        return () => { canceled = true }
    }, [])

    useEffect(() => {
        let canceled = false

        const restoreConversation = async (savedConversationId: string) => {
            try {
                console.debug(`📥 Restoring conversation: ${savedConversationId}`)
                const conversation = await getConversation(savedConversationId)
                if (canceled) return

                console.info(`✅ Restored ${conversation.messages.length} messages for conversation ${savedConversationId}`)
                const visibleMessages = conversation.messages.filter(m => m.role !== 'tool')
                setMessages(visibleMessages.map(msg => {
                    const text = msg.content ?? ''
                    return {
                        id: msg.id,
                        role: msg.role as 'user' | 'assistant',
                        content: text,
                        thinkingSteps: msg.role === 'assistant' && text
                            ? [{ id: `restored-${msg.id}`, type: 'text' as const, text }]
                            : undefined,
                    }
                }))
                setConversationTitle(conversation.title ?? null)

                const dismissedIds = getDismissedActionIds()
                const restoredChanges: PendingChange[] = []
                for (const msg of conversation.messages) {
                    if (msg.role === 'tool' && msg.tool_name) {
                        try {
                            const output = msg.tool_output
                                ? (typeof msg.tool_output === 'string'
                                    ? JSON.parse(msg.tool_output)
                                    : msg.tool_output) as Record<string, unknown>
                                : null
                            const result = (output as { result?: Record<string, unknown> })?.result
                            const actionId = result?.action_id as string | undefined
                            if (actionId && !dismissedIds.includes(actionId)) {
                                const toolInput = msg.tool_input
                                    ? (typeof msg.tool_input === 'string'
                                        ? JSON.parse(msg.tool_input)
                                        : msg.tool_input) as Record<string, unknown>
                                    : undefined
                                const change = buildPendingChange(msg.tool_name, result, toolInput)
                                if (change) {
                                    change.id = `restored-${actionId}`
                                    restoredChanges.push(change)
                                }
                            }
                        } catch (parseErr) {
                            console.warn('Failed to parse tool message:', msg.id, parseErr)
                        }
                    }
                }
                if (restoredChanges.length > 0) {
                    setPendingChanges(restoredChanges)
                }
            } catch (err) {
                console.error('❌ Failed to restore conversation from backend:', err)
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
        return () => { canceled = true }
    }, [clearConversationIdFromStorage])

    useEffect(() => {
        if (isInitializing || !conversationId) return
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

    useEffect(() => {
        const fetchSessions = async () => {
            try {
                setSessionsLoading(true)
                const response = await listConversations(5, 0)
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
        return () => { canceled = true }
    }, [conversationId, conversationTitle, isInitializing])

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [messages])

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

    const buildPageContext = useCallback((): PageContext | undefined => {
        if (typeof window === 'undefined') return undefined
        const path = window.location.pathname

        if (path === '/') return { type: 'home', route: 'home' }
        if (path === '/schedule' || /^\/w\/[^/]+\/schedule$/.test(path)) {
            return { type: 'schedule', route: 'schedule' }
        }

        const wsMatch = path.match(/^\/w\/([^/]+)/)
        if (!wsMatch) return undefined
        const wsId = wsMatch[1]

        const noteMatch = path.match(/^\/w\/[^/]+\/notes\/([^/]+)$/)
        if (noteMatch) {
            const page: PageContext = {
                type: 'note',
                route: 'note_detail',
                note_id: noteMatch[1],
            }
            if (noteTitle) page.note_title = noteTitle
            return page
        }

        if (path === `/w/${wsId}` || path === `/w/${wsId}/notes`) {
            return { type: 'home', route: 'home' }
        }

        if (path === `/w/${wsId}/records`) {
            return { type: 'records', route: 'records' }
        }

        const wfMatch = path.match(/^\/w\/[^/]+\/workflows(?:\/([^/]+))?$/)
        if (wfMatch) {
            return wfMatch[1]
                ? { type: 'workflow', route: 'workflow_detail', workflow_id: wfMatch[1] }
                : { type: 'workflow', route: 'workflow' }
        }

        return undefined
    }, [noteTitle])

    const loadSession = useCallback(async (sessionId: string) => {
        try {
            setIsLoading(true)
            console.debug(`📥 Loading session: ${sessionId}`)
            const conversation = await getConversation(sessionId)

            const visibleMessages = conversation.messages.filter(m => m.role !== 'tool')
            const loadedMessages: AgentMessage[] = visibleMessages.map(msg => {
                const text = msg.content ?? ''
                return {
                    id: msg.id,
                    role: msg.role as 'user' | 'assistant',
                    content: text,
                    thinkingSteps: msg.role === 'assistant' && text
                        ? [{ id: `loaded-${msg.id}`, type: 'text' as const, text }]
                        : undefined,
                }
            })

            setMessages(loadedMessages)
            setConversationId(sessionId)
            saveConversationIdToStorage(sessionId)
            setConversationTitle(conversation.title ?? null)
            setSessions([])

            const dismissedIds = getDismissedActionIds()
            const loadedChanges: PendingChange[] = []
            for (const msg of conversation.messages) {
                if (msg.role === 'tool' && msg.tool_name) {
                    try {
                        const output = msg.tool_output
                            ? (typeof msg.tool_output === 'string'
                                ? JSON.parse(msg.tool_output)
                                : msg.tool_output) as Record<string, unknown>
                            : null
                        const result = (output as { result?: Record<string, unknown> })?.result
                        const actionId = result?.action_id as string | undefined
                        if (actionId && !dismissedIds.includes(actionId)) {
                            const toolInput = msg.tool_input
                                ? (typeof msg.tool_input === 'string'
                                    ? JSON.parse(msg.tool_input)
                                    : msg.tool_input) as Record<string, unknown>
                                : undefined
                            const change = buildPendingChange(msg.tool_name, result, toolInput)
                            if (change) {
                                change.id = `restored-${actionId}`
                                loadedChanges.push(change)
                            }
                        }
                    } catch (parseErr) {
                        console.warn('Failed to parse tool message:', msg.id, parseErr)
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
        setPendingChanges([])
        setLastUsage(null)
        setLastModelUsed(null)
        clearDismissedActionIds()
        clearConversationIdFromStorage()
    }, [clearConversationIdFromStorage])

    const deleteSession = useCallback(async (sessionId: string) => {
        setDeletingSessionId(sessionId)
        try {
            await deleteConversation(sessionId)
            setSessions(prev => prev.filter(s => s.id !== sessionId))
            if (conversationId === sessionId) {
                handleNewSession()
            }
        } catch (err) {
            setError(`Failed to delete session: ${err instanceof Error ? err.message : 'Unknown error'}`)
            console.error('Failed to delete session:', err)
        } finally {
            setDeletingSessionId(null)
        }
    }, [conversationId, handleNewSession])

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

    const sendMessage = useCallback(async (
        text: string,
        addedPills: ContextPill[],
    ) => {
        if (!text.trim() || isLoading) return
        const userMsg = text.trim()

        setError(null)
        setLastUsage(null)

        const userMsgObj: AgentMessage = {
            id: Date.now().toString(),
            role: 'user',
            content: userMsg,
        }
        const loadingMsgObj: AgentMessage = {
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
            const runtimeText = buildRuntimeContextText()
            const page = buildPageContext()
            const pillsArray = addedPills.map(p => ({ id: p.id, text: p.text, label: p.label }))
            const context: Record<string, unknown> = {}
            if (pillsArray.length > 0) context.pills = pillsArray
            if (page) context.page = page
            if (runtimeText) context.runtime = runtimeText

            let finalConversationId: string | null = null
            let thinkingSteps: NonNullable<AgentMessage['thinkingSteps']> = []
            let currentToolArgs: Record<string, unknown> | undefined
            let currentThinkingText = ''
            let currentTextText = ''

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

            // Flushing replaces the live placeholder instead of appending next to
            // it — otherwise the same text ends up in the list twice.
            const flushPendingText = () => {
                if (!currentTextText) return
                const textStep = {
                    id: `text-${Date.now()}-${Math.random()}`,
                    type: 'text' as const,
                    text: currentTextText,
                }
                thinkingSteps = [...thinkingSteps.filter(s => s.id !== LIVE_TEXT_ID), textStep]
                currentTextText = ''
            }

            const flushPendingThinking = () => {
                if (!currentThinkingText) return
                const thinkingStep = {
                    id: `thinking-${Date.now()}-${Math.random()}`,
                    type: 'thinking' as const,
                    text: currentThinkingText,
                }
                thinkingSteps = [...thinkingSteps.filter(s => s.id !== LIVE_THINKING_ID), thinkingStep]
                currentThinkingText = ''
            }

            const pushStepNow = () => {
                setMessages(prev =>
                    prev.map(m => m.id === loadingMsgObj.id
                        ? { ...m, thinkingSteps }
                        : m
                    )
                )
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
                    currentTextText += event.text
                    // Only the live placeholder is replaced; segments already
                    // flushed before a tool call must stay in the list.
                    const stepsWithoutTrailingText = thinkingSteps.filter(s => s.id !== LIVE_TEXT_ID)
                    const newTextStep = {
                        id: LIVE_TEXT_ID,
                        type: 'text' as const,
                        text: currentTextText,
                    }
                    thinkingSteps = [...stepsWithoutTrailingText, newTextStep]
                    setMessages(prev =>
                        prev.map(m => m.id === loadingMsgObj.id
                            ? { ...m, thinkingSteps }
                            : m
                        )
                    )
                } else if (event.type === 'thinking' && event.text) {
                    currentThinkingText += event.text
                    const stepsWithoutTrailingThinking = thinkingSteps.filter(s => s.id !== LIVE_THINKING_ID)
                    const newThinkingStep = {
                        id: LIVE_THINKING_ID,
                        type: 'thinking' as const,
                        text: currentThinkingText,
                    }
                    thinkingSteps = [...stepsWithoutTrailingThinking, newThinkingStep]
                    setMessages(prev =>
                        prev.map(m => m.id === loadingMsgObj.id
                            ? { ...m, thinkingSteps }
                            : m
                        )
                    )
                } else if (event.type === 'tool_start' && event.tool_name) {
                    flushPendingThinking()
                    flushPendingText()
                    currentToolArgs = event.tool_args
                    const step = {
                        id: `tool-${Date.now()}-${Math.random()}`,
                        type: 'tool_start' as const,
                        toolName: event.tool_name,
                        toolArgs: event.tool_args,
                    }
                    thinkingSteps = [...thinkingSteps, step]
                    pushStepNow()
                } else if (event.type === 'tool_result' && event.tool_name) {
                    flushPendingThinking()
                    flushPendingText()
                    const step = {
                        id: `result-${Date.now()}-${Math.random()}`,
                        type: 'tool_result' as const,
                        toolName: event.tool_name,
                        result: event.result,
                        success: event.success,
                    }
                    thinkingSteps = [...thinkingSteps, step]
                    pushStepNow()

                    handleToolNavigation(event)

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
                } else if (event.type === 'note_diff' && event.note_id && event.proposal_id) {
                    console.log('[AskAI] note_diff event received', { note_id: event.note_id, proposal_id: event.proposal_id, has_onNoteDiff: !!onNoteDiff })
                    if (onNoteDiff) {
                        console.log('[AskAI] calling onNoteDiff', event.note_id, event.proposal_id)
                        onNoteDiff(event.note_id, event.proposal_id)
                    }
                } else if (event.type === 'plan_proposal' && event.proposal_id) {
                    onPlanProposal?.(event.proposal_id)
                } else if (event.type === 'ask_choice' && event.questions) {
                    flushPendingThinking()
                    flushPendingText()
                    const step = {
                        id: `ask-${Date.now()}-${Math.random()}`,
                        type: 'ask_choice' as const,
                        questions: event.questions,
                    }
                    thinkingSteps = [...thinkingSteps, step]
                    pushStepNow()
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
                    saveConversationIdToStorage(event.conversation_id)
                    console.info(`✅ Received conversationId from stream and saved to localStorage: ${event.conversation_id}`)
                }
            }

            flushPendingThinking()
            flushPendingText()

            if (!conversationId && finalConversationId) {
                console.debug(`Setting conversationId state: ${finalConversationId}`)
                setConversationId(finalConversationId)
            }

            updateTokenUsage(0)

            setMessages(prev =>
                prev.map(m => m.id === loadingMsgObj.id
                    ? { ...m, loading: false, thinkingSteps }
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
    }, [isLoading, conversationId, updateTokenUsage, buildRuntimeContextText, buildPageContext, navigate, workspaceId, onToolNavigate, saveConversationIdToStorage, selectedModel, onNoteDiff, onPlanProposal])

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

    const answerChoice = useCallback((
        messageId: string,
        stepId: string,
        answers: Record<string, string>,
        summaryText: string,
    ) => {
        setMessages(prev => prev.map(m => m.id === messageId
            ? {
                ...m,
                thinkingSteps: (m.thinkingSteps ?? []).map(s => s.id === stepId ? { ...s, answers } : s),
            }
            : m
        ))
        void sendMessage(summaryText, [])
    }, [sendMessage])

    return {
        messages,
        isLoading,
        error,
        conversationId,
        conversationTitle,
        sessions,
        sessionsLoading,
        sessionsLoadingMore,
        sessionsOffset,
        deletingSessionId,
        isInitializing,
        pendingChanges,
        selectedModel,
        availableModels,
        lastUsage,
        lastModelUsed,
        abortRef,
        messagesEndRef,
        setError,
        setMessages,
        setConversationTitle,
        setSessions,
        setPendingChanges,
        sendMessage,
        stopGeneration,
        handleNewSession,
        loadSession,
        loadMoreSessions,
        deleteSession,
        handleModelChange,
        acceptChange,
        undoChange,
        acceptAllChanges,
        undoAllChanges,
        answerChoice,
        clearConversationIdFromStorage,
    }
}
