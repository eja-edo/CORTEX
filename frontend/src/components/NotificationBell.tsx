import { useCallback, useEffect, useRef, useState } from 'react'
import { Bell, BellOff, Calendar, CheckCircle2, Info, RefreshCw, StickyNote, X, AlertTriangle, CheckSquare } from 'lucide-react'
import { BlockRenderer } from './BlockRenderer'
import type { NotificationBlock, NotificationActionDef } from '../types'

export type NotificationKind = 'sync' | 'schedule' | 'note' | 'system' | 'info' | 'success' | 'warning' | 'error'

export type AppNotification = {
   id: string
   kind: NotificationKind
   title: string
   body: string
   timestamp: Date
   read: boolean
   payload?: Record<string, unknown>
   content?: NotificationBlock[]
   actions?: NotificationActionDef[]
}

interface NotificationBellProps {
   notifications: AppNotification[]
   onMarkRead: (id: string) => void
   onMarkAllRead: () => void
   onDismiss: (id: string) => void
   onNavigate?: (path: string) => void
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
   info: {
       icon: <Info size={13} />,
       color: 'var(--accent)',
   },
   success: {
       icon: <CheckSquare size={13} />,
       color: 'var(--green)',
   },
   warning: {
       icon: <AlertTriangle size={13} />,
       color: 'var(--yellow)',
   },
   error: {
       icon: <AlertTriangle size={13} />,
       color: 'var(--red)',
   },
}

export function NotificationBell({
   notifications,
   onMarkRead,
   onMarkAllRead,
   onDismiss,
   onNavigate,
}: NotificationBellProps) {
   const [isOpen, setIsOpen] = useState(false)
   const [animatingIds, setAnimatingIds] = useState<Set<string>>(new Set())
   const panelRef = useRef<HTMLDivElement>(null)
   const btnRef = useRef<HTMLButtonElement>(null)

   const unreadCount = notifications.filter((n) => !n.read).length

    const handleToggle = useCallback(() => {
        setIsOpen((prev) => !prev)
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission()
        }
    }, [])

   const handleItemClick = useCallback(
       (notification: AppNotification) => {
           onMarkRead(notification.id)
           if (notification.payload?.navigate_to) {
               onNavigate?.(String(notification.payload.navigate_to))
           }
           setIsOpen(false)
       },
       [onMarkRead, onNavigate],
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
                className={`topbar-icon-btn ${unreadCount > 0 ? 'has-unread' : ''}`}
                onClick={handleToggle}
                aria-label={`Thông báo${unreadCount > 0 ? ` (${unreadCount} chưa đọc)` : ''}`}
                title="Notifications"
            >
                <Bell size={18} />
                {unreadCount > 0 && (
                    <span className="topbar-icon-btn-badge" aria-hidden>
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
                                           onClick={() => handleItemClick(n)}
                                           role="button"
                                           tabIndex={0}
                                           onKeyDown={(e) => e.key === 'Enter' && handleItemClick(n)}
                                       >
                                        <div
                                            className="notif-kind-icon"
                                            style={{ color: meta.color, background: `${meta.color}14` }}
                                        >
                                            {meta.icon}
                                        </div>
                                        <div className="notif-item-body">
                                             <div className="notif-item-title">{n.title}</div>
                                             {n.content && n.content.length > 0 ? (
                                                <BlockRenderer blocks={n.content} actions={n.actions} onNavigate={onNavigate} />
                                             ) : n.body ? (
                                                <div className="notif-item-text">{n.body}</div>
                                             ) : null}
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