import { useCallback, useState } from 'react'
import type { ReasonPreference, UserPreferencesResponse } from '../types'
import { getUserPreferences, listReasonPreferences, updateQuietHours, updateReasonPreference } from '../services/api'

export function usePreferences() {
  const [quietHours, setQuietHours] = useState<UserPreferencesResponse | null>(null)
  const [reasons, setReasons] = useState<ReasonPreference[]>([])
  const [isLoading, setIsLoading] = useState(false)

  const fetchPreferences = useCallback(async () => {
    setIsLoading(true)
    try {
      const [prefs, reasonList] = await Promise.all([getUserPreferences(), listReasonPreferences()])
      setQuietHours(prefs)
      setReasons(reasonList)
    } catch (error) {
      console.error('Failed to fetch preferences:', error)
    } finally {
      setIsLoading(false)
    }
  }, [])

  const saveQuietHours = useCallback(async (start: string | null, end: string | null) => {
    const updated = await updateQuietHours(start, end)
    setQuietHours(updated)
    return updated
  }, [])

  const toggleReason = useCallback(async (reasonKey: string, enabled: boolean) => {
    // Optimistic update — the list is small and a toggle failing is rare
    // enough that a flash-then-revert reads better than a spinner per row.
    setReasons(prev => prev.map(r => (r.reason_key === reasonKey ? { ...r, enabled } : r)))
    try {
      const updated = await updateReasonPreference(reasonKey, enabled)
      setReasons(prev => prev.map(r => (r.reason_key === reasonKey ? updated : r)))
    } catch (error) {
      console.error('Failed to update reason preference:', error)
      setReasons(prev => prev.map(r => (r.reason_key === reasonKey ? { ...r, enabled: !enabled } : r)))
    }
  }, [])

  return { quietHours, reasons, isLoading, fetchPreferences, saveQuietHours, toggleReason }
}
