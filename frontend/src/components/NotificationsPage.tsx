import { useCallback, useEffect, useState } from 'react'
import { BellOff, Check, ChevronLeft, ChevronRight, RefreshCw, Trash2 } from 'lucide-react'
import { NotificationDetailModal } from './NotificationDetailModal'
import { KIND_META, timeAgo } from '../utils/notificationDisplay'
import type { NotificationKind } from './NotificationBell'
import {
    listNotifications,
    markNotificationRead,
    markAllNotificationsRead,
    deleteNotification,
    recordAttentionResponse,
} from '../services/api'
import type { NotificationResponse } from '../types'

const PAGE_SIZE = 20

type NotificationsPageProps = {
    onNavigate?: (path: string) => void
    /** Lets the parent refresh the bell's badge/list after a mutation made here. */
    onNotificationsChanged?: () => void
}

function pageNumbers(current: number, total: number): (number | 'ellipsis')[] {
    if (total <= 7) return Array.from({ length: total }, (_, i) => i)
    const pages = new Set<number>([0, total - 1, current, current - 1, current + 1])
    const sorted = [...pages].filter((p) => p >= 0 && p < total).sort((a, b) => a - b)
    const result: (number | 'ellipsis')[] = []
    sorted.forEach((p, i) => {
        if (i > 0 && p - sorted[i - 1] > 1) result.push('ellipsis')
        result.push(p)
    })
    return result
}

