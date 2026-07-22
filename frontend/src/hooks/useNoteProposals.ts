import { useCallback } from 'react'
import { requestWithAuth } from '../services/api'

export interface NoteEditProposal {
    id: string
    note_id: string
    base_revision_id: string | null
    base_version: number
    patch: Array<{ op: string; pos: number; length?: number; text?: string }>
    creator_type: string
    creator_id: string
    status: 'pending' | 'applying' | 'approved' | 'rejected' | 'expired' | 'superseded'
    approved_by: string | null
    approved_at: string | null
    rejected_by: string | null
    rejected_at: string | null
    last_viewed_at: string | null
    expires_at: string
    conversation_id: string | null
    created_at: string
    updated_at: string
    old_content: string | null
    new_content: string | null
}

export interface ApproveResponse {
    proposal_id: string
    note_id: string
    status: string
    version: number
}

export interface RejectResponse {
    proposal_id: string
    note_id: string
    status: string
}

export interface ProposalListResponse {
    items: NoteEditProposal[]
    total: number
}

export function useNoteProposals() {
    const fetchProposal = useCallback(async (proposalId: string): Promise<NoteEditProposal> => {
        return requestWithAuth<NoteEditProposal>(`/note-proposals/${proposalId}`)
    }, [])

    const listProposals = useCallback(async (params: {
        note_id?: string
        status?: string
        limit?: number
        offset?: number
    } = {}): Promise<ProposalListResponse> => {
        const query = new URLSearchParams()
        if (params.note_id) query.set('note_id', params.note_id)
        if (params.status) query.set('status', params.status)
        if (params.limit) query.set('limit', String(params.limit))
        if (params.offset) query.set('offset', String(params.offset))
        const qs = query.toString()
        return requestWithAuth<ProposalListResponse>(`/note-proposals${qs ? `?${qs}` : ''}`)
    }, [])

    const approveProposal = useCallback(async (proposalId: string): Promise<ApproveResponse> => {
        return requestWithAuth<ApproveResponse>(`/note-proposals/${proposalId}/approve`, {
            method: 'POST',
        })
    }, [])

    const rejectProposal = useCallback(async (proposalId: string): Promise<RejectResponse> => {
        return requestWithAuth<RejectResponse>(`/note-proposals/${proposalId}/reject`, {
            method: 'POST',
        })
    }, [])

    return { fetchProposal, listProposals, approveProposal, rejectProposal }
}
