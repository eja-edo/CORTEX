import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNoteProposals, type NoteEditProposal } from '../hooks/useNoteProposals'

interface DiffLine {
    type: 'equal' | 'insert' | 'delete'
    text: string
}

function computeLineDiff(oldText: string, newText: string): DiffLine[] {
    if (oldText === newText) return [{ type: 'equal', text: oldText }]

    const oldLines = oldText.split('\n')
    const newLines = newText.split('\n')
    const m = oldLines.length
    const n = newLines.length

    // Build LCS table
    const lcs: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
    for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
            lcs[i][j] = oldLines[i - 1] === newLines[j - 1]
                ? lcs[i - 1][j - 1] + 1
                : Math.max(lcs[i - 1][j], lcs[i][j - 1])
        }
    }

    // Backtrack to build diff result
    const result: DiffLine[] = []
    let i = m
    let j = n
    while (i > 0 || j > 0) {
        if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
            result.push({ type: 'equal', text: oldLines[i - 1] })
            i--
            j--
        } else if (j > 0 && (i === 0 || lcs[i][j - 1] >= lcs[i - 1][j])) {
            result.push({ type: 'insert', text: newLines[j - 1] })
            j--
        } else {
            result.push({ type: 'delete', text: oldLines[i - 1] })
            i--
        }
    }
    result.reverse()

    // Merge consecutive same-type lines
    const merged: DiffLine[] = []
    for (const line of result) {
        const last = merged[merged.length - 1]
        if (last && last.type === line.type) {
            last.text += '\n' + line.text
        } else {
            merged.push({ ...line, text: line.text })
        }
    }
    return merged
}

interface Props {
    noteId: string
    proposalId: string
    onClose: () => void
    onApproved: (noteId: string) => void
}

export function DiffReviewPanel({ noteId, proposalId, onClose, onApproved }: Props) {
    const [proposal, setProposal] = useState<NoteEditProposal | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [actionLoading, setActionLoading] = useState<'approve' | 'reject' | null>(null)
    const { fetchProposal, approveProposal, rejectProposal } = useNoteProposals()

    useEffect(() => {
        setLoading(true)
        setError(null)
        fetchProposal(proposalId)
            .then(setProposal)
            .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load proposal'))
            .finally(() => setLoading(false))
    }, [proposalId, fetchProposal])

    const diffLines = useMemo(() => {
        if (!proposal?.old_content || !proposal?.new_content) return []
        return computeLineDiff(proposal.old_content, proposal.new_content)
    }, [proposal])

    const handleApprove = useCallback(async () => {
        setActionLoading('approve')
        try {
            await approveProposal(proposalId)
            setProposal((prev) => prev ? { ...prev, status: 'approved' } : prev)
            onApproved(noteId)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to approve')
        } finally {
            setActionLoading(null)
        }
    }, [proposalId, approveProposal, onApproved, noteId])

    const handleReject = useCallback(async () => {
        setActionLoading('reject')
        try {
            await rejectProposal(proposalId)
            onClose()
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to reject')
        } finally {
            setActionLoading(null)
        }
    }, [proposalId, rejectProposal, onClose])

    if (loading) {
        return (
            <div className="diff-review-panel">
                <div className="diff-review-loading">Loading changes...</div>
            </div>
        )
    }

    if (error) {
        return (
            <div className="diff-review-panel">
                <div className="diff-review-error">{error}</div>
                <button onClick={onClose} className="diff-review-close-btn">Close</button>
            </div>
        )
    }

    if (!proposal) return null

    const isPending = proposal.status === 'pending'
    const isTerminal = proposal.status === 'approved' || proposal.status === 'rejected'

    return (
        <div className="diff-review-panel">
            <div className="diff-review-header">
                <h3>Review AI Changes</h3>
                <span className={`diff-review-status status-${proposal.status}`}>
                    {proposal.status}
                </span>
                <button onClick={onClose} className="diff-review-close-btn">&times;</button>
            </div>

            {isTerminal && (
                <div className="diff-review-message">
                    {proposal.status === 'approved'
                        ? 'Changes have been applied to the note.'
                        : 'Changes were rejected.'}
                </div>
            )}

            <div className="diff-review-stats">
                <span>+{diffLines.filter(l => l.type === 'insert').length} additions</span>
                <span>-{diffLines.filter(l => l.type === 'delete').length} deletions</span>
            </div>

            <div className="diff-review-content">
                {diffLines.map((line, i) => (
                    <div key={i} className={`diff-line diff-line-${line.type}`}>
                        <span className="diff-line-marker">
                            {line.type === 'insert' ? '+' : line.type === 'delete' ? '-' : ' '}
                        </span>
                        <span className="diff-line-text">{line.text || ' '}</span>
                    </div>
                ))}
            </div>

            {isPending && (
                <div className="diff-review-actions">
                    <button
                        onClick={handleApprove}
                        disabled={actionLoading !== null}
                        className="diff-review-approve-btn"
                    >
                        {actionLoading === 'approve' ? 'Applying...' : 'Approve'}
                    </button>
                    <button
                        onClick={handleReject}
                        disabled={actionLoading !== null}
                        className="diff-review-reject-btn"
                    >
                        {actionLoading === 'reject' ? 'Rejecting...' : 'Reject'}
                    </button>
                </div>
            )}
        </div>
    )
}
