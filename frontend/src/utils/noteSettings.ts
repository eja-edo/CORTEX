const STORAGE_KEY = 'cortex_block_editing'

export function getBlockEditingEnabled(): boolean {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored !== null) return stored === 'true'
  } catch {
    // localStorage unavailable
  }
  return false
}

export function setBlockEditingEnabled(enabled: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(enabled))
  } catch {
    // localStorage unavailable
  }
}
