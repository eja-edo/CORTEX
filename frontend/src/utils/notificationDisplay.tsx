import { AlertTriangle, Calendar, CheckCircle2, CheckSquare, Info, Layers, RefreshCw, StickyNote, BellRing } from 'lucide-react'
import type { NotificationKind } from '../components/NotificationBell'

export function timeAgo(date: Date): string {
    const diff = Date.now() - date.getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'Vừa xong'
    if (mins < 60) return `${mins} phút trước`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs} giờ trước`
    return date.toLocaleDateString('vi-VN')
}

export const KIND_META: Record<NotificationKind, { icon: React.ReactNode; color: string }> = {
    sync: {
        icon: <RefreshCw size={13} />,
        color: 'var(--accent)',
    },
    schedule: {
        icon: <Calendar size={13} />,
        color: 'var(--yellow)',
    },
    reminder: {
        icon: <BellRing size={13} />,
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
    task_overdue: {
        icon: <CheckSquare size={13} />,
        color: 'var(--red)',
    },
    attention_bundle: {
        icon: <Layers size={13} />,
        color: 'var(--accent)',
    },
}
