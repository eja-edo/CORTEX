import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { NoteItem } from '../components/NoteSidebar'
import type { Workspace } from '../types'
import { requestWithAuth } from '../services/api'
import { plainTextFromMarkdown } from '../utils/noteMarkdown'
import { buildTextPatch, type NotePatchOp } from '../utils/textPatch'

export type ApiNote = {
    id: string
    user_id: string
    workspace_id: string | null
    parent_note_id: string | null
    content: string
    content_type: string
    position: { x: number; y: number }
    size: { width: number; height: number }
    style: { color: string }
    version: number
    is_deleted: boolean
    created_at: string
    updated_at: string
    rendered_html?: string | null
}

export type AppNote = NoteItem & {
    version: number
    updatedAt: string
    parentNoteId: string | null
    title: string
}

type NoteSyncState = {
    baseContent: string
    baseVersion: number
    inFlight: boolean
    queued: boolean
}

export type NoteSummary = {
    id: string
    date: string
    title: string
    parentNoteId: string | null
}

export type ApiNoteSummary = {
    id: string
    user_id: string
    workspace_id: string | null
    parent_note_id: string | null
    title: string
    content_type: string
    position: { x: number; y: number }
    size: { width: number; height: number }
    style: { color: string }
    version: number
    is_deleted: boolean
    created_at: string
    updated_at: string
}

export function noteTitleFromMd(md: string): string {
    const text = plainTextFromMarkdown(md)
    return text.split('\n').find(l => l.trim()) || 'Untitled'
}

function formatNoteDate(isoDateTime: string): string {
    const parsed = new Date(isoDateTime)
    if (Number.isNaN(parsed.getTime())) return 'Unknown date'
    return parsed.toLocaleDateString('vi-VN')
}

function mapApiNoteToAppNote(note: ApiNote): AppNote {
    return {
        id: note.id,
        contentMd: note.content,
        date: formatNoteDate(note.updated_at),
        version: note.version,
        updatedAt: note.updated_at,
        parentNoteId: note.parent_note_id,
        title: noteTitleFromMd(note.content),
    }
}

function mapApiNoteSummaryToAppNote(note: ApiNoteSummary): AppNote {
    return {
        id: note.id,
        contentMd: '',
        date: formatNoteDate(note.updated_at),
        version: note.version,
        updatedAt: note.updated_at,
        parentNoteId: note.parent_note_id,
        title: note.title,
    }
}

