import type { EditScope } from '../types'

/**
 * "Don't ask again" for the this-occurrence-or-all prompt (`useEditScopeDialog`).
 * Every current call site (schedule field edits, checklist create/update/delete)
 * offers only `this_only`/`all` — see each one's own `EDIT_SCOPE_OPTIONS` —
 * so one remembered scope is portable across all of them. Settings has a
 * toggle that clears this (`clearRememberedEditScope`), same shape as
 * `noteSettings.ts`'s block-editing flag.
 */
const STORAGE_KEY = 'cortex_edit_scope_remembered'

export function getRememberedEditScope(): EditScope | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { scope?: EditScope }
    return parsed.scope === 'this_only' || parsed.scope === 'all' ? parsed.scope : null
  } catch {
    return null
  }
}

export function setRememberedEditScope(scope: EditScope): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ scope }))
  } catch {
    // localStorage unavailable
  }
}

export function clearRememberedEditScope(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // localStorage unavailable
  }
}
