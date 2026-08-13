import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CalendarClock, Link2, ListTodo, Repeat, X } from 'lucide-react'
import { clsx } from 'clsx'
import type { TaskPriority } from '../types'
import { usePlanProposals, type PlanItemRecurrence, type PlanProposalItem } from '../hooks/usePlanProposals'
import { PriorityIcon } from './PriorityIcon'
import { PriorityMenu } from './PriorityMenu'
import { priorityLabel } from '../utils/taskPriority'
import { DueDateEditor } from './DueDateEditor'
import { dateOnly, formatCompactDate } from '../utils/taskDateBuckets'

const RECURRENCE_FREQ_LABELS: Record<PlanItemRecurrence['freq'], string> = {
    NONE: '',
    DAILY: 'Hằng ngày',
    WEEKLY: 'Hằng tuần',
    MONTHLY: 'Hằng tháng',
}

function recurrenceLabel(rec: PlanItemRecurrence): string | null {
    if (rec.freq === 'NONE') return null
    const interval = rec.interval ?? 1
    const base = interval > 1
        ? `Mỗi ${interval} ${rec.freq === 'DAILY' ? 'ngày' : rec.freq === 'WEEKLY' ? 'tuần' : 'tháng'}`
        : RECURRENCE_FREQ_LABELS[rec.freq]
    const until = rec.until ? `đến ${formatCompactDate(dateOnly(rec.until))}` : null
    const count = !until && rec.count ? `${rec.count} lần` : null
    const suffix = until ?? count
    return suffix ? `${base} · ${suffix}` : base
}

interface EditableItem extends PlanProposalItem {
    included: boolean
}

/** How many parent_key hops this item is from a top-level item — used only
 * to indent sub-tasks visually. Bounded by the backend's cycle check, so
 * this always terminates. */
function depthOf(item: PlanProposalItem, byKey: Map<string, PlanProposalItem>): number {
    let depth = 0
    let current: PlanProposalItem | undefined = item
    const seen = new Set<string>()
    while (current?.parent_key && !seen.has(current.key)) {
        seen.add(current.key)
        current = byKey.get(current.parent_key)
        depth += 1
    }
    return depth
}

interface Props {
    proposalId: string
    onClose: () => void
    onApproved: () => void
}

export function PlanProposalCard({ proposalId, onClose, onApproved }: Props) {
    const { fetchProposal, approveProposal, rejectProposal } = usePlanProposals()
    const [items, setItems] = useState<EditableItem[] | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [actionLoading, setActionLoading] = useState<'approve' | 'reject' | null>(null)

    useEffect(() => {
        setLoading(true)
        setError(null)
        fetchProposal(proposalId)
            .then((proposal) => setItems(proposal.items.map((item) => ({ ...item, included: true }))))
            .catch((err) => setError(err instanceof Error ? err.message : 'Không tải được đề xuất'))
            .finally(() => setLoading(false))
    }, [proposalId, fetchProposal])

    const byKey = useMemo(() => {
        const map = new Map<string, PlanProposalItem>()
        for (const item of items ?? []) map.set(item.key, item)
        return map
    }, [items])

    const updateItem = useCallback((key: string, patch: Partial<EditableItem>) => {
        setItems((prev) => prev && prev.map((item) => (item.key === key ? { ...item, ...patch } : item)))
    }, [])

    const handleApprove = useCallback(async () => {
        if (!items) return
        setActionLoading('approve')
        setError(null)
        try {
            const included = items.filter((item) => item.included).map(({ included: _included, ...rest }) => rest)
            await approveProposal(proposalId, included)
            onApproved()
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Không áp dụng được đề xuất')
        } finally {
            setActionLoading(null)
        }
    }, [items, approveProposal, proposalId, onApproved])

    const handleReject = useCallback(async () => {
        setActionLoading('reject')
        setError(null)
        try {
            await rejectProposal(proposalId)
            onClose()
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Không huỷ được đề xuất')
        } finally {
            setActionLoading(null)
        }
    }, [rejectProposal, proposalId, onClose])

    const includedCount = items?.filter((i) => i.included).length ?? 0

    return (
        <div className="plan-proposal-card">
            <div className="plan-proposal-header">
                <span className="plan-proposal-title">Đề xuất kế hoạch{items ? ` (${includedCount}/${items.length})` : ''}</span>
                <button type="button" className="plan-proposal-close-btn" aria-label="Đóng" onClick={onClose}>
                    <X size={14} />
                </button>
            </div>

            {loading && <div className="plan-proposal-loading">Đang tải…</div>}
            {error && <div className="plan-proposal-error">{error}</div>}

            {items && !loading && (
                <div className="plan-proposal-list">
                    {items.map((item) => (
                        <PlanProposalItemRow
                            key={item.key}
                            item={item}
                            depth={depthOf(item, byKey)}
                            linkedEventTitle={item.related_event_key ? byKey.get(item.related_event_key)?.title : undefined}
                            onChange={(patch) => updateItem(item.key, patch)}
                        />
                    ))}
                </div>
            )}

            {items && !loading && (
                <div className="plan-proposal-actions">
                    <button
                        type="button"
                        className="plan-proposal-approve-btn"
                        disabled={actionLoading !== null || includedCount === 0}
                        onClick={() => void handleApprove()}
                    >
                        {actionLoading === 'approve' ? 'Đang áp dụng…' : 'Áp dụng'}
                    </button>
                    <button
                        type="button"
                        className="plan-proposal-reject-btn"
                        disabled={actionLoading !== null}
                        onClick={() => void handleReject()}
                    >
                        {actionLoading === 'reject' ? 'Đang huỷ…' : 'Huỷ'}
                    </button>
                </div>
            )}
        </div>
    )
}