export function useNotes(currentWorkspace: Workspace | null, activeNoteId: string | null) {
    const [recentNotes, setRecentNotes] = useState<AppNote[]>([])
    const recentNotesRef = useRef<AppNote[]>([])
    const noteSyncTimersRef = useRef<Record<string, number>>({})
    const noteSyncStatesRef = useRef<Record<string, NoteSyncState>>({})
    // FIX: Track which note id each pending timer belongs to, to cancel stale saves on switch
    const noteLoadInFlightRef = useRef<Set<string>>(new Set())
    // FIX: Track the activeNoteId in a ref so persist callbacks can check if they're still relevant
    const activeNoteIdRef = useRef<string | null>(activeNoteId)

    const [workspaceDraggingNoteId, setWorkspaceDraggingNoteId] = useState<string | null>(null)
    const [workspaceDropTargetParentId, setWorkspaceDropTargetParentId] = useState<string | null>(null)

    useEffect(() => {
        recentNotesRef.current = recentNotes
    }, [recentNotes])

    // FIX: Keep activeNoteIdRef in sync
    useEffect(() => {
        activeNoteIdRef.current = activeNoteId
    }, [activeNoteId])

    const handleNoteChange = useCallback((id: string, contentMd: string) => {
        setRecentNotes((prev) => prev.map((n) => (n.id === id ? { ...n, contentMd } : n)))
        scheduleNotePersist(id)
    }, [])

    const noteSummaries = useMemo(
        () => recentNotes.map((note) => ({
            id: note.id,
            date: note.date,
            title: note.title || noteTitleFromMd(note.contentMd),
            parentNoteId: note.parentNoteId ?? null,
        })),
        [recentNotes],
    )

    const workspaceNotesByParent = useMemo(() => {
        const byParent = new Map<string | null, NoteSummary[]>()
        for (const note of noteSummaries) {
            const parentId = note.parentNoteId ?? null
            const bucket = byParent.get(parentId)
            if (bucket) bucket.push(note)
            else byParent.set(parentId, [note])
        }
        return byParent
    }, [noteSummaries])

    const workspaceRootNotes = useMemo(() => {
        const existingIds = new Set(noteSummaries.map((note) => note.id))
        return noteSummaries.filter((note) => note.parentNoteId == null || !existingIds.has(note.parentNoteId))
    }, [noteSummaries])

    const activeWorkspaceNote = useMemo(
        () => recentNotes.find((note) => note.id === activeNoteId) ?? null,
        [recentNotes, activeNoteId],
    )

    const canMoveWorkspaceNote = useCallback((sourceId: string, targetParentId: string | null): boolean => {
        if (sourceId === targetParentId) return false

        const childrenByParent = new Map<string | null, string[]>()
        for (const note of recentNotesRef.current) {
            const parentId = note.parentNoteId ?? null
            const bucket = childrenByParent.get(parentId)
            if (bucket) bucket.push(note.id)
            else childrenByParent.set(parentId, [note.id])
        }

        if (targetParentId === null) return true

        const stack = [sourceId]
        const visited = new Set<string>()
        while (stack.length > 0) {
            const currentId = stack.pop()
            if (!currentId || visited.has(currentId)) continue
            if (currentId === targetParentId) return false
            visited.add(currentId)
            stack.push(...(childrenByParent.get(currentId) ?? []))
        }

        return true
    }, [])

    const handleWorkspaceSidebarDrop = useCallback(async (targetParentId: string | null): Promise<void> => {
        if (!workspaceDraggingNoteId) return
        if (!canMoveWorkspaceNote(workspaceDraggingNoteId, targetParentId)) return
        await handleMoveNote(workspaceDraggingNoteId, targetParentId)
    }, [workspaceDraggingNoteId, canMoveWorkspaceNote])

    const collectDescendantIds = useCallback((rootNoteId: string): string[] => {
        const notesByParent = new Map<string | null, AppNote[]>()
        for (const note of recentNotesRef.current) {
            const parentKey = note.parentNoteId ?? null
            const bucket = notesByParent.get(parentKey)
            if (bucket) {
                bucket.push(note)
            } else {
                notesByParent.set(parentKey, [note])
            }
        }

        const collected: string[] = []
        const stack = [rootNoteId]
        const seen = new Set<string>()
        while (stack.length) {
            const currentId = stack.pop()
            if (!currentId || seen.has(currentId)) continue
            seen.add(currentId)
            collected.push(currentId)
            const children = notesByParent.get(currentId) ?? []
            for (const child of children) stack.push(child.id)
        }
        return collected
    }, [])

    const clearNotes = useCallback(() => {
        setRecentNotes([])
        noteSyncStatesRef.current = {}
        noteLoadInFlightRef.current = new Set()
    }, [])

    async function fetchNotes(): Promise<void> {
        if (!currentWorkspace) return
        try {
            const data = await requestWithAuth<ApiNoteSummary[]>(`/notes/workspaces/${currentWorkspace.id}`)
            const mappedNotes = data.map(mapApiNoteSummaryToAppNote)
            setRecentNotes(mappedNotes)
            // FIX: Reset sync states when fetching fresh note list — prevents stale
            // sync state from a previous workspace or old note list
            noteSyncStatesRef.current = {}
            noteLoadInFlightRef.current = new Set()
        } catch (error) {
            console.error('Cannot load notes:', error)
        }
    }

    async function fetchFullNote(noteId: string): Promise<void> {
        try {
            const data = await requestWithAuth<ApiNote>(`/notes/${noteId}`)
            const mapped = mapApiNoteToAppNote(data)

            setRecentNotes((prev) => prev.map((n) => (n.id === noteId ? mapped : n)))
            noteSyncStatesRef.current[noteId] = {
                baseContent: mapped.contentMd,
                baseVersion: mapped.version,
                inFlight: false,
                queued: false,
            }
        } catch (error) {
            console.error('Cannot load note:', error)
        }
    }

    useEffect(() => {
        if (!activeNoteId) return

        // Flush any pending persist for the previously active note (Bug 3)
        const prevActiveId = activeNoteIdRef.current
        if (prevActiveId && prevActiveId !== activeNoteId) {
            const prevTimerId = noteSyncTimersRef.current[prevActiveId]
            if (prevTimerId) {
                window.clearTimeout(prevTimerId)
                delete noteSyncTimersRef.current[prevActiveId]
                void persistNoteContent(prevActiveId)
            }
        }

        if (noteLoadInFlightRef.current.has(activeNoteId)) return

        noteLoadInFlightRef.current.add(activeNoteId)
        void fetchFullNote(activeNoteId).finally(() => {
            noteLoadInFlightRef.current.delete(activeNoteId)
        })
    }, [activeNoteId])

    async function persistNoteContent(noteId: string): Promise<void> {
        const target = recentNotesRef.current.find((note) => note.id === noteId)
        if (!target) return

        const syncState = noteSyncStatesRef.current[noteId]
        // If the full content has not been loaded yet, skip persist.
        if (!syncState) return

        if (syncState.inFlight) {
            syncState.queued = true
            return
        }

        const nextContent = target.contentMd
        if (nextContent === syncState.baseContent) {
            return
        }

        const patch = buildTextPatch(syncState.baseContent, nextContent)
        if (!patch.length) {
            syncState.baseContent = nextContent
            return
        }

        const requestVersion = syncState.baseVersion
        const requestContent = nextContent
        syncState.inFlight = true
        syncState.queued = false

        try {
            const payload: { version: number; patch: NotePatchOp[] } = { version: requestVersion, patch }
            const updated = await requestWithAuth<ApiNote>(`/notes/${noteId}/patch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            })
            const mapped = mapApiNoteToAppNote(updated)
            syncState.baseContent = mapped.contentMd
            syncState.baseVersion = mapped.version
            syncState.inFlight = false

            setRecentNotes((prev) =>
                prev.map((note) => {
                    if (note.id !== noteId) return note

                    if (note.contentMd !== requestContent) {
                        return {
                            ...note,
                            version: mapped.version,
                            updatedAt: mapped.updatedAt,
                            date: mapped.date,
                        }
                    }

                    return { ...note, ...mapped }
                }),
            )

            const latest = recentNotesRef.current.find((note) => note.id === noteId)
            if (latest && latest.contentMd !== syncState.baseContent) {
                syncState.queued = true
            }
            if (syncState.queued) {
                syncState.queued = false
                window.setTimeout(() => {
                    void persistNoteContent(noteId)
                }, 0)
            }
        } catch (error) {
            syncState.inFlight = false
            if (error instanceof Error && 'status' in error && (error as { status: number }).status === 409) {
                console.error('Note update conflict. Reloading latest version.')
                delete noteSyncStatesRef.current[noteId]
                await fetchFullNote(noteId)
                return
            }
            console.error('Cannot save note:', error)
        }
    }

    function scheduleNotePersist(noteId: string): void {
        const existing = noteSyncTimersRef.current[noteId]
        if (existing) window.clearTimeout(existing)
        noteSyncTimersRef.current[noteId] = window.setTimeout(() => {
            void persistNoteContent(noteId)
            delete noteSyncTimersRef.current[noteId]
        }, 280)
    }

    async function handleCreateNote(parentNoteId?: string): Promise<AppNote | null> {
        if (!currentWorkspace) {
            console.error('Please select a workspace first')
            return null
        }

        if (currentWorkspace.my_role === 'viewer') {
            console.error('You do not have permission to create notes in this workspace')
            return null
        }

        try {
            const created = await requestWithAuth<ApiNote>('/notes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    workspace_id: currentWorkspace.id,
                    content: '# New note',
                    content_type: 'markdown',
                    parent_note_id: parentNoteId ?? null,
                    position: { x: 0, y: 0 },
                    size: { width: 200, height: 200 },
                    style: { color: 'yellow' },
                }),
            })
            const mapped = mapApiNoteToAppNote(created)
            setRecentNotes((prev) => [mapped, ...prev])
            noteSyncStatesRef.current[mapped.id] = {
                baseContent: mapped.contentMd,
                baseVersion: mapped.version,
                inFlight: false,
                queued: false,
            }
            return mapped
        } catch (error) {
            console.error('Cannot create note:', error)
            return null
        }
    }

    async function handleDeleteNote(noteId: string): Promise<string[]> {
        try {
            await requestWithAuth<void>(`/notes/${noteId}`, { method: 'DELETE' })
            const removedIds = collectDescendantIds(noteId)
            const removedSet = new Set(removedIds)
            setRecentNotes((prev) => prev.filter((n) => !removedSet.has(n.id)))
            for (const removedId of removedIds) {
                delete noteSyncStatesRef.current[removedId]
                // FIX: Also cancel any pending save timers for deleted notes
                const timer = noteSyncTimersRef.current[removedId]
                if (timer) {
                    window.clearTimeout(timer)
                    delete noteSyncTimersRef.current[removedId]
                }
            }
            return removedIds
        } catch (error) {
            console.error('Cannot delete note:', error)
            return []
        }
    }

    async function handleMoveNote(noteId: string, parentNoteId: string | null): Promise<void> {
        const current = recentNotesRef.current.find((note) => note.id === noteId)
        if (!current) return

        const syncState = noteSyncStatesRef.current[noteId]
        if (syncState?.inFlight) {
            console.error('Note đang được đồng bộ. Vui lòng thử lại sau vài giây.')
            return
        }

        try {
            const updated = await requestWithAuth<ApiNote>(`/notes/${noteId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    version: current.version,
                    parent_note_id: parentNoteId,
                }),
            })

            const mapped = mapApiNoteToAppNote(updated)
            setRecentNotes((prev) => {
                const nextNotes = prev.map((note) => (note.id === noteId ? { ...note, ...mapped } : note))
                recentNotesRef.current = nextNotes
                return nextNotes
            })

            const nextSyncState = noteSyncStatesRef.current[noteId]
            if (nextSyncState) {
                nextSyncState.baseVersion = mapped.version
            }
        } catch (error) {
            if (error instanceof Error && 'status' in error && (error as { status: number }).status === 409) {
                console.error('Note update conflict. Reloading latest version.')
                delete noteSyncStatesRef.current[noteId]
                await fetchFullNote(noteId)
                return
            }
            console.error('Cannot move note:', error)
        }
    }

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            Object.values(noteSyncTimersRef.current).forEach((timerId) => window.clearTimeout(timerId))
            noteSyncTimersRef.current = {}
        }
    }, [])

    return {
        recentNotes,
        setRecentNotes,
        noteSummaries,
        workspaceNotesByParent,
        workspaceRootNotes,
        activeWorkspaceNote,
        handleNoteChange,
        fetchNotes,
        fetchFullNote,
        handleCreateNote,
        handleDeleteNote,
        handleMoveNote,
        collectDescendantIds,
        clearNotes,
        workspaceDraggingNoteId,
        setWorkspaceDraggingNoteId,
        workspaceDropTargetParentId,
        setWorkspaceDropTargetParentId,
        canMoveWorkspaceNote,
        handleWorkspaceSidebarDrop,
    }
}