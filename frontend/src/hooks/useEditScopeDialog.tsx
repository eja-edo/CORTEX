import { useCallback, useState } from 'react'
import { EditScopeDialog } from '../components/EditScopeDialog'
import type { EditScope } from '../types'

type PendingPrompt = {
    title: string
    message: string
    options: { scope: EditScope; label: string }[]
    resolve: (scope: EditScope | null) => void
}

export type PromptEditScope = (options: {
    title: string
    message: string
    options: { scope: EditScope; label: string }[]
}) => Promise<EditScope | null>

/**
 * Promise-based "this occurrence / from now on / all" prompt, same shape as
 * `useConfirmDialog` — `await promptEditScope({...})` resolves the chosen
 * scope, or `null` if dismissed. Render `dialog` once near the root of
 * whichever component calls it.
 */
export function useEditScopeDialog(): { promptEditScope: PromptEditScope; dialog: React.ReactNode } {
    const [pending, setPending] = useState<PendingPrompt | null>(null)

    const promptEditScope = useCallback<PromptEditScope>((options) => {
        return new Promise<EditScope | null>((resolve) => {
            setPending({ ...options, resolve })
        })
    }, [])

    const dialog = pending ? (
        <EditScopeDialog
            title={pending.title}
            message={pending.message}
            options={pending.options}
            onChoose={(scope) => {
                pending.resolve(scope)
                setPending(null)
            }}
            onCancel={() => {
                pending.resolve(null)
                setPending(null)
            }}
        />
    ) : null

    return { promptEditScope, dialog }
}