function PlanProposalItemRow({
    item,
    depth,
    linkedEventTitle,
    onChange,
}: {
    item: EditableItem
    depth: number
    linkedEventTitle?: string
    onChange: (patch: Partial<EditableItem>) => void
}) {
    const [priorityMenuOpen, setPriorityMenuOpen] = useState(false)
    const priorityBtnRef = useRef<HTMLButtonElement | null>(null)
    const priority = (item.priority ?? null) as TaskPriority | null

    return (
        <div
            className={clsx('plan-proposal-item', item.type === 'event' && 'plan-proposal-item--event', !item.included && 'is-excluded')}
            style={depth > 0 ? { marginLeft: depth * 18 } : undefined}
        >
            <input
                type="checkbox"
                className="plan-proposal-item-check"
                checked={item.included}
                onChange={(e) => onChange({ included: e.target.checked })}
                aria-label={item.included ? 'Bỏ chọn mục này' : 'Chọn mục này'}
            />

            <span className="plan-proposal-item-type-icon" title={item.type === 'task' ? 'Việc cần làm' : 'Sự kiện'}>
                {item.type === 'task' ? <ListTodo size={13} /> : <CalendarClock size={13} />}
            </span>

            <input
                type="text"
                className="plan-proposal-item-title"
                value={item.title}
                onChange={(e) => onChange({ title: e.target.value })}
            />

            {item.type === 'task' ? (
                <>
                    <DueDateEditor
                        value={item.due_date ?? null}
                        onChange={(next) => onChange({ due_date: next })}
                        dateClassName="plan-proposal-date-input"
                        timeClassName="plan-proposal-date-input"
                        toggleClassName="plan-proposal-date-time-toggle"
                    />
                    <button
                        ref={priorityBtnRef}
                        type="button"
                        className={clsx('plan-proposal-item-priority', priority && `is-${priority}`)}
                        title={priorityLabel(priority) ?? 'Đặt ưu tiên'}
                        onClick={() => setPriorityMenuOpen((v) => !v)}
                    >
                        <PriorityIcon priority={priority} />
                    </button>
                    {priorityMenuOpen && (
                        <PriorityMenu
                            anchorRef={priorityBtnRef}
                            value={priority}
                            onSelect={(next) => {
                                setPriorityMenuOpen(false)
                                onChange({ priority: next })
                            }}
                            onClose={() => setPriorityMenuOpen(false)}
                        />
                    )}
                    {linkedEventTitle && (
                        <span className="plan-proposal-item-meta" title="Gắn với sự kiện">
                            <Link2 size={10} />
                            {linkedEventTitle}
                        </span>
                    )}
                </>
            ) : (
                <>
                    <span className="plan-proposal-item-event-time">
                        <input
                            type="datetime-local"
                            className="plan-proposal-date-input"
                            value={item.start_time?.slice(0, 16) ?? ''}
                            onChange={(e) => onChange({ start_time: e.target.value ? `${e.target.value}:00` : null })}
                        />
                        <span className="plan-proposal-item-event-sep">→</span>
                        <input
                            type="datetime-local"
                            className="plan-proposal-date-input"
                            value={item.end_time?.slice(0, 16) ?? ''}
                            onChange={(e) => onChange({ end_time: e.target.value ? `${e.target.value}:00` : null })}
                        />
                    </span>
                    {item.recurrence && recurrenceLabel(item.recurrence) && (
                        <span className="plan-proposal-item-meta" title="Lặp lại">
                            <Repeat size={10} />
                            {recurrenceLabel(item.recurrence)}
                        </span>
                    )}
                </>
            )}
        </div>
    )
}
