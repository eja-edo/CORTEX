import type { TokenPair, NotificationListResponse, NotificationResponse } from '../types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'
const TOKEN_STORAGE_KEY = 'cortex_tokens'

export class ApiError extends Error {
    status: number

    constructor(message: string, status: number) {
        super(message)
        this.status = status
    }
}

// Module-level token storage (avoids stale closures)
let currentTokens: TokenPair | null = null

export function readStoredTokens(): TokenPair | null {
    const raw = window.localStorage.getItem(TOKEN_STORAGE_KEY)
    if (!raw) return null
    try {
        const parsed = JSON.parse(raw) as TokenPair
        if (parsed.accessToken && parsed.refreshToken) return parsed
        return null
    } catch { return null }
}

export function writeStoredTokens(tokens: TokenPair | null): void {
    if (!tokens) {
        window.localStorage.removeItem(TOKEN_STORAGE_KEY)
        currentTokens = null
        return
    }
    window.localStorage.setItem(TOKEN_STORAGE_KEY, JSON.stringify(tokens))
    currentTokens = tokens
}

export function getCurrentTokens(): TokenPair | null {
    return currentTokens
}

export function setCurrentTokens(tokens: TokenPair | null): void {
    currentTokens = tokens
    if (tokens) writeStoredTokens(tokens)
    else writeStoredTokens(null)
}

// Initialize from localStorage on module load
currentTokens = readStoredTokens()

export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
    const response = await fetch(url, init)
    const text = await response.text()
    const body = text ? JSON.parse(text) : null
    if (!response.ok) throw new ApiError(body?.detail ?? `Request failed (${response.status})`, response.status)
    return body as T
}

async function refreshToken(currentRefreshToken: string): Promise<TokenPair> {
    const payload = await requestJson<{ access_token: string; refresh_token: string; token_type: string }>(
        `${API_BASE_URL}/auth/refresh`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: currentRefreshToken }) },
    )
    return { accessToken: payload.access_token, refreshToken: payload.refresh_token }
}

export async function requestWithAuth<T>(path: string, init?: RequestInit): Promise<T> {
    if (!currentTokens) throw new Error('Please login first')

    const headers = new Headers(init?.headers ?? {})
    headers.set('Authorization', `Bearer ${currentTokens.accessToken}`)
    let response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
    if (response.status === 401) {
        const newTokens = await refreshToken(currentTokens.refreshToken)
        setCurrentTokens(newTokens)
        const retryHeaders = new Headers(init?.headers ?? {})
        retryHeaders.set('Authorization', `Bearer ${newTokens.accessToken}`)
        response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers: retryHeaders })
    }
    const text = await response.text()
    const body = text ? JSON.parse(text) : null
    if (!response.ok) throw new ApiError(body?.detail ?? `Request failed (${response.status})`, response.status)
    return body as T
}

// ============================================================================
// Agent Conversation APIs (Phase 5: Memory & Proactive Suggestions)
// ============================================================================

export interface ConversationListItem {
    id: string
    workspace_id: string | null
    title: string
    message_count: number
    has_summary: boolean
    updated_at: string
    created_at: string
}

export interface ConversationListResponse {
    conversations: ConversationListItem[]
    pagination: {
        total: number
        limit: number
        offset: number
        remaining: number
    }
}

export interface AgentMessage {
    id: string
    role: 'user' | 'assistant' | 'tool'
    content: string
    context?: Record<string, unknown> | null
    tool_name?: string
    tool_input?: string
    tool_output?: string
    created_at: string
}

export interface ConversationDetailResponse {
    id: string
    workspace_id: string | null
    title: string
    summary: string | null
    message_count: number
    total_tokens: number
    created_at: string
    updated_at: string
    messages: AgentMessage[]
}

export interface DeleteConversationResponse {
    status: string
    conversation_id: string
    message: string
}

export interface AvailableModel {
    id: string
    label: string
}

