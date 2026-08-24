import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react'
import { ToastContext } from '../hooks/useToast'
import type { ToastAction, ToastApi, ToastInput, ToastKind } from '../hooks/useToast'

/**
 * Transient feedback, replacing two things the app did not have:
 *
 *  - Any success/failure signal at all for most actions. There are ~148
 *    `catch` blocks and ~100 `console.*` calls in the codebase and no channel
 *    that reaches the user, so a failed request looked like nothing happening.
 *
 *  - A non-destructive place to put the old `.status-bar`. That banner was an
 *    in-flow element: showing it pushed the entire app down by its height at
 *    the exact moment the user had just acted, and it had no dismiss control.
 *
 * Toasts deliberately do not take focus — a notification that steals the
 * caret mid-typing is worse than one that is missed. Screen readers get them
 * through the live region on the viewport instead.
 */

type Toast = {
    id: string
    kind: ToastKind
    message: string
    action?: ToastAction
    duration: number
}

type ShowToast = (input: ToastInput) => string

/**
 * Errors stay up longer than confirmations: a confirmation only reassures,
 * an error usually has to be read and acted on. Anything with an action
 * (undo) gets the long window too, since the action is the point.
 */
const DEFAULT_DURATION: Record<ToastKind, number> = {
    success: 4000,
    info: 5000,
    error: 8000,
}

const ICONS: Record<ToastKind, typeof CheckCircle2> = {
    success: CheckCircle2,
    error: AlertCircle,
    info: Info,
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
    const [toasts, setToasts] = useState<Toast[]>([])
    const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>())

    const dismiss = useCallback((id: string) => {
        const timer = timers.current.get(id)
        if (timer) {
            clearTimeout(timer)
            timers.current.delete(id)
        }
        setToasts((prev) => prev.filter((t) => t.id !== id))
    }, [])

    const show = useCallback<ShowToast>(({ kind = 'success', message, action, duration }) => {
        const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
        const ms = duration ?? (action ? DEFAULT_DURATION.error : DEFAULT_DURATION[kind])

        setToasts((prev) => {
            // Repeating the same message (a retry loop, a burst of failures)
            // should refresh the existing toast rather than stack copies.
            const deduped = prev.filter((t) => t.message !== message)
            // Cap the stack so a runaway loop cannot cover the whole screen.
            return [...deduped, { id, kind, message, action, duration: ms }].slice(-3)
        })

        if (ms > 0) {
            timers.current.set(id, setTimeout(() => dismiss(id), ms))
        }
        return id
    }, [dismiss])

    // Timers outlive the component if the tree unmounts mid-countdown.
    useEffect(() => {
        const pending = timers.current
        return () => {
            pending.forEach(clearTimeout)
            pending.clear()
        }
    }, [])

    const api = useMemo<ToastApi>(() => ({ show, dismiss }), [show, dismiss])

    return (
        <ToastContext.Provider value={api}>
            {children}
            <ToastViewport toasts={toasts} onDismiss={dismiss} />
        </ToastContext.Provider>
    )
}

function ToastViewport({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: string) => void }) {
    return (
        <div className="toast-viewport">
            {/*
              Two regions, because the politeness level differs and a single
              region cannot carry both. Successes wait for a pause in speech;
              errors interrupt, since the user's next action may depend on it.
            */}
            <div className="toast-live-region" aria-live="polite" aria-atomic="false">
                {toasts.filter((t) => t.kind !== 'error').map((t) => (
                    <ToastRow key={t.id} toast={t} onDismiss={onDismiss} />
                ))}
            </div>
            <div className="toast-live-region" role="alert" aria-live="assertive" aria-atomic="false">
                {toasts.filter((t) => t.kind === 'error').map((t) => (
                    <ToastRow key={t.id} toast={t} onDismiss={onDismiss} />
                ))}
            </div>
        </div>
    )
}

function ToastRow({ toast, onDismiss }: { toast: Toast; onDismiss: (id: string) => void }) {
    const Icon = ICONS[toast.kind]
    return (
        <div className={`toast toast--${toast.kind}`}>
            <Icon size={16} className="toast-icon" aria-hidden="true" />
            <span className="toast-message">{toast.message}</span>
            {toast.action && (
                <button
                    type="button"
                    className="toast-action"
                    onClick={() => {
                        toast.action?.onAct()
                        onDismiss(toast.id)
                    }}
                >
                    {toast.action.label}
                </button>
            )}
            <button
                type="button"
                className="toast-close"
                onClick={() => onDismiss(toast.id)}
                aria-label="Đóng thông báo"
            >
                <X size={14} />
            </button>
        </div>
    )
}
