import { AlarmClock, AlertTriangle, Calendar, CheckCircle2, CheckSquare, Clock, Flame, Hourglass, Info, Layers, ListChecks, Moon, RefreshCw, StickyNote, Sunrise, BellRing } from 'lucide-react'
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
    // The seven detection reasons the State Evaluator produces. Colour
    // tracks the reason's base level in
    // app/services/attention_reason_catalog.py — ASK is the loudest thing
    // that reaches this list, INFORM the quietest — so the bell reads at a
    // glance instead of flattening everything to grey `system`.
    task_overdue: {
        icon: <CheckSquare size={13} />,
        color: 'var(--red)',
    },
    task_at_risk: {
        icon: <Flame size={13} />,
        color: 'var(--red)',
    },
    task_blocked_cascade: {
        icon: <ListChecks size={13} />,
        color: 'var(--red)',
    },
    task_due_soon: {
        icon: <Hourglass size={13} />,
        color: 'var(--yellow)',
    },
    task_stale: {
        icon: <Clock size={13} />,
        color: 'var(--text-tertiary)',
    },
    schedule_starts_soon: {
        icon: <AlarmClock size={13} />,
        color: 'var(--yellow)',
    },
    day_review: {
        icon: <Moon size={13} />,
        color: 'var(--purple)',
    },
    day_plan: {
        icon: <Sunrise size={13} />,
        color: 'var(--green)',
    },
    attention_bundle: {
        icon: <Layers size={13} />,
        color: 'var(--accent)',
    },
}