/**
 * List the models the chat UI may switch between.
 */
export async function getAvailableModels(): Promise<AvailableModel[]> {
    return requestWithAuth('/agent/models')
}

/**
 * List all conversations for the authenticated user.
 * @param limit - Maximum conversations to return (default: 50, max: 100)
 * @param offset - Number of conversations to skip (default: 0)
 */
export async function listConversations(limit = 50, offset = 0): Promise<ConversationListResponse> {
    const params = new URLSearchParams({
        limit: Math.min(limit, 100).toString(),
        offset: offset.toString(),
    })
    return requestWithAuth(`/agent/conversations?${params}`)
}

/**
 * Get a specific conversation with full message history.
 * @param conversationId - UUID of the conversation
 */
export async function getConversation(conversationId: string): Promise<ConversationDetailResponse> {
    return requestWithAuth(`/agent/conversations/${conversationId}`)
}

/**
 * Delete a conversation permanently.
 * @param conversationId - UUID of the conversation
 */
export async function deleteConversation(conversationId: string): Promise<DeleteConversationResponse> {
    return requestWithAuth(`/agent/conversations/${conversationId}`, {
        method: 'DELETE',
    })
}

/**
 * Send a chat message to the agent.
 * @param message - User message
 * @param conversationId - Optional existing conversation ID (creates new if not provided)
 * @param workspaceId - Optional workspace ID for context
 */
export async function sendAgentMessage(
    message: string,
    conversationId?: string,
    workspaceId?: string,
    context?: Record<string, unknown>,
): Promise<{ conversation_id: string; reply: string }> {
    return requestWithAuth('/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            message,
            conversation_id: conversationId,
            workspace_id: workspaceId,
            context,
        }),
    })
}

export interface TokenUsage {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
}

export interface AskChoiceOption {
    label: string
    description?: string
}

export interface AskChoiceQuestion {
    id: string
    question: string
    options: AskChoiceOption[]
    allow_multiple?: boolean
}

export interface StreamEvent {
    type: 'text' | 'done' | 'tool_start' | 'tool_result' | 'thinking' | 'title_generated'
    | 'note_diff' | 'proposal_approved' | 'proposal_rejected' | 'proposal_conflict' | 'proposal_expired'
    | 'plan_proposal' | 'ask_choice'
    text?: string
    conversation_id?: string
    title?: string
    tool_name?: string
    tool_args?: Record<string, unknown>
    result?: unknown
    success?: boolean
    error?: string
    usage?: TokenUsage
    model_used?: string
    proposal_id?: string
    note_id?: string
    base_version?: number
    version?: number
    item_count?: number
    questions?: AskChoiceQuestion[]
}

export interface StreamOptions {
    model?: string
    temperature?: number
    signal?: AbortSignal
}

