import type { TokenPair } from '../types'

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
): Promise<{ conversation_id: string; reply: string }> {
    return requestWithAuth('/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            message,
            conversation_id: conversationId,
            workspace_id: workspaceId,
        }),
    })
}

export { API_BASE_URL }
