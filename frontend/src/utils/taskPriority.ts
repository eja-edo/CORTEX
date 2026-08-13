import type { TaskPriority } from '../types'

export const PRIORITY_LABELS: Record<TaskPriority, string> = {
    low: 'Thấp',
    medium: 'Trung bình',
    high: 'Cao',
    urgent: 'Khẩn cấp',
}

export function priorityLabel(priority: TaskPriority | null): string | null {
    return priority ? PRIORITY_LABELS[priority] : null
}