export async function* streamAgentMessage(
    message: string,
    conversationId?: string,
    workspaceId?: string,
    context?: Record<string, unknown>,
    options?: StreamOptions,
): AsyncGenerator<StreamEvent, void, undefined> {
    let tokens = getCurrentTokens()
    if (!tokens?.accessToken) {
        throw new Error('No authentication token available')
    }

    const url = `${API_BASE_URL}/agent/stream/chat`
    const body = JSON.stringify({
        message,
        conversation_id: conversationId,
        workspace_id: workspaceId,
        context,
        model: options?.model,
        temperature: options?.temperature,
    })

    let response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${tokens.accessToken}`,
        },
        body,
        signal: options?.signal,
    })

    // Handle 401 - token expired, refresh and retry
    if (response.status === 401 && tokens.refreshToken) {
        try {
            tokens = await refreshToken(tokens.refreshToken)
            setCurrentTokens(tokens)
            response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${tokens.accessToken}`,
                },
                body,
            })
        } catch {
            // Refresh failed, return original 401 error
            const errorData = await response.json().catch(() => ({}))
            throw new ApiError(errorData.detail || `Authentication failed: ${response.statusText}`, response.status)
        }
    }

    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new ApiError(errorData.detail || `Stream request failed: ${response.statusText}`, response.status)
    }

    const reader = response.body?.getReader()
    if (!reader) {
        throw new Error('Response body is not readable')
    }

    const decoder = new TextDecoder()
    let buffer = ''

    try {
        while (true) {
            const { done, value } = await reader.read()
            if (done) break

            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() || ''

            for (const line of lines) {
                if (!line.trim()) continue

                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6))

                        if (data.event === 'token' && data.text) {
                            yield { type: 'text', text: data.text }
                        } else if (data.event === 'done') {
                            yield {
                                type: 'done',
                                conversation_id: data.conversation_id,
                                usage: data.usage,
                                model_used: data.model_used,
                            }
                        } else if (data.event === 'title_generated') {
                            yield {
                                type: 'title_generated',
                                conversation_id: data.conversation_id,
                                title: data.title
                            }
                        } else if (data.event === 'tool_start') {
                            yield {
                                type: 'tool_start',
                                tool_name: data.tool_name,
                                tool_args: data.tool_args
                            }
                        } else if (data.event === 'tool_result') {
                            yield {
                                type: 'tool_result',
                                tool_name: data.tool_name,
                                result: data.result,
                                success: data.success,
                                error: data.error,
                            }
                        } else if (data.event === 'reasoning_token') {
                            yield {
                                type: 'thinking',
                                text: data.text
                            }
                        } else if (data.event === 'note_diff') {
                            console.log('[api.ts] note_diff event received', { proposal_id: data.proposal_id, note_id: data.note_id, base_version: data.base_version })
                            yield {
                                type: 'note_diff',
                                proposal_id: data.proposal_id,
                                note_id: data.note_id,
                                base_version: data.base_version,
                            }
                        } else if (data.event === 'plan_proposal') {
                            yield {
                                type: 'plan_proposal',
                                proposal_id: data.proposal_id,
                                item_count: data.item_count,
                            }
                        } else if (data.event === 'ask_choice') {
                            yield {
                                type: 'ask_choice',
                                questions: data.questions,
                            }
                        } else if (data.event === 'proposal_approved') {
                            yield {
                                type: 'proposal_approved',
                                proposal_id: data.proposal_id,
                                note_id: data.note_id,
                                version: data.version,
                            }
                        } else if (data.event === 'proposal_rejected') {
                            yield {
                                type: 'proposal_rejected',
                                proposal_id: data.proposal_id,
                                note_id: data.note_id,
                            }
                        } else if (data.event === 'proposal_conflict') {
                            yield {
                                type: 'proposal_conflict',
                                proposal_id: data.proposal_id,
                                note_id: data.note_id,
                                base_version: data.expected,
                                version: data.actual,
                            }
                        } else if (data.event === 'proposal_expired') {
                            yield {
                                type: 'proposal_expired',
                                proposal_id: data.proposal_id,
                                note_id: data.note_id,
                            }
                        }
                    } catch {
                        // Ignore JSON parse errors
                    }
                }
            }
        }

        // Process any remaining buffer
        if (buffer.trim() && buffer.startsWith('data: ')) {
            try {
                const data = JSON.parse(buffer.slice(6))
                if (data.event === 'token' && data.text) {
                    yield { type: 'text', text: data.text }
                } else if (data.event === 'done') {
                    yield {
                        type: 'done',
                        conversation_id: data.conversation_id,
                        usage: data.usage,
                        model_used: data.model_used,
                    }
                } else if (data.event === 'title_generated') {
                    yield {
                        type: 'title_generated',
                        conversation_id: data.conversation_id,
                        title: data.title
                    }
                } else if (data.event === 'tool_start') {
                    yield {
                        type: 'tool_start',
                        tool_name: data.tool_name,
                        tool_args: data.tool_args
                    }
                } else if (data.event === 'tool_result') {
                    yield {
                        type: 'tool_result',
                        tool_name: data.tool_name,
                        result: data.result,
                        success: data.success,
                        error: data.error,
                    }
                } else if (data.event === 'note_diff') {
                    console.log('[api.ts buffer] note_diff event received', { proposal_id: data.proposal_id, note_id: data.note_id })
                    yield {
                        type: 'note_diff',
                        proposal_id: data.proposal_id,
                        note_id: data.note_id,
                        base_version: data.base_version,
                    }
                } else if (data.event === 'plan_proposal') {
                    yield {
                        type: 'plan_proposal',
                        proposal_id: data.proposal_id,
                        item_count: data.item_count,
                    }
                } else if (data.event === 'ask_choice') {
                    yield {
                        type: 'ask_choice',
                        questions: data.questions,
                    }
                } else if (data.event === 'proposal_approved') {
                    yield {
                        type: 'proposal_approved',
                        proposal_id: data.proposal_id,
                        note_id: data.note_id,
                        version: data.version,
                    }
                } else if (data.event === 'proposal_rejected') {
                    yield {
                        type: 'proposal_rejected',
                        proposal_id: data.proposal_id,
                        note_id: data.note_id,
                    }
                } else if (data.event === 'proposal_conflict') {
                    yield {
                        type: 'proposal_conflict',
                        proposal_id: data.proposal_id,
                        note_id: data.note_id,
                        base_version: data.expected,
                        version: data.actual,
                    }
                } else if (data.event === 'proposal_expired') {
                    yield {
                        type: 'proposal_expired',
                        proposal_id: data.proposal_id,
                        note_id: data.note_id,
                    }
                }
            } catch {
                // Ignore JSON parse errors
            }
        }
    } catch (err) {
        if ((err as Error)?.name === 'AbortError') {
            return
        }
        throw err
    } finally {
        reader.releaseLock()
    }
}

