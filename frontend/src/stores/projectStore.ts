import { create } from 'zustand'
import type { Project } from '../types'
import { createProject, listProjects, moveTaskToProject, updateProject } from '../services/api'
import { useTaskStore } from './taskStore'

const OPEN_PROJECT_KEY = 'cortex_open_project'

/**
 * The projects the user is in, plus which one is currently open.
 *
 * **"Open project" is a UI scope, not a hidden context.** It decides what
 * the "Việc" screen lists and what a newly typed task defaults to — and
 * nothing else. In particular it never reaches the agent: DESIGN 9.2
 * settles that there is no session-level current project, because an
 * implicit one produces the classic silent failure where the user says
 * "mark the spec task done" and the agent quietly acts on the wrong
 * project. Every tool call names its project explicitly instead.
 *
 * It deliberately does **not** scope "Hôm nay" (DESIGN 10.2): if that
 * screen filtered by the open project, the user would have to walk through
 * every project to find out what to do — which is exactly the work Cortex
 * exists to remove. Ranking only means something when it sees everything.
 */
interface ProjectStore {
    projects: Project[]
    isLoading: boolean
    hasLoaded: boolean
    error: string | null
    /** `null` means "chưa chọn" — the Việc screen then falls back to the
     * first project rather than showing an empty page with no explanation. */
    openProjectId: string | null

    fetchAll: () => Promise<void>
    setOpenProject: (projectId: string | null) => void
    create: (name: string) => Promise<Project>
    rename: (projectId: string, name: string) => Promise<void>
    /** Move a task and keep both caches honest: the task's own row changes
     * project, and both projects' open counts shift. Refetching projects
     * afterwards is cheaper than recomputing the counts here and getting
     * them subtly wrong — a count that disagrees with the list under it is
     * worse than a count that arrives 200ms late. */
    moveTask: (taskId: string, projectId: string) => Promise<void>
}

function readStoredOpenProject(): string | null {
    try {
        return window.localStorage.getItem(OPEN_PROJECT_KEY)
    } catch {
        // Private windows and blocked site data both throw here. A missing
        // preference is not an error state — the screen picks a project.
        return null
    }
}

export const useProjectStore = create<ProjectStore>((set, get) => ({
    projects: [],
    isLoading: false,
    hasLoaded: false,
    error: null,
    openProjectId: readStoredOpenProject(),

    fetchAll: async () => {
        set({ isLoading: true, error: null })
        try {
            const projects = await listProjects()
            // An open project that no longer exists (closed elsewhere, or
            // stale localStorage from another account) must not leave the
            // switcher pointing at nothing.
            const openProjectId = get().openProjectId
            const stillThere = projects.some((p) => p.id === openProjectId)
            set({
                projects,
                isLoading: false,
                hasLoaded: true,
                openProjectId: stillThere ? openProjectId : (projects[0]?.id ?? null),
            })
        } catch (err) {
            set({ error: (err as Error).message, isLoading: false, hasLoaded: true })
        }
    },

    setOpenProject: (projectId) => {
        set({ openProjectId: projectId })
        try {
            if (projectId) window.localStorage.setItem(OPEN_PROJECT_KEY, projectId)
            else window.localStorage.removeItem(OPEN_PROJECT_KEY)
        } catch {
            // Remembering the choice is a convenience; failing to remember
            // it must not break switching projects in this session.
        }
    },

    create: async (name) => {
        const project = await createProject(name)
        set((state) => ({ projects: [...state.projects, project] }))
        get().setOpenProject(project.id)
        return project
    },

    rename: async (projectId, name) => {
        const updated = await updateProject(projectId, { name })
        set((state) => ({
            projects: state.projects.map((p) => (p.id === projectId ? updated : p)),
        }))
    },

    moveTask: async (taskId, projectId) => {
        const updated = await moveTaskToProject(taskId, projectId)
        useTaskStore.setState((state) => ({
            tasks: state.tasks.map((task) => (task.id === taskId ? updated : task)),
        }))
        await get().fetchAll()
    },
}))
