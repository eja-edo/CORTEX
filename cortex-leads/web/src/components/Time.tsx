import { clock, dateTime, dayMonth, full, when } from './format'

type Style = 'clock' | 'when' | 'dateTime' | 'day'
const RENDER: Record<Style, (iso: string) => string> = { clock, when, dateTime, day: (i) => dayMonth(i) }

/** Every time on screen is one of these: shown short, complete on hover, machine-readable for tests and copy. */
export function Time({ iso, as = 'clock', className }: { iso: string; as?: Style; className?: string }) {
  return <time dateTime={iso} title={full(iso)} className={className}>{RENDER[as](iso)}</time>
}
