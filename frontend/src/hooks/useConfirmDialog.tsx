import { useCallback, useState } from 'react'
import { ConfirmDialog } from '../components/ConfirmDialog'
import type { ConfirmPrompt } from '../utils/taskCascade'

type PendingConfirm = {
    title: string
    message: string
    confirmLabel: string
    cancelLabel: string
    resolve: (confirmed: boolean) => void
}

/**
 * A promise-based yes/no dialog: `await confirm({...})` resolves `true`/
 * `false` once the user picks, instead of every caller wiring up its own
 * open/close state. Render `dialog` once near the root of whichever
 * component calls `confirm` — it's `null` until a confirmation is pending.
 */
export function useConfirmDialog(): { confirm: ConfirmPrompt; dialog: React.ReactNode } {
    const [pending, setPending] = useState<PendingConfirm | null>(null)

    const confirm = useCallback<ConfirmPrompt>((options) => {
        return new Promise<boolean>((resolve) => {
            setPending({ ...options, resolve })
        })
    }, [])

    const dialog = pending ? (
        <ConfirmDialog
            title={pending.title}
            message={pending.message}
            confirmLabel={pending.confirmLabel}
            cancelLabel={pending.cancelLabel}
            onConfirm={() => {
                pending.resolve(true)
                setPending(null)
            }}
            onCancel={() => {
                pending.resolve(false)
                setPending(null)
            }}
        />
    ) : null

    return { confirm, dialog }
}
