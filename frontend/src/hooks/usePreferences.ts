import { useCallback, useState } from 'react'
import type { ChannelLinkCode, ReasonPreference, UserChannel, UserPreferencesResponse } from '../types'
import {
  createChannelLinkCode,
  deleteUserChannel,
  getUserPreferences,
  listReasonPreferences,
  listUserChannels,
  updateQuietHours,
  updateReasonPreference,
  updateUserChannel,
} from '../services/api'

export function usePreferences() {
  const [quietHours, setQuietHours] = useState<UserPreferencesResponse | null>(null)
  const [reasons, setReasons] = useState<ReasonPreference[]>([])
  const [channels, setChannels] = useState<UserChannel[]>([])
  const [isLoading, setIsLoading] = useState(false)

  const fetchPreferences = useCallback(async () => {
    setIsLoading(true)
    try {
      // `allSettled`, not `all`: the three calls are independent, and the
      // channels endpoint is the newest of them. One of them failing
      // should cost the user that one section, not the whole settings
      // page — which is what `all` would do by rejecting on the first
      // failure and leaving quiet hours unset too.
      const [prefs, reasonList, channelList] = await Promise.allSettled([
        getUserPreferences(),
        listReasonPreferences(),
        listUserChannels(),
      ])
      if (prefs.status === 'fulfilled') setQuietHours(prefs.value)
      if (reasonList.status === 'fulfilled') setReasons(reasonList.value)
      if (channelList.status === 'fulfilled') setChannels(channelList.value)

      for (const result of [prefs, reasonList, channelList]) {
        if (result.status === 'rejected') {
          console.error('Failed to fetch part of preferences:', result.reason)
        }
      }
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

  const createLinkCode = useCallback(async (channel: string): Promise<ChannelLinkCode> => {
    return createChannelLinkCode(channel)
  }, [])

  const updateChannel = useCallback(
    async (channelId: string, updates: { enabled?: boolean; min_level?: string }) => {
      // Same optimistic pattern as the reason toggles, for the same reason:
      // a checkbox that waits on a round trip before moving feels broken.
      const previous = channels
      setChannels(prev =>
        prev.map(c => (c.id === channelId ? { ...c, ...(updates as Partial<UserChannel>) } : c))
      )
      try {
        const updated = await updateUserChannel(channelId, updates)
        setChannels(prev => prev.map(c => (c.id === channelId ? updated : c)))
      } catch (error) {
        console.error('Failed to update channel:', error)
        setChannels(previous)
      }
    },
    [channels]
  )

  const removeChannel = useCallback(async (channelId: string) => {
    // Not optimistic. Unlinking is destructive and needs re-doing the whole
    // code flow to undo, so the row stays until the server confirms.
    try {
      await deleteUserChannel(channelId)
      setChannels(prev => prev.filter(c => c.id !== channelId))
    } catch (error) {
      console.error('Failed to delete channel:', error)
    }
  }, [])

  return {
    quietHours,
    reasons,
    channels,
    isLoading,
    fetchPreferences,
    saveQuietHours,
    toggleReason,
    createLinkCode,
    updateChannel,
    removeChannel,
  }
}
