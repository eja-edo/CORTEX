import { createContext, useContext } from 'react'

/**
 * Context and types for the toast channel. Kept out of `Toast.tsx` because a
 * module that exports both components and non-components breaks React Fast
 * Refresh — the whole module gets remounted on edit instead of hot-swapped.
 *
 * The provider and the visual components live in `components/Toast.tsx`.
 */

export type ToastKind = 'success' | 'error' | 'info'

export type ToastAction = {
    label: string
    onAct: () => void
}

export type ToastInput = {
    kind?: ToastKind
    message: string
    action?: ToastAction
    /** Milliseconds before auto-dismiss. Pass 0 to require a manual dismiss. */
    duration?: number
}

export type ToastApi = {
    show: (input: ToastInput) => string
    dismiss: (id: string) => void
}

export const ToastContext = createContext<ToastApi | null>(null)

export function useToast(): ToastApi {
    const ctx = useContext(ToastContext)
    if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
    return ctx
}
