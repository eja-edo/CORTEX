import { useEffect, useRef, useState } from 'react'
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
    /** `remember`: the "đừng hỏi lại" checkbox was checked when this option
     * was picked — the caller (`useEditScopeDialog`) persists the choice and
     * skips this dialog entirely next time. Settings has a toggle to turn
     * asking back on. */
    onChoose: (scope: EditScope, remember: boolean) => void
    onCancel: () => void
}) {
    const dialogRef = useRef<HTMLDivElement>(null)
    const firstOptionRef = useRef<HTMLButtonElement>(null)
    const [remember, setRemember] = useState(false)

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
                    <label className="edit-scope-dialog-remember">
                        <input
                            type="checkbox"
                            checked={remember}
                            onChange={(e) => setRemember(e.target.checked)}
                        />
                        <span>Không hỏi lại lần sau — luôn dùng lựa chọn này (đổi lại trong Cài đặt)</span>
                    </label>
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
                            onClick={() => onChoose(opt.scope, remember)}
                        >
                            {opt.label}
                        </button>
                    ))}
                </div>
            </div>
        </div>
    )
}
