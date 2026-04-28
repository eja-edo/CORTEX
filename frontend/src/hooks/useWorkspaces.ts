import { useCallback, useState } from 'react'
import type { Workspace } from '../types'
import { requestWithAuth } from '../services/api'

export function useWorkspaces() {
    const [workspaces, setWorkspaces] = useState<Workspace[]>([])
    const [currentWorkspace, setCurrentWorkspace] = useState<Workspace | null>(null)

    const fetchWorkspaces = useCallback(async (): Promise<void> => {
        try {
            const data = await requestWithAuth<Workspace[]>('/workspaces')
            setWorkspaces(data)
            if (!currentWorkspace && data.length > 0) {
                const personal = data.find(ws => ws.is_personal)
                const defaultWs = personal || data[0]
                setCurrentWorkspace(defaultWs)
            }
        } catch (error) {
            console.error('Cannot load workspaces:', error)
        }
    }, [currentWorkspace])

    const switchWorkspace = useCallback((workspace: Workspace): boolean => {
        if (workspace.id === currentWorkspace?.id) return false
        setCurrentWorkspace(workspace)
        return true
    }, [currentWorkspace])

    const createWorkspace = useCallback(async (name: string): Promise<Workspace | null> => {
        try {
            const created = await requestWithAuth<Workspace>('/workspaces', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name }),
            })
            setWorkspaces(prev => [...prev, created])
            return created
        } catch (error) {
            console.error('Cannot create workspace:', error)
            return null
        }
    }, [])

    const renameWorkspace = useCallback(async (id: string, name: string): Promise<boolean> => {
        try {
            const updated = await requestWithAuth<Workspace>(`/workspaces/${id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name }),
            })
            setWorkspaces(prev => prev.map(ws => ws.id === id ? updated : ws))
            if (currentWorkspace?.id === id) {
                setCurrentWorkspace(updated)
            }
            return true
        } catch (error) {
            console.error('Cannot rename workspace:', error)
            return false
        }
    }, [currentWorkspace])

    const deleteWorkspace = useCallback(async (id: string): Promise<boolean> => {
        try {
            await requestWithAuth<void>(`/workspaces/${id}`, { method: 'DELETE' })
            setWorkspaces(prev => prev.filter(ws => ws.id !== id))
            if (currentWorkspace?.id === id) {
                const remaining = workspaces.filter(ws => ws.id !== id)
                setCurrentWorkspace(remaining[0] ?? null)
            }
            return true
        } catch (error) {
            console.error('Cannot delete workspace:', error)
            return false
        }
    }, [currentWorkspace, workspaces])

    return {
        workspaces,
        currentWorkspace,
        setWorkspaces,
        setCurrentWorkspace,
        fetchWorkspaces,
        switchWorkspace,
        createWorkspace,
        renameWorkspace,
        deleteWorkspace,
    }
}
