import { useState } from 'react'
import { Check, X, Wrench } from 'lucide-react'
import type { PendingToolCall, ToolCallDecision } from '../services/api'

interface Props {
    pending: PendingToolCall[]
    onResolve: (decisions: ToolCallDecision[]) => void
    isResolving?: boolean
}

/** Best-effort human-readable summary of a tool call's args — good enough
 * for a confirmation card, not meant to be a full inspector. */
function formatArgs(args: Record<string, unknown>): string | null {
    const entries = Object.entries(args ?? {})
    if (entries.length === 0) return null
    return entries
        .map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
        .join(' · ')
}

/** Manual execution mode's approval card — mirrors PlanProposalCard's
 * checkbox-per-item + one submit pattern, but talks to a dedicated
 * approve/reject endpoint (POST .../tool-calls/resolve) instead of
 * round-tripping through the LLM like AskChoiceCard's answers do. Shown
 * whenever `useAgentStream`'s `pendingApproval` is non-null — see
 * AgentService._run_tool_loop's manual-mode guard on the backend for why
 * the turn stopped here. */
export function ToolCallApprovalCard({ pending, onResolve, isResolving }: Props) {
    const [approved, setApproved] = useState<Record<string, boolean>>(
        () => Object.fromEntries(pending.map(p => [p.id, true]))
    )

    const toggle = (id: string) => {
        setApproved(prev => ({ ...prev, [id]: !prev[id] }))
    }

    const submit = () => {
        onResolve(pending.map(p => ({ pending_id: p.id, approved: approved[p.id] ?? true })))
    }

    const rejectAll = () => {
        onResolve(pending.map(p => ({ pending_id: p.id, approved: false })))
    }

    const approvedCount = pending.filter(p => approved[p.id]).length

    return (
        <div className="tool-approval-card">
            <div className="tool-approval-header">
                <Wrench size={13} />
                <span className="tool-approval-title">
                    Đang chờ duyệt ({approvedCount}/{pending.length})
                </span>
            </div>

            <div className="tool-approval-list">
                {pending.map(call => (
                    <label key={call.id} className="tool-approval-item">
                        <input
                            type="checkbox"
                            checked={approved[call.id] ?? true}
                            onChange={() => toggle(call.id)}
                            disabled={isResolving}
                        />
                        <div className="tool-approval-item-body">
                            <span className="tool-approval-item-name">{call.tool_name}</span>
                            {formatArgs(call.tool_input) && (
                                <span className="tool-approval-item-args">{formatArgs(call.tool_input)}</span>
                            )}
                        </div>
                    </label>
                ))}
            </div>

            <div className="tool-approval-actions">
                <button
                    type="button"
                    className="tool-approval-approve-btn"
                    disabled={isResolving}
                    onClick={submit}
                >
                    <Check size={13} />
                    {isResolving ? 'Đang xử lý…' : approvedCount === pending.length ? 'Chạy tất cả' : `Chạy (${approvedCount})`}
                </button>
                <button
                    type="button"
                    className="tool-approval-reject-btn"
                    disabled={isResolving}
                    onClick={rejectAll}
                >
                    <X size={13} />
                    Từ chối tất cả
                </button>
            </div>
        </div>
    )
}
