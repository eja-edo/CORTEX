import { useCallback } from 'react'
import { requestWithAuth } from '../services/api'

export interface PlanItemRecurrence {
    freq: 'NONE' | 'DAILY' | 'WEEKLY' | 'MONTHLY'
    interval?: number
    until?: string | null
    count?: number | null
    tzid?: string
}

export interface PlanProposalItem {
    key: string
    type: 'task' | 'event'
    title: string
    description?: string | null
    // Task-only
    due_date?: string | null
    priority?: string | null
    parent_key?: string | null
    related_event_key?: string | null
    // Event-only
    start_time?: string | null
    end_time?: string | null
    location?: string | null
    recurrence?: PlanItemRecurrence | null
}

export interface PlanProposal {
    id: string
    user_id: string
    conversation_id: string | null
    items: PlanProposalItem[]
    status: 'pending' | 'approved' | 'rejected' | 'expired'
    creator_type: string
    creator_id: string
    created_at: string
    expires_at: string
    approved_at: string | null
    rejected_at: string | null
}

export interface PlanProposalItemResult {
    key: string
    type: 'task' | 'event'
    outcome: 'created' | 'failed'
    id: string | null
    error: string | null
}

export interface PlanProposalApproveResponse {
    proposal_id: string
    status: string
    results: PlanProposalItemResult[]
    created_count: number
    failed_count: number
}

export interface PlanProposalRejectResponse {
    proposal_id: string
    status: string
}

export function usePlanProposals() {
    const fetchProposal = useCallback(async (proposalId: string): Promise<PlanProposal> => {
        return requestWithAuth<PlanProposal>(`/plan-proposals/${proposalId}`)
    }, [])

    const approveProposal = useCallback(async (
        proposalId: string,
        items?: PlanProposalItem[],
    ): Promise<PlanProposalApproveResponse> => {
        return requestWithAuth<PlanProposalApproveResponse>(`/plan-proposals/${proposalId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(items !== undefined ? { items } : {}),
        })
    }, [])

    const rejectProposal = useCallback(async (proposalId: string): Promise<PlanProposalRejectResponse> => {
        return requestWithAuth<PlanProposalRejectResponse>(`/plan-proposals/${proposalId}/reject`, {
            method: 'POST',
        })
    }, [])

    return { fetchProposal, approveProposal, rejectProposal }
}
