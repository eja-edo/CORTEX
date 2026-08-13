import type { TaskPriority } from '../types'

/**
 * Linear-style priority glyph: three ascending bars, filled up to the
 * priority level (low = 1, medium = 2, high = 3), muted bars left dim.
 * Urgent breaks the pattern with a filled square + "!" — it isn't a level
 * on the same bar scale, it's an interrupt.
 */
export function PriorityIcon({ priority, size = 13 }: { priority: TaskPriority | null; size?: number }) {
    if (priority === 'urgent') {
        return (
            <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden focusable="false">
                <rect width="16" height="16" rx="3.5" fill="currentColor" />
                <rect x="7" y="3.5" width="2" height="6" rx="1" fill="var(--bg)" />
                <rect x="7" y="10.5" width="2" height="2" rx="1" fill="var(--bg)" />
            </svg>
        )
    }

    const filled = priority === 'high' ? 3 : priority === 'medium' ? 2 : priority === 'low' ? 1 : 0
    const heights = [4, 7, 10]

    return (
        <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden focusable="false">
            {heights.map((h, i) => (
                <rect
                    key={i}
                    x={1 + i * 5}
                    y={13 - h}
                    width="3"
                    height={h}
                    rx="1"
                    fill="currentColor"
                    opacity={i < filled ? 1 : 0.28}
                />
            ))}
        </svg>
    )
}
