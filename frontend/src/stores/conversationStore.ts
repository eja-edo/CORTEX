import { create } from 'zustand'
import type { ConversationListItem, AgentConversation, TokenBudgetStatus } from '../types'

interface ConversationState {
    // Conversations data
    conversations: ConversationListItem[]
    currentConversation: AgentConversation | null
    isLoadingConversations: boolean
    isLoadingCurrent: boolean
    error: string | null

    // Token budget
    tokenBudget: TokenBudgetStatus

    // Actions
    setConversations: (conversations: ConversationListItem[]) => void
    setCurrentConversation: (conversation: AgentConversation | null) => void
    setIsLoadingConversations: (loading: boolean) => void
    setIsLoadingCurrent: (loading: boolean) => void
    setError: (error: string | null) => void
    setTokenBudget: (budget: TokenBudgetStatus) => void
    updateTokenUsage: (used: number) => void
    addConversation: (conversation: ConversationListItem) => void
    removeConversation: (conversationId: string) => void
    reset: () => void
}

const initialTokenBudget: TokenBudgetStatus = {
    used: 0,
    limit: 100_000,
    remaining: 100_000,
    percentage: 0,
}

export const useConversationStore = create<ConversationState>((set, get) => ({
    conversations: [],
    currentConversation: null,
    isLoadingConversations: false,
    isLoadingCurrent: false,
    error: null,
    tokenBudget: initialTokenBudget,

    setConversations: (conversations) =>
        set({ conversations }),

    setCurrentConversation: (conversation) =>
        set({ currentConversation: conversation }),

    setIsLoadingConversations: (loading) =>
        set({ isLoadingConversations: loading }),

    setIsLoadingCurrent: (loading) =>
        set({ isLoadingCurrent: loading }),

    setError: (error) =>
        set({ error }),

    setTokenBudget: (budget) =>
        set({ tokenBudget: budget }),

    updateTokenUsage: (used) => {
        const limit = get().tokenBudget.limit
        const remaining = Math.max(0, limit - used)
        const percentage = Math.min(100, Math.round((used / limit) * 100))

        set({
            tokenBudget: {
                used,
                limit,
                remaining,
                percentage,
            },
        })
    },

    addConversation: (conversation) => {
        set((state) => ({
            conversations: [conversation, ...state.conversations],
        }))
    },

    removeConversation: (conversationId) => {
        set((state) => ({
            conversations: state.conversations.filter((c) => c.id !== conversationId),
        }))
    },

    reset: () =>
        set({
            conversations: [],
            currentConversation: null,
            isLoadingConversations: false,
            isLoadingCurrent: false,
            error: null,
            tokenBudget: initialTokenBudget,
        }),
}))
