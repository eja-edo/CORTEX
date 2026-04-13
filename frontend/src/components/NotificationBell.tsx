import { useCallback, useEffect, useRef, useState } from 'react'
import { Bell, BellOff, Calendar, CheckCircle2, RefreshCw, StickyNote, X } from 'lucide-react'

export type NotificationKind = 'sync' | 'schedule' | 'note' | 'system'

export type AppNotification = {
    id: string
    kind: NotificationKind
    title: string
    body: string
    timestamp: Date
    read: boolean
}

interface NotificationBellProps {
    notifications: AppNotification[]
    onMarkRead: (id: string) => void
    onMarkAllRead: () => void
    onDismiss: (id: string) => void
}

function timeAgo(date: Date): string {
    const diff = Date.now() - date.getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'Vừa xong'
    if (mins < 60) return `${mins} phút trước`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs} giờ trước`
    return date.toLocaleDateString('vi-VN')
}

const KIND_META: Record<NotificationKind, { icon: React.ReactNode; color: string }> = {
    sync: {
        icon: <RefreshCw size={13} />,
        color: 'var(--accent)',
    },
    schedule: {
        icon: <Calendar size={13} />,
        color: 'var(--yellow)',
    },
    note: {
        icon: <StickyNote size={13} />,
        color: 'var(--green)',
    },
    system: {
        icon: <CheckCircle2 size={13} />,
        color: 'var(--text-tertiary)',
    },
}

export function NotificationBell({
    notifications,
    onMarkRead,
    onMarkAllRead,
    onDismiss,
}: NotificationBellProps) {
    const [isOpen, setIsOpen] = useState(false)
    const [animatingIds, setAnimatingIds] = useState<Set<string>>(new Set())
    const panelRef = useRef<HTMLDivElement>(null)
    const btnRef = useRef<HTMLButtonElement>(null)

    const unreadCount = notifications.filter((n) => !n.read).length

    const handleToggle = useCallback(() => {
        setIsOpen((prev) => !prev)
    }, [])

    const handleMarkRead = useCallback(
        (id: string) => {
            onMarkRead(id)
        },
        [onMarkRead],
    )

    const handleDismiss = useCallback(
        (id: string, e: React.MouseEvent) => {
            e.stopPropagation()
            setAnimatingIds((prev) => new Set(prev).add(id))
            setTimeout(() => {
                onDismiss(id)
                setAnimatingIds((prev) => {
                    const next = new Set(prev)
                    next.delete(id)
                    return next
                })
            }, 240)
        },
        [onDismiss],
    )

    // Close on outside click
    useEffect(() => {
        if (!isOpen) return
        const onPointerDown = (e: PointerEvent) => {
            if (
                panelRef.current?.contains(e.target as Node) ||
                btnRef.current?.contains(e.target as Node)
            )
                return
            setIsOpen(false)
        }
        document.addEventListener('pointerdown', onPointerDown, true)
        return () => document.removeEventListener('pointerdown', onPointerDown, true)
    }, [isOpen])

    return (
        <div className="notif-root" style={{ position: 'relative' }}>
            <button
                ref={btnRef}
                type="button"
                className={`topbar-btn notif-bell-btn ${unreadCount > 0 ? 'has-unread' : ''}`}
                onClick={handleToggle}
                aria-label={`Thông báo${unreadCount > 0 ? ` (${unreadCount} chưa đọc)` : ''}`}
                title="Notifications"
            >
                {unreadCount > 0 ? <Bell size={14} /> : <BellOff size={14} />}
                {unreadCount > 0 && (
                    <span className="notif-badge" aria-hidden>
                        {unreadCount > 9 ? '9+' : unreadCount}
                    </span>
                )}
            </button>

            {isOpen && (
                <div ref={panelRef} className="notif-panel" role="dialog" aria-label="Notifications">
                    <div className="notif-panel-header">
                        <span className="notif-panel-title">Thông báo</span>
                        {unreadCount > 0 && (
                            <button
                                type="button"
                                className="notif-mark-all-btn"
                                onClick={() => { onMarkAllRead(); }}
                            >
                                Đánh dấu tất cả đã đọc
                            </button>
                        )}
                    </div>

                    <div className="notif-list">
                        {notifications.length === 0 ? (
                            <div className="notif-empty">
                                <BellOff size={22} strokeWidth={1.5} style={{ color: 'var(--text-disabled)' }} />
                                <span>Không có thông báo nào</span>
                            </div>
                        ) : (
                            notifications.map((n) => {
                                const meta = KIND_META[n.kind]
                                const isExiting = animatingIds.has(n.id)
                                return (
                                    <div
                                        key={n.id}
                                        className={`notif-item ${!n.read ? 'unread' : ''} ${isExiting ? 'exiting' : ''}`}
                                        onClick={() => handleMarkRead(n.id)}
                                        role="button"
                                        tabIndex={0}
                                        onKeyDown={(e) => e.key === 'Enter' && handleMarkRead(n.id)}
                                    >
                                        <div
                                            className="notif-kind-icon"
                                            style={{ color: meta.color, background: `${meta.color}14` }}
                                        >
                                            {meta.icon}
                                        </div>
                                        <div className="notif-item-body">
                                            <div className="notif-item-title">{n.title}</div>
                                            <div className="notif-item-text">{n.body}</div>
                                            <div className="notif-item-time">{timeAgo(n.timestamp)}</div>
                                        </div>
                                        <div className="notif-item-actions">
                                            {!n.read && <span className="notif-unread-dot" aria-label="Chưa đọc" />}
                                            <button
                                                type="button"
                                                className="notif-dismiss-btn"
                                                onClick={(e) => handleDismiss(n.id, e)}
                                                aria-label="Bỏ thông báo"
                                                title="Dismiss"
                                            >
                                                <X size={11} />
                                            </button>
                                        </div>
                                    </div>
                                )
                            })
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}