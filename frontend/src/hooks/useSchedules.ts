import { useCallback, useState } from 'react'
import { startOfWeek, endOfWeek } from 'date-fns'
import type { Schedule, ScheduleListResponse, GoogleCalendarStatus } from '../types'
import { requestWithAuth } from '../services/api'

function toLocalInputDateTime(value: Date): string {
    const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
    return local.toISOString().slice(0, 16)
}

function toIsoDateTime(localDateTime: string): string {
    return new Date(localDateTime).toISOString()
}

function getRangeForCurrentWeek(): { startDate: string; endDate: string } {
    const now = new Date()
    const start = startOfWeek(now, { weekStartsOn: 1 })
    const end = endOfWeek(now, { weekStartsOn: 1 })
    start.setHours(0, 0, 0, 0)
    end.setHours(23, 59, 59, 999)
    return { startDate: toLocalInputDateTime(start), endDate: toLocalInputDateTime(end) }
}

export function useSchedules() {
    const weekRange = getRangeForCurrentWeek()
    const [schedules, setSchedules] = useState<Schedule[]>([])
    const [startDate, setStartDate] = useState<string>(weekRange.startDate)
    const [endDate, setEndDate] = useState<string>(weekRange.endDate)
    const [googleCalendarStatus, setGoogleCalendarStatus] = useState<GoogleCalendarStatus | null>(null)

    const fetchSchedules = useCallback(async (): Promise<void> => {
        try {
            const data = await requestWithAuth<ScheduleListResponse>(
                `/schedules?start_date=${encodeURIComponent(toIsoDateTime(startDate))}&end_date=${encodeURIComponent(toIsoDateTime(endDate))}`
            )
            setSchedules(data.items)
        } catch (error) {
            console.error('Cannot load schedules:', error)
        }
    }, [startDate, endDate])

    const fetchGoogleCalendarStatus = useCallback(async (): Promise<void> => {
        try {
            const status = await requestWithAuth<GoogleCalendarStatus>('/google-calendar/status')
            setGoogleCalendarStatus(status)
        } catch (error) {
            setGoogleCalendarStatus(null)
            console.error('Cannot load Google Calendar status:', error)
        }
    }, [])

    const handleConnectGoogleCalendar = useCallback(async (): Promise<void> => {
        try {
            const payload = await requestWithAuth<{ authorization_url: string }>('/google-calendar/connect-url')
            window.location.href = payload.authorization_url
        } catch (error) {
            console.error('Cannot connect Google Calendar:', error)
        }
    }, [])

    const handleDisconnectGoogleCalendar = useCallback(async (): Promise<void> => {
        try {
            await requestWithAuth<{ message: string }>('/google-calendar/disconnect', { method: 'DELETE' })
            setGoogleCalendarStatus({
                connected: false,
                provider: 'GOOGLE',
                calendar_id: null,
                granted_scopes: [],
                last_synced_at: null,
                has_sync_token: false,
                channel_expiration: null,
                last_sync_error: null,
            })
        } catch (error) {
            console.error('Cannot disconnect Google Calendar:', error)
        }
    }, [])

    const handleSyncGoogleCalendarNow = useCallback(async (): Promise<void> => {
        try {
            await requestWithAuth<{ message: string }>('/google-calendar/sync-now', { method: 'POST' })
            await fetchGoogleCalendarStatus()
        } catch (error) {
            console.error('Cannot sync Google Calendar:', error)
        }
    }, [fetchGoogleCalendarStatus])

    const handleStartGoogleCalendarWatch = useCallback(async (): Promise<void> => {
        try {
            await requestWithAuth<{ message: string }>('/google-calendar/watch/start', { method: 'POST' })
            await fetchGoogleCalendarStatus()
        } catch (error) {
            console.error('Cannot start Google Calendar watch:', error)
        }
    }, [fetchGoogleCalendarStatus])

    const handleRenewGoogleCalendarWatch = useCallback(async (): Promise<void> => {
        try {
            await requestWithAuth<{ message: string }>('/google-calendar/watch/renew', { method: 'POST' })
            await fetchGoogleCalendarStatus()
        } catch (error) {
            console.error('Cannot renew Google Calendar watch:', error)
        }
    }, [fetchGoogleCalendarStatus])

    const handleCreateSchedule = useCallback(async (schedule: Omit<Schedule, 'id' | 'user_id' | 'created_at' | 'updated_at' | 'is_completed'>): Promise<void> => {
        try {
            await requestWithAuth<Schedule>('/schedules', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(schedule),
            })
            await fetchSchedules()
        } catch (error) {
            console.error('Cannot create schedule:', error)
        }
    }, [fetchSchedules])

    const handleToggleComplete = useCallback(async (item: Schedule): Promise<void> => {
        try {
            await requestWithAuth<Schedule>(`/schedules/${item.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_completed: !item.is_completed }),
            })
            await fetchSchedules()
        } catch (error) {
            console.error('Cannot update schedule:', error)
        }
    }, [fetchSchedules])

    const handleUpdateSchedule = useCallback(async (item: Schedule, patch: Partial<Schedule>): Promise<boolean> => {
        if (!item.id) return false
        try {
            await requestWithAuth<Schedule>(`/schedules/${item.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(patch),
            })
            await fetchSchedules()
            return true
        } catch (error) {
            console.error('Cannot update schedule:', error)
            return false
        }
    }, [fetchSchedules])

    const handleRemoveSchedule = useCallback(async (scheduleId: string): Promise<void> => {
        try {
            await requestWithAuth<void>(`/schedules/${scheduleId}`, { method: 'DELETE' })
            await fetchSchedules()
        } catch (error) {
            console.error('Cannot delete schedule:', error)
        }
    }, [fetchSchedules])

    return {
        schedules,
        setSchedules,
        startDate,
        endDate,
        setStartDate,
        setEndDate,
        googleCalendarStatus,
        setGoogleCalendarStatus,
        fetchSchedules,
        fetchGoogleCalendarStatus,
        handleConnectGoogleCalendar,
        handleDisconnectGoogleCalendar,
        handleSyncGoogleCalendarNow,
        handleStartGoogleCalendarWatch,
        handleRenewGoogleCalendarWatch,
        handleCreateSchedule,
        handleToggleComplete,
        handleUpdateSchedule,
        handleRemoveSchedule,
    }
}