export async function uploadNoteImage(
    noteId: string,
    file: File,
): Promise<{ id: string; url: string; original_filename: string; content_type: string; file_size: number }> {
    const tokens = getCurrentTokens()
    if (!tokens?.accessToken) {
        throw new Error('No authentication token available')
    }

    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(`${API_BASE_URL}/notes/${noteId}/images`, {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${tokens.accessToken}`,
        },
        body: formData,
    })

    if (!response.ok) {
        throw new ApiError('Failed to upload image', response.status)
    }

    return response.json()
}

export async function listNoteImages(noteId: string): Promise<Array<{
    id: string; url: string; original_filename: string; content_type: string; file_size: number; created_at: string
}>> {
    return requestWithAuth(`/notes/${noteId}/images`)
}

export async function deleteNoteImage(noteId: string, imageId: string): Promise<void> {
   await requestWithAuth(`/notes/${noteId}/images/${imageId}`, { method: 'DELETE' })
}

export interface PendingChange {
    id: string
    toolName: string
    actionId: string
    entityId: string
    title: string
    description: string
}

export async function revertAction(actionId: string): Promise<{ success: boolean; message: string }> {
   return requestWithAuth(`/agent/actions/${actionId}/revert`, { method: 'POST' })
}

export async function listNotifications(limit = 50, offset = 0): Promise<NotificationListResponse> {
   return requestWithAuth(`/notifications?limit=${limit}&offset=${offset}`)
}

export async function markNotificationRead(notificationId: string): Promise<NotificationResponse> {
   return requestWithAuth(`/notifications/${notificationId}/read`, { method: 'PATCH' })
}

export async function markAllNotificationsRead(): Promise<{ message: string }> {
   return requestWithAuth('/notifications/read-all', { method: 'POST' })
}

export async function deleteNotification(notificationId: string): Promise<{ message: string }> {
   return requestWithAuth(`/notifications/${notificationId}`, { method: 'DELETE' })
}

export { API_BASE_URL }