export function NotificationsPage({ onNavigate, onNotificationsChanged }: NotificationsPageProps) {
    const [items, setItems] = useState<NotificationResponse[]>([])
    const [total, setTotal] = useState(0)
    const [page, setPage] = useState(0)
    const [isLoading, setIsLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [selected, setSelected] = useState<Set<string>>(new Set())
    const [busyIds, setBusyIds] = useState<Set<string>>(new Set())
    const [detail, setDetail] = useState<NotificationResponse | null>(null)

    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

    const fetchPage = useCallback(async (targetPage: number) => {
        setIsLoading(true)
        setError(null)
        try {
            const data = await listNotifications(PAGE_SIZE, targetPage * PAGE_SIZE)
            setItems(data.items)
            setTotal(data.total)
            setPage(targetPage)
            setSelected(new Set())
        } catch {
            setError('Không thể tải thông báo. Vui lòng thử lại.')
        } finally {
            setIsLoading(false)
        }
    }, [])

    useEffect(() => {
        void fetchPage(0)
    }, [fetchPage])

    const goToPage = useCallback((target: number) => {
        if (target < 0 || target >= totalPages || target === page || isLoading) return
        void fetchPage(target)
    }, [fetchPage, isLoading, page, totalPages])

    const toggleSelect = useCallback((id: string) => {
        setSelected((prev) => {
            const next = new Set(prev)
            if (next.has(id)) next.delete(id)
            else next.add(id)
            return next
        })
    }, [])

    const isAllSelected = items.length > 0 && items.every((n) => selected.has(n.id))

    const toggleSelectAll = useCallback(() => {
        setSelected((prev) => {
            if (items.length > 0 && items.every((n) => prev.has(n.id))) return new Set()
            return new Set(items.map((n) => n.id))
        })
    }, [items])

    const markReadLocally = useCallback((ids: Set<string>) => {
        const nowIso = new Date().toISOString()
        setItems((prev) => prev.map((n) => (ids.has(n.id) && !n.read_at ? { ...n, read_at: nowIso } : n)))
    }, [])

    const handleMarkRead = useCallback(async (ids: string[]) => {
        const targets = ids.filter((id) => {
            const n = items.find((it) => it.id === id)
            return n && !n.read_at
        })
        if (targets.length === 0) return
        setBusyIds((prev) => new Set([...prev, ...targets]))
        markReadLocally(new Set(targets))
        try {
            await Promise.all(targets.map((id) => markNotificationRead(id)))
            onNotificationsChanged?.()
        } catch {
            setError('Không thể đánh dấu đã đọc. Vui lòng thử lại.')
        } finally {
            setBusyIds((prev) => {
                const next = new Set(prev)
                targets.forEach((id) => next.delete(id))
                return next
            })
        }
    }, [items, markReadLocally, onNotificationsChanged])

    const handleMarkAllRead = useCallback(async () => {
        try {
            await markAllNotificationsRead()
            setItems((prev) => prev.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })))
            onNotificationsChanged?.()
        } catch {
            setError('Không thể đánh dấu tất cả đã đọc. Vui lòng thử lại.')
        }
    }, [onNotificationsChanged])

    const handleDelete = useCallback(async (ids: string[]) => {
        if (ids.length === 0) return
        const confirmMsg = ids.length === 1
            ? 'Xoá thông báo này?'
            : `Xoá ${ids.length} thông báo đã chọn?`
        if (!window.confirm(confirmMsg)) return

        setBusyIds((prev) => new Set([...prev, ...ids]))
        // Feedback Loop (6.9) raw material — a bulk/single delete here is a
        // dismiss, for every id that came from a gated (not pass-through)
        // notification.
        ids.forEach((id) => {
            const logId = items.find((it) => it.id === id)?.attention_log_id
            if (logId) recordAttentionResponse(logId, 'dismissed')
        })
        try {
            await Promise.all(ids.map((id) => deleteNotification(id)))
            setDetail((prev) => (prev && ids.includes(prev.id) ? null : prev))
            onNotificationsChanged?.()
            // Refetch the current page — deleting can shift the total count and
            // leave the page short, so recompute from the server rather than
            // patch local state.
            const remaining = total - ids.length
            const lastPage = Math.max(0, Math.ceil(remaining / PAGE_SIZE) - 1)
            await fetchPage(Math.min(page, lastPage))
        } catch {
            setError('Không thể xoá thông báo. Vui lòng thử lại.')
        } finally {
            setBusyIds((prev) => {
                const next = new Set(prev)
                ids.forEach((id) => next.delete(id))
                return next
            })
        }
    }, [fetchPage, items, onNotificationsChanged, page, total])

    const handleRowClick = useCallback((n: NotificationResponse) => {
        setDetail(n)
        if (!n.read_at) void handleMarkRead([n.id])
    }, [handleMarkRead])

    const handleDetailNavigate = useCallback((path: string) => {
        if (detail?.attention_log_id) recordAttentionResponse(detail.attention_log_id, 'accepted')
        setDetail(null)
        onNavigate?.(path)
    }, [onNavigate, detail])

    const selectedCount = selected.size
    const rangeStart = total === 0 ? 0 : page * PAGE_SIZE + 1
    const rangeEnd = Math.min(total, page * PAGE_SIZE + items.length)

    return (
        <div className="today-panel notifications-page">
            <header className="notifications-page-header">
                <h1 className="notifications-page-title">Thông báo</h1>
                <p className="notifications-page-subtitle">
                    {total > 0 ? `${total} thông báo` : 'Không có thông báo nào'}
                </p>
            </header>

            {error && <p className="notifications-page-error">{error}</p>}

            <div className="notifications-toolbar">
                <label className="notifications-select-all">
                    <input
                        type="checkbox"
                        checked={isAllSelected}
                        onChange={toggleSelectAll}
                        aria-label="Chọn tất cả"
                        disabled={items.length === 0}
                    />
                </label>

                {selectedCount > 0 ? (
                    <div className="notifications-toolbar-actions">
                        <span className="notifications-selected-count">{selectedCount} đã chọn</span>
                        <button
                            type="button"
                            className="notifications-toolbar-btn"
                            onClick={() => void handleMarkRead([...selected])}
                            title="Đánh dấu đã đọc"
                        >
                            <Check size={15} />
                            <span>Đánh dấu đã đọc</span>
                        </button>
                        <button
                            type="button"
                            className="notifications-toolbar-btn danger"
                            onClick={() => void handleDelete([...selected])}
                            title="Xoá"
                        >
                            <Trash2 size={15} />
                            <span>Xoá</span>
                        </button>
                    </div>
                ) : (
                    <div className="notifications-toolbar-actions">
                        <button
                            type="button"
                            className="notifications-toolbar-btn"
                            onClick={() => void fetchPage(page)}
                            title="Làm mới"
                            disabled={isLoading}
                        >
                            <RefreshCw size={15} className={isLoading ? 'spin' : ''} />
                        </button>
                        <button
                            type="button"
                            className="notifications-toolbar-btn"
                            onClick={() => void handleMarkAllRead()}
                        >
                            Đánh dấu tất cả đã đọc
                        </button>
                    </div>
                )}

                <div className="notifications-toolbar-pagination">
                    <span className="notifications-range-label">
                        {total > 0 ? `${rangeStart}–${rangeEnd} / ${total}` : ''}
                    </span>
                    <button
                        type="button"
                        className="notifications-page-arrow"
                        onClick={() => goToPage(page - 1)}
                        disabled={page === 0 || isLoading}
                        aria-label="Trang trước"
                    >
                        <ChevronLeft size={16} />
                    </button>
                    <button
                        type="button"
                        className="notifications-page-arrow"
                        onClick={() => goToPage(page + 1)}
                        disabled={page >= totalPages - 1 || isLoading}
                        aria-label="Trang sau"
                    >
                        <ChevronRight size={16} />
                    </button>
                </div>
            </div>

            <div className="notifications-list">
                {items.length === 0 && !isLoading ? (
                    <div className="notifications-empty">
                        <BellOff size={28} strokeWidth={1.5} />
                        <span>Không có thông báo nào</span>
                    </div>
                ) : (
                    items.map((n) => {
                        const kind = (n.type as NotificationKind) in KIND_META ? (n.type as NotificationKind) : 'system'
                        const meta = KIND_META[kind]
                        const isUnread = !n.read_at
                        const isBusy = busyIds.has(n.id)
                        return (
                            <div
                                key={n.id}
                                className={`notifications-row ${isUnread ? 'unread' : ''} ${selected.has(n.id) ? 'selected' : ''} ${isBusy ? 'busy' : ''}`}
                                onClick={() => handleRowClick(n)}
                                role="button"
                                tabIndex={0}
                                onKeyDown={(e) => e.key === 'Enter' && handleRowClick(n)}
                            >
                                <input
                                    type="checkbox"
                                    className="notifications-row-checkbox"
                                    checked={selected.has(n.id)}
                                    onClick={(e) => e.stopPropagation()}
                                    onChange={() => toggleSelect(n.id)}
                                    aria-label={`Chọn: ${n.title}`}
                                />
                                <div
                                    className="notifications-row-icon"
                                    style={{ color: meta.color, background: `${meta.color}14` }}
                                >
                                    {meta.icon}
                                </div>
                                <div className="notifications-row-body">
                                    <span className="notifications-row-title">{n.title}</span>
                                    {n.body && <span className="notifications-row-snippet">{n.body}</span>}
                                </div>
                                <span className="notifications-row-time">{timeAgo(new Date(n.created_at))}</span>
                                <button
                                    type="button"
                                    className="notifications-row-delete"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        void handleDelete([n.id])
                                    }}
                                    aria-label="Xoá thông báo"
                                    title="Xoá"
                                >
                                    <Trash2 size={14} />
                                </button>
                            </div>
                        )
                    })
                )}
            </div>

            {totalPages > 1 && (
                <div className="notifications-pagination">
                    <button
                        type="button"
                        className="notifications-page-arrow"
                        onClick={() => goToPage(page - 1)}
                        disabled={page === 0 || isLoading}
                        aria-label="Trang trước"
                    >
                        <ChevronLeft size={16} />
                    </button>
                    {pageNumbers(page, totalPages).map((p, i) =>
                        p === 'ellipsis' ? (
                            <span key={`ellipsis-${i}`} className="notifications-page-ellipsis">…</span>
                        ) : (
                            <button
                                key={p}
                                type="button"
                                className={`notifications-page-number ${p === page ? 'active' : ''}`}
                                onClick={() => goToPage(p)}
                                disabled={isLoading}
                            >
                                {p + 1}
                            </button>
                        ),
                    )}
                    <button
                        type="button"
                        className="notifications-page-arrow"
                        onClick={() => goToPage(page + 1)}
                        disabled={page >= totalPages - 1 || isLoading}
                        aria-label="Trang sau"
                    >
                        <ChevronRight size={16} />
                    </button>
                </div>
            )}

            {detail && (
                <NotificationDetailModal
                    title={detail.title}
                    timestamp={new Date(detail.created_at)}
                    body={detail.body}
                    content={detail.content}
                    actions={detail.actions}
                    navigateTo={typeof detail.payload?.navigate_to === 'string' ? detail.payload.navigate_to : undefined}
                    onClose={() => setDetail(null)}
                    onNavigate={handleDetailNavigate}
                    onDelete={() => void handleDelete([detail.id])}
                />
            )}
        </div>
    )
}
