import { useCallback, useEffect, useRef, useState } from 'react'
import type { CalendarItem } from '../types'
import { requestWithAuth } from '../services/api'

function toIsoDateTime(localDateTime: string): string {
    return new Date(localDateTime).toISOString()
}

/**
 * The calendar's feed (Milestone 2.6).
 *
 * One request, one shape, both tables. The component that renders this never
 * learns that schedules and tasks live apart — it reads `render_as` and draws
 * accordingly.
 */
export function useCalendarItems(startDate: string, endDate: string) {
    const [items, setItems] = useState<CalendarItem[]>([])
    const [isLoading, setIsLoading] = useState(false)
    // Bumped on every call; a response only gets applied if it's still the
    // most recent one requested. Without this, two in-flight requests for
    // different ranges (e.g. fired back-to-back while clicking Next/Prev)
    // can resolve out of order — the slower, older one landing last would
    // silently overwrite the grid with the wrong range's events, which is
    // what "events hiện lúc mất" actually was.
    const requestIdRef = useRef(0)

    const fetchItems = useCallback(async (): Promise<void> => {
        const requestId = ++requestIdRef.current
        setIsLoading(true)
        try {
            const data = await requestWithAuth<CalendarItem[]>(
                `/calendar/items?from=${encodeURIComponent(toIsoDateTime(startDate))}`
                + `&to=${encodeURIComponent(toIsoDateTime(endDate))}`,
            )
            if (requestId === requestIdRef.current) setItems(data)
        } catch (error) {
            console.error('Cannot load calendar items:', error)
        } finally {
            if (requestId === requestIdRef.current) setIsLoading(false)
        }
    }, [startDate, endDate])

    useEffect(() => {
        void fetchItems()
    }, [fetchItems])

    return { items, isLoading, fetchItems }
}
