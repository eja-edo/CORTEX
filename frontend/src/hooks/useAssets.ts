import { useCallback, useState } from 'react'
import type { Project } from '../types'
import { requestWithAuth } from '../services/api'

export type SidebarAsset = {
    id: string
    title: string | null
    status: string
    type: string
    created_at: string
}

export function useAssets(currentProject: Project | null) {
    const [sidebarAssets, setSidebarAssets] = useState<SidebarAsset[]>([])
    const [sidebarAssetsLoading, setSidebarAssetsLoading] = useState(false)

    const loadSidebarAssets = useCallback(async (): Promise<void> => {
        if (!currentProject) return
        setSidebarAssetsLoading(true)
        try {
            const assets = await requestWithAuth<Array<{
                id: string
                title: string | null
                status: string
                type: string
                created_at: string
            }>>(`/assets/projects/${currentProject.id}`)
            setSidebarAssets(assets)
        } catch (error) {
            console.error('Failed to load sidebar assets:', error)
        } finally {
            setSidebarAssetsLoading(false)
        }
    }, [currentProject])

    const deleteAsset = useCallback(async (assetId: string): Promise<boolean> => {
        try {
            await requestWithAuth<void>(`/assets/${assetId}`, { method: 'DELETE' })
            setSidebarAssets(prev => prev.filter(a => a.id !== assetId))
            return true
        } catch (error) {
            console.error('Cannot delete asset:', error)
            return false
        }
    }, [])

    return {
        sidebarAssets,
        sidebarAssetsLoading,
        setSidebarAssets,
        loadSidebarAssets,
        deleteAsset,
    }
}
