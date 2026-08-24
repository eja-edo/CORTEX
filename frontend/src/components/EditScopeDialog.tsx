import { useEffect, useRef } from 'react'
import type { EditScope } from '../types'

/**
 * "Which occurrences?" prompt for editing/completing one occurrence of a
 * recurring schedule or a checklist task tied to one. Same modal shell as
 * `ConfirmDialog`, but three choices instead of yes/no — a bare confirm
 * dialog can't express this without conflating "cancel" with one of the
 * real answers.
 */
export function EditScopeDialog({
    title,
    message,
    options,
    onChoose,
    onCancel,
}: {
    title: string
    message: string
    options: { scope: EditScope; label: string }[]
    onChoose: (scope: EditScope) => void
    onCancel: () => void
}) {
    const dialogRef = useRef<HTMLDivElement>(null)
    const firstOptionRef = useRef<HTMLButtonElement>(null)

    useEffect(() => {
        const previouslyFocused = document.activeElement as HTMLElement | null
        firstOptionRef.current?.focus()

        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.stopPropagation()
                onCancel()
                return
            }
            if (e.key !== 'Tab') return

            const focusables = dialogRef.current?.querySelectorAll<HTMLElement>(
                'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
            )
            if (!focusables || focusables.length === 0) return
            const first = focusables[0]
            const last = focusables[focusables.length - 1]

            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault()
                last.focus()
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault()
                first.focus()
            }
        }

        document.addEventListener('keydown', onKeyDown, true)
        return () => {
            document.removeEventListener('keydown', onKeyDown, true)
            previouslyFocused?.focus?.()
        }
    }, [onCancel])

    return (
        <div className="modal-backdrop" onClick={onCancel}>
            <div
                ref={dialogRef}
                className="modal confirm-dialog"
                onClick={(e) => e.stopPropagation()}
                role="alertdialog"
                aria-modal="true"
                aria-labelledby="edit-scope-dialog-title"
                aria-describedby="edit-scope-dialog-message"
            >
                <div className="modal-header">
                    <div className="modal-title-area">
                        <div className="modal-title" id="edit-scope-dialog-title">{title}</div>
                    </div>
                </div>
                <div className="modal-body">
                    <p className="confirm-dialog-message" id="edit-scope-dialog-message">{message}</p>
                </div>
                <div className="modal-footer">
                    <button type="button" className="btn btn-ghost" onClick={onCancel}>
                        Huỷ
                    </button>
                    {options.map((opt, i) => (
                        <button
                            key={opt.scope}
                            ref={i === 0 ? firstOptionRef : undefined}
                            type="button"
                            className="btn btn-primary"
                            onClick={() => onChoose(opt.scope)}
                        >
                            {opt.label}
                        </button>
                    ))}
                </div>
            </div>
        </div>
    )
}
