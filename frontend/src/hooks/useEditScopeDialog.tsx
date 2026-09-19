import { useCallback, useState } from 'react'
import { EditScopeDialog } from '../components/EditScopeDialog'
import type { EditScope } from '../types'
import { getRememberedEditScope, setRememberedEditScope } from '../utils/editScopePreference'

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
 *
 * If the user previously ticked "don't ask again" (see `EditScopeDialog`),
 * this resolves immediately from `editScopePreference` without ever
 * rendering the dialog — as long as the remembered scope is one of the
 * options actually offered this time (every current caller offers exactly
 * `this_only`/`all`, so it always is; the check is just so a future caller
 * with a different option set falls back to asking instead of applying a
 * scope it never offered). Settings has a toggle to clear the preference
 * and start asking again.
 */
export function useEditScopeDialog(): { promptEditScope: PromptEditScope; dialog: React.ReactNode } {
    const [pending, setPending] = useState<PendingPrompt | null>(null)

    const promptEditScope = useCallback<PromptEditScope>((options) => {
        const remembered = getRememberedEditScope()
        if (remembered && options.options.some((opt) => opt.scope === remembered)) {
            return Promise.resolve(remembered)
        }
        return new Promise<EditScope | null>((resolve) => {
            setPending({ ...options, resolve })
        })
    }, [])

    const dialog = pending ? (
        <EditScopeDialog
            title={pending.title}
            message={pending.message}
            options={pending.options}
            onChoose={(scope, remember) => {
                if (remember) setRememberedEditScope(scope)
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
