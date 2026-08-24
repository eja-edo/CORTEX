import { useState } from 'react'
import { Plus } from 'lucide-react'
import { useEventChecklist } from '../hooks/useEventChecklist'
import type { PromptEditScope } from '../hooks/useEditScopeDialog'
import { TaskChecklistRow } from './TaskChecklistRow'
import { SubtaskCreatePanel } from './SubtaskCreatePanel'

/**
 * The checklist inside an event (Milestone 2.6).
 *
 * Reads `tasks WHERE related_event_id = eventId` and renders them with
 * `TaskChecklistRow` — the same row used on the Tasks page and "Hôm nay",
 * so a task linked to an event has exactly the same fields (priority
 * dropdown, due date, full detail view) as one that isn't. The link back
 * to the event is just `related_event_id`, untouched by any of these
 * actions — nothing here ever clears or reassigns it.
 *
 * The event's description is untouched prose — no checklist text is ever
 * written into it, and none is ever parsed out of it.
 *
 *   type a line + Enter  →  task.create (related_event_id = eventId,
 *                           due_date defaults to the event's end time)
 *   tick the box         →  task.complete
 *   delete the line      →  task.delete
 *   click the title      →  full task detail modal (task.update)
 */
export function EventChecklist({
    eventId,
    eventEndTime,
    occurrenceStartTime,
    isRecurring,
    promptEditScope,
}: {
    eventId: string | null
    eventEndTime?: string | null
    // Only meaningful when `isRecurring` — disambiguates which occurrence's
    // checklist state this is (see `useEventChecklist`'s docstring).
    occurrenceStartTime?: string | null
    isRecurring?: boolean
    promptEditScope: PromptEditScope
}) {
    const { tasks, isLoading, fetchTasks, addTask, toggleTask, removeTask, updateTask } =
        useEventChecklist(eventId, eventEndTime ?? null, occurrenceStartTime ?? null, Boolean(isRecurring), promptEditScope)
    const [addingItem, setAddingItem] = useState(false)

    if (!eventId) return null

    const doneCount = tasks.filter((t) => t.status === 'done').length

    return (
        <div className="event-checklist">
            <div className="event-checklist-header">
                <span className="modal-description-label">Checklist</span>
                {tasks.length > 0 && (
                    <span className="event-checklist-count">
                        {doneCount}/{tasks.length}
                    </span>
                )}
            </div>

            <ul className="event-checklist-list">
                {tasks.map((task) => (
                    <TaskChecklistRow
                        key={task.id}
                        task={task}
                        onToggle={() => void toggleTask(task)}
                        onRename={(title) => updateTask(task.id, { title })}
                        onSetDueDate={(date) => updateTask(task.id, { due_date: date })}
                        onUpdateDetail={(patch) => updateTask(task.id, patch)}
                        onRemove={() => void removeTask(task.id)}
                        onDetailClose={() => void fetchTasks()}
                    />
                ))}
            </ul>

            {addingItem ? (
                <SubtaskCreatePanel
                    onCancel={() => setAddingItem(false)}
                    onCreate={async (input) => {
                        await addTask(input)
                        setAddingItem(false)
                    }}
                />
            ) : (
                <button
                    type="button"
                    className="task-detail-modal-checklist-add"
                    onClick={() => setAddingItem(true)}
                >
                    <Plus size={13} />
                    <span>Add a checklist item…</span>
                </button>
            )}

            {isLoading && tasks.length === 0 && (
                <div className="event-checklist-empty">Loading…</div>
            )}
        </div>
    )
}
