import { useEffect } from 'react'

const EDITABLE_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT'])

function isEditingText(): boolean {
    const el = document.activeElement as HTMLElement | null
    if (!el) return false
    if (EDITABLE_TAGS.has(el.tagName)) return true
    return el.isContentEditable
}

/**
 * Closes a modal/overlay on Escape. Extracted because the same
 * `useEffect(() => { document.addEventListener('keydown', ...) }, [])` block
 * was about to get copy-pasted into seven components; three others already
 * had their own hand-written copy (WorkspaceSearch, AskAI, App.tsx's mobile
 * nav drawer) — a single hook keeps the behaviour in one place.
 *
 * Skips while a text field inside the modal has focus. Several of these
 * modals already give Escape a field-level meaning — TaskDetailModal's title
 * input reverts unsaved edits, for instance — without calling
 * `stopPropagation()`. Without this guard, one Escape press would revert the
 * field *and* blow away the whole modal in the same keystroke. Once focus
 * leaves the field, Escape closes the modal as expected — the same two-step
 * behaviour most editors use.
 */
export function useEscapeToClose(onClose: () => void, enabled = true) {
    useEffect(() => {
        if (!enabled) return
        const handler = (e: KeyboardEvent) => {
            if (e.key !== 'Escape') return
            if (isEditingText()) return
            onClose()
        }
        document.addEventListener('keydown', handler)
        return () => document.removeEventListener('keydown', handler)
    }, [onClose, enabled])
}
