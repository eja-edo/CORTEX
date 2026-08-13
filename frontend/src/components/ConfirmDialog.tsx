/**
 * A generic yes/no confirmation modal — same `.modal-backdrop`/`.modal`
 * shell every other modal in the app uses, sized down to a single question.
 * Backdrop click and the cancel button both count as "no": the caller only
 * hears about an explicit choice, dismissal is never ambiguous with confirm.
 */
export function ConfirmDialog({
    title,
    message,
    confirmLabel,
    cancelLabel,
    onConfirm,
    onCancel,
}: {
    title: string
    message: string
    confirmLabel: string
    cancelLabel: string
    onConfirm: () => void
    onCancel: () => void
}) {
    return (
        <div className="modal-backdrop" onClick={onCancel}>
            <div className="modal confirm-dialog" onClick={(e) => e.stopPropagation()} role="alertdialog" aria-modal="true">
                <div className="modal-header">
                    <div className="modal-title-area">
                        <div className="modal-title">{title}</div>
                    </div>
                </div>
                <div className="modal-body">
                    <p className="confirm-dialog-message">{message}</p>
                </div>
                <div className="modal-footer">
                    <button type="button" className="btn btn-ghost" onClick={onCancel}>
                        {cancelLabel}
                    </button>
                    <button type="button" className="btn btn-primary" onClick={onConfirm} autoFocus>
                        {confirmLabel}
                    </button>
                </div>
            </div>
        </div>
    )
}
