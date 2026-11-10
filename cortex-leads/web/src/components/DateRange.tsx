import clsx from 'clsx'
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { businessDay, dayFull } from './format'
import { Button } from './ui'

export interface Range { from?: string; to?: string; preset?: PresetId }
export type PresetId = 'today' | 'yesterday' | '7d' | '30d' | 'month' | 'last_month' | 'custom'

const PRESETS: { id: Exclude<PresetId, 'custom'>; label: string }[] = [
  { id: 'today', label: 'Hôm nay' }, { id: 'yesterday', label: 'Hôm qua' }, { id: '7d', label: '7 ngày qua' },
  { id: '30d', label: '30 ngày qua' }, { id: 'month', label: 'Tháng này' }, { id: 'last_month', label: 'Tháng trước' },
]
const WEEK = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']
const p2 = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getUTCFullYear()}-${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())}`
const parse = (s: string) => { const [y, m, d] = s.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d)) }
const shift = (s: string, days: number) => { const d = parse(s); d.setUTCDate(d.getUTCDate() + days); return ymd(d) }
const firstOf = (s: string) => `${s.slice(0, 8)}01`
const addMonths = (s: string, n: number) => { const d = parse(firstOf(s)); d.setUTCMonth(d.getUTCMonth() + n); return ymd(d) }

/** Days are the business's calendar days (DESIGN §5.13): "today" comes from the session's time zone, never the browser's. */
export function presetRange(id: Exclude<PresetId, 'custom'>, today: string): Range {
  switch (id) {
    case 'today': return { from: today, to: today, preset: id }
    case 'yesterday': return { from: shift(today, -1), to: shift(today, -1), preset: id }
    case '7d': return { from: shift(today, -6), to: today, preset: id }
    case '30d': return { from: shift(today, -29), to: today, preset: id }
    case 'month': return { from: firstOf(today), to: today, preset: id }
    case 'last_month': { const f = addMonths(today, -1); return { from: f, to: shift(firstOf(today), -1), preset: id } }
  }
}

export function rangeLabel(r: Range): string {
  if (!r.from && !r.to) return 'Tất cả thời gian'
  const hit = PRESETS.find((p) => p.id === r.preset)
  if (hit) return hit.label
  return `${r.from ? dayFull(r.from) : '…'} – ${r.to ? dayFull(r.to) : '…'}`
}

const days = (a: string, b: string) => Math.round((parse(b).getTime() - parse(a).getTime()) / 86_400_000) + 1
const typed = /^(\d{2})\/(\d{2})\/(\d{4})$/
const fromTyped = (s: string, today: string): string | null => {
  const m = typed.exec(s.trim())
  if (!m) return null
  const v = `${m[3]}-${m[2]}-${m[1]}`
  return ymd(parse(v)) === v && v <= today ? v : null
}

function Month({ month, today, from, to, onPick }: { month: string; today: string; from?: string; to?: string; onPick: (d: string) => void }) {
  const first = parse(month)
  const lead = (first.getUTCDay() + 6) % 7 // weeks start on Monday
  const count = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate()
  const cells = [...Array<null>(lead).fill(null), ...Array.from({ length: count }, (_, i) => shift(month, i))]
  while (cells.length % 7) cells.push(null)
  return (
    <div role="grid" aria-label={`Tháng ${first.getUTCMonth() + 1}, ${first.getUTCFullYear()}`} className="grid grid-cols-7">
      {WEEK.map((w) => <div key={w} role="columnheader" className="flex h-6 items-center justify-center text-[11px] font-semibold text-ink-3">{w}</div>)}
      {cells.map((d, i) => {
        if (!d) return <div key={i} />
        const edge = d === from || d === to
        const inside = !!from && !!to && d >= from && d <= to
        const future = d > today
        return (
          <div key={d} className={clsx('flex h-[34px] items-center justify-center', inside && 'bg-accent-soft', d === from && to && from !== to && 'rounded-l-full', d === to && from && from !== to && 'rounded-r-full')}>
            <button type="button" disabled={future} aria-label={dayFull(d)} aria-pressed={edge} onClick={() => onPick(d)}
              className={clsx('flex size-8 items-center justify-center rounded-full text-[13px]', edge ? 'bg-accent font-semibold text-white' : inside ? 'font-semibold text-accent' : future ? 'cursor-not-allowed text-ink-3' : 'font-medium hover:bg-app')}>
              {Number(d.slice(8))}
            </button>
          </div>
        )
      })}
    </div>
  )
}

export function DateRange({ value, onChange, now }: { value: Range; onChange: (r: Range) => void; now?: Date }) {
  const today = businessDay(now)
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<Range>(value)
  const [month, setMonth] = useState(firstOf(value.to ?? today))
  const [texts, setTexts] = useState({ from: '', to: '' })
  const root = useRef<HTMLDivElement>(null)
  const show = (r: Range) => { setDraft(r); setTexts({ from: r.from ? dayFull(r.from) : '', to: r.to ? dayFull(r.to) : '' }) }
  const openIt = () => { show(value); setMonth(firstOf(value.to ?? today)); setOpen(true) }

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (root.current && !root.current.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])

  const pick = (d: string) => {
    if (!draft.from || draft.to || d < draft.from) show({ from: d, preset: 'custom' }) // a new start, or the second click went backwards
    else show({ from: draft.from, to: d, preset: 'custom' })
  }
  const apply = () => { onChange(draft.from && !draft.to ? { ...draft, to: draft.from } : draft); setOpen(false) }
  const typedField = (k: 'from' | 'to', text: string) => {
    setTexts((t) => ({ ...t, [k]: text }))
    const v = fromTyped(text, today)
    if (v) { setDraft((r) => ({ ...r, [k]: v, preset: 'custom' })); setMonth(firstOf(v)) }
  }
  const summary = draft.from && draft.to ? `${days(draft.from, draft.to)} ngày · ${dayFull(draft.from).slice(0, 5)} – ${dayFull(draft.to).slice(0, 5)}` : draft.from ? 'Chọn ngày kết thúc' : 'Chưa chọn khoảng nào'
  const filtered = !!(value.from || value.to)
  return (
    <div ref={root} className="relative">
      <button type="button" aria-haspopup="dialog" aria-expanded={open} onClick={() => (open ? setOpen(false) : openIt())}
        className={clsx('flex h-9 max-w-full items-center gap-2 rounded-lg border px-3 text-[13px] whitespace-nowrap', filtered || open ? 'border-accent bg-accent-soft font-semibold text-accent' : 'border-line bg-surface text-ink-2')}>
        <CalendarDays className="size-4" aria-hidden />Thời gian:<span className="font-semibold">{rangeLabel(value)}</span><ChevronDown className="size-4" aria-hidden />
      </button>
      {open && (
        <div role="dialog" aria-label="Chọn khoảng thời gian" className="z-30 overflow-hidden rounded-xl border border-line bg-surface shadow-xl max-sm:fixed max-sm:inset-x-3 max-sm:top-3 max-sm:max-h-[calc(100dvh-1.5rem)] max-sm:overflow-y-auto sm:absolute sm:top-full sm:left-0 sm:mt-1.5 sm:w-[560px]">
          <div className="flex max-sm:flex-col">
            <div className="flex shrink-0 gap-0.5 bg-app p-3 max-sm:flex-wrap sm:w-44 sm:flex-col">
              <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-ink-3 max-sm:w-full">Khoảng nhanh</div>
              {[...PRESETS, { id: 'custom' as const, label: 'Tuỳ chọn' }].map((p) => (
                <button key={p.id} type="button" aria-pressed={draft.preset === p.id}
                  onClick={() => { if (p.id === 'custom') show({ preset: 'custom' }); else { const r = presetRange(p.id, today); show(r); setMonth(firstOf(r.to!)) } }}
                  className={clsx('h-[34px] rounded-lg px-2.5 text-left text-[13px]', draft.preset === p.id ? 'bg-accent-soft font-semibold text-accent' : 'font-medium hover:bg-surface')}>{p.label}</button>
              ))}
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-3 p-4">
              <div className="flex items-center justify-between">
                <button type="button" aria-label="Tháng trước" onClick={() => setMonth(addMonths(month, -1))} className="text-ink-2"><ChevronLeft className="size-5" /></button>
                <span className="text-sm font-semibold">Tháng {parse(month).getUTCMonth() + 1}, {parse(month).getUTCFullYear()}</span>
                <button type="button" aria-label="Tháng sau" disabled={addMonths(month, 1) > today} onClick={() => setMonth(addMonths(month, 1))} className="text-ink-2 disabled:text-ink-3"><ChevronRight className="size-5" /></button>
              </div>
              <Month month={month} today={today} from={draft.from} to={draft.to} onPick={pick} />
              <div className="flex gap-3">
                {(['from', 'to'] as const).map((k) => (
                  <label key={k} className="flex min-w-0 flex-1 flex-col gap-1 text-[11px] text-ink-3">{k === 'from' ? 'Từ ngày' : 'Đến ngày'}
                    <input value={texts[k]} placeholder="dd/mm/yyyy" inputMode="numeric" onChange={(e) => typedField(k, e.target.value)}
                      className={clsx('h-[34px] w-full min-w-0 rounded-lg border bg-surface px-2.5 text-[13px] text-ink', texts[k] && !fromTyped(texts[k], today) ? 'border-bad' : 'border-line')} />
                  </label>
                ))}
              </div>
              <p className="text-[11px] text-ink-3">Tính theo giờ của doanh nghiệp. Từ 00:00 ngày bắt đầu đến hết ngày kết thúc.</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-3">
            <span className="text-xs text-ink-2">{summary}</span>
            <div className="flex gap-2">
              <Button type="button" onClick={() => { onChange({}); setOpen(false) }}>Xoá lọc</Button>
              <Button type="button" variant="primary" disabled={!draft.from} onClick={apply}>Áp dụng</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
