import { useCallback, useState } from 'react'
import type { NotificationListResponse, NotificationResponse } from '../types'
import { listNotifications, markNotificationRead, markAllNotificationsRead, deleteNotification, recordAttentionResponse } from '../services/api'
import type { AppNotification, NotificationKind } from '../components/NotificationBell'

function mapApiNotification(apiNotif: NotificationResponse): AppNotification {
   return {
       id: apiNotif.id,
       kind: (apiNotif.type as NotificationKind) || 'system',
       title: apiNotif.title,
       body: apiNotif.body || '',
       timestamp: new Date(apiNotif.created_at),
       read: apiNotif.read_at !== null,
       payload: apiNotif.payload || {},
       content: apiNotif.content || undefined,
       actions: apiNotif.actions || undefined,
       attentionLogId: apiNotif.attention_log_id,
   }
}

export function useNotifications() {
   const [notifications, setNotifications] = useState<AppNotification[]>([])
   const [isLoading, setIsLoading] = useState(false)

   const fetchNotifications = useCallback(async () => {
       setIsLoading(true)
       try {
           const data: NotificationListResponse = await listNotifications(50)
           const mapped = data.items.map(mapApiNotification)
           setNotifications(mapped)
       } catch (error) {
           console.error('Failed to fetch notifications:', error)
       } finally {
           setIsLoading(false)
       }
   }, [])

   const addNotification = useCallback((notif: AppNotification) => {
        setNotifications((prev) => {
            if (prev.some((n) => n.id === notif.id)) return prev
            return [notif, ...prev].slice(0, 50)
        })
    }, [])

   const handleMarkRead = useCallback(async (id: string) => {
       try {
           await markNotificationRead(id)
           setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)))
       } catch (error) {
           console.error('Failed to mark notification as read:', error)
       }
   }, [])

   const handleMarkAllRead = useCallback(async () => {
       try {
           await markAllNotificationsRead()
       } catch (error) {
           console.error('Failed to mark all notifications as read:', error)
       }
       setNotifications((prev) => prev.map((n) => ({ ...n, read: true })))
   }, [])

   const handleDismiss = useCallback(async (id: string) => {
       const dismissed = notifications.find((n) => n.id === id)
       setNotifications((prev) => prev.filter((n) => n.id !== id))
       if (dismissed?.attentionLogId) {
           recordAttentionResponse(dismissed.attentionLogId, 'dismissed')
       }
       try {
           await deleteNotification(id)
       } catch (error) {
           console.error('Failed to delete notification:', error)
       }
   }, [notifications])

   // Feedback Loop (6.9) raw material for the other outcome: the user
   // clicked through instead of dismissing. Fire-and-forget, same as
   // dismiss — never blocks the navigation it's reporting on.
   const handleAccept = useCallback((id: string) => {
       const notif = notifications.find((n) => n.id === id)
       if (notif?.attentionLogId) {
           recordAttentionResponse(notif.attentionLogId, 'accepted')
       }
   }, [notifications])

   return {
       notifications,
       setNotifications,
       isLoading,
       fetchNotifications,
       addNotification,
       handleMarkRead,
       handleMarkAllRead,
       handleDismiss,
       handleAccept,
   }
}
