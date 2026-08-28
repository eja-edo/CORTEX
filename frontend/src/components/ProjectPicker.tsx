import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Plus } from 'lucide-react'
import type { Project } from '../types'
import { strings } from '../i18n/strings'

/**
 * The in-place project dropdown — DESIGN 10.1.
 *
 * Fixing an assignment **where you can see it is wrong** beats navigating
 * to a management page, finding the task again, fixing it, and coming back.
 * It also removes a nav entry: there is no "manage projects" screen, and
 * that absence is deliberate.
 *
 * Every change here is a labelled correction feeding DESIGN 4.4 — the
 * derivation rule's quality is measured by how often people reach for this.
 * Above 20% the rule is wrong and gets fixed; the answer is never "add more
 * UI here".
 */
export function ProjectPicker({
    projects,
    value,
    onChange,
    onCreate,
    disabled,
    label,
}: {
    projects: Project[]
    value: string | null
    onChange: (projectId: string) => void
    onCreate?: (name: string) => void
    disabled?: boolean
    label?: string
}) {
    const [isOpen, setIsOpen] = useState(false)
    const containerRef = useRef<HTMLDivElement>(null)
    const current = projects.find((p) => p.id === value) ?? null

    useEffect(() => {
        if (!isOpen) return
        const onDocumentPointerDown = (event: MouseEvent) => {
            if (!containerRef.current?.contains(event.target as Node)) setIsOpen(false)
        }
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') setIsOpen(false)
        }
        document.addEventListener('mousedown', onDocumentPointerDown)
        document.addEventListener('keydown', onKeyDown)
        return () => {
            document.removeEventListener('mousedown', onDocumentPointerDown)
            document.removeEventListener('keydown', onKeyDown)
        }
    }, [isOpen])

    const handlePick = (projectId: string) => {
        setIsOpen(false)
        if (projectId !== value) onChange(projectId)
    }

    const handleCreate = () => {
        setIsOpen(false)
        const name = window.prompt(strings.projects.newProjectPrompt)?.trim()
        if (name) onCreate?.(name)
    }

    return (
        <div className="project-picker" ref={containerRef}>
            <button
                type="button"
                className="project-picker-trigger"
                onClick={() => setIsOpen((open) => !open)}
                disabled={disabled}
                aria-haspopup="listbox"
                aria-expanded={isOpen}
                aria-label={label ?? strings.projects.moveLabel}
            >
                <span className="project-picker-name">
                    {current?.name ?? strings.projects.personalFallback}
                </span>
                <ChevronDown size={13} aria-hidden />
            </button>

            {isOpen && (
                <ul className="project-picker-menu" role="listbox">
                    {projects.map((project) => (
                        <li key={project.id}>
                            <button
                                type="button"
                                role="option"
                                aria-selected={project.id === value}
                                className={`project-picker-option ${project.id === value ? 'is-current' : ''}`}
                                onClick={() => handlePick(project.id)}
                            >
                                <span className="project-picker-option-name">{project.name}</span>
                                {project.open_task_count > 0 && (
                                    <span className="project-picker-count">
                                        {project.open_task_count}
                                    </span>
                                )}
                            </button>
                        </li>
                    ))}
                    {onCreate && (
                        <li>
                            <button
                                type="button"
                                className="project-picker-option project-picker-create"
                                onClick={handleCreate}
                            >
                                <Plus size={13} aria-hidden />
                                <span>{strings.projects.newProject}</span>
                            </button>
                        </li>
                    )}
                </ul>
            )}
        </div>
    )
}
