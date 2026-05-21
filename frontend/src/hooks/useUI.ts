import { useCallback, useState } from 'react'
import type { AppNotification } from '../components/NotificationBell'
import { getStoredTheme, applyThemeToDocument } from '../utils/theme'
import type { AppTheme } from '../utils/theme'

export function useUI() {
    const [isWorkspaceSidebarCollapsed, setIsWorkspaceSidebarCollapsed] = useState<boolean>(false)
    const [isCreateEventOpen, setIsCreateEventOpen] = useState<boolean>(false)
    const [isSearchOpen, setIsSearchOpen] = useState(false)
    const [isAskAIOpen, setIsAskAIOpen] = useState(false)
    const [createEventInitialTimes, setCreateEventInitialTimes] = useState<{ startDate: string; endDate: string } | null>(null)
    const [sectionNoteOpen, setSectionNoteOpen] = useState(true)
    const [sectionRecordOpen, setSectionRecordOpen] = useState(true)
    const [notifications, setNotifications] = useState<AppNotification[]>([])
    const [syncToastMessage, setSyncToastMessage] = useState<string>('')
    const [theme, setThemeState] = useState<AppTheme>(getStoredTheme)

    const setTheme = useCallback((newTheme: AppTheme) => {
        setThemeState(newTheme)
        applyThemeToDocument(newTheme)
        window.localStorage.setItem('cortex_theme', newTheme)
    }, [])

    const showSyncToast = useCallback((message: string): void => {
        setSyncToastMessage(message)
        const newNotif: AppNotification = {
            id: Date.now().toString(),
            kind: 'sync',
            title: 'Calendar synced',
            body: message,
            timestamp: new Date(),
            read: false,
        }
        setNotifications((prev) => [newNotif, ...prev].slice(0, 50))
        window.setTimeout(() => {
            setSyncToastMessage('')
        }, 5000)
    }, [])

    const openCreateEvent = useCallback(() => {
        setCreateEventInitialTimes(null)
        setIsCreateEventOpen(true)
    }, [])

    const openCreateEventWithTimes = useCallback((startDate: Date, endDate: Date) => {
        const toLocalInputDateTime = (value: Date): string => {
            const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
            return local.toISOString().slice(0, 16)
        }
        setCreateEventInitialTimes({
            startDate: toLocalInputDateTime(startDate),
            endDate: toLocalInputDateTime(endDate),
        })
        setIsCreateEventOpen(true)
    }, [])

    const closeCreateEvent = useCallback(() => {
        setIsCreateEventOpen(false)
        setCreateEventInitialTimes(null)
    }, [])

    return {
        isWorkspaceSidebarCollapsed,
        setIsWorkspaceSidebarCollapsed,
        isCreateEventOpen,
        isSearchOpen,
        setIsSearchOpen,
        isAskAIOpen,
        setIsAskAIOpen,
        createEventInitialTimes,
        sectionNoteOpen,
        setSectionNoteOpen,
        sectionRecordOpen,
        setSectionRecordOpen,
        notifications,
        setNotifications,
        syncToastMessage,
        setSyncToastMessage,
        theme,
        setTheme,
        showSyncToast,
        openCreateEvent,
        openCreateEventWithTimes,
        closeCreateEvent,
    }
}
