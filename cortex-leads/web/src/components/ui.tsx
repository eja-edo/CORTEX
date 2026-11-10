import clsx from 'clsx'
import { CheckCircle2, CircleAlert, Ellipsis, Info, Loader2, Sparkles, TriangleAlert, X, type LucideIcon } from 'lucide-react'
import { type ButtonHTMLAttributes, type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { initials } from './format'

export type Tone = 'neutral' | 'accent' | 'ok' | 'warn' | 'bad' | 'ai' | 'solid'
const TONES: Record<Tone, string> = {
  neutral: 'bg-app text-ink-2',
  accent: 'bg-accent-soft text-accent',
  ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn',
  bad: 'bg-bad-soft text-bad',
  ai: 'bg-ai-soft text-ai',
  solid: 'bg-accent text-white',
}

export function Badge({ tone = 'neutral', children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={clsx('inline-flex items-center rounded-full px-2 py-[3px] text-xs font-medium whitespace-nowrap', TONES[tone], className)}>{children}</span>
}

type Variant = 'primary' | 'secondary' | 'danger' | 'dangerSolid' | 'ghost' | 'segOn'
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-accent text-white hover:bg-indigo-700 disabled:opacity-40',
  secondary: 'bg-surface text-ink border border-line hover:bg-app disabled:opacity-40',
  danger: 'bg-surface text-bad border border-bad hover:bg-bad-soft disabled:opacity-40',
  dangerSolid: 'bg-bad text-white hover:bg-red-800 disabled:opacity-40',
  ghost: 'bg-transparent text-ink-2 hover:text-ink disabled:opacity-40', // the unselected half of a segmented control
  segOn: 'bg-surface text-accent border border-line disabled:opacity-40', // the selected half
}

export function Button({ variant = 'secondary', busy, className, children, disabled, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button {...rest} disabled={disabled || busy}
      className={clsx('inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-[13px] font-semibold max-lg:min-h-10', VARIANTS[variant], className)}>
      {busy && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
      {children}
    </button>
  )
}

export function Avatar({ name, size = 40, active }: { name: string; size?: number; active?: boolean }) {
  return (
    <span aria-hidden style={{ width: size, height: size, fontSize: size / 2.8 }}
      className={clsx('inline-flex shrink-0 items-center justify-center rounded-full font-semibold', active ? 'bg-accent text-white' : 'bg-app text-ink-2')}>
      {initials(name)}
    </span>
  )
}

export const Label = ({ children }: { children: ReactNode }) =>
  <h3 className="text-[11px] font-semibold tracking-wider text-ink-3 uppercase">{children}</h3>

/** The three states every data surface owes the user (loading, empty, error); never a blank. */
export const Loading = ({ label = 'Đang tải…' }: { label?: string }) =>
  <div role="status" className="flex items-center gap-2 p-6 text-ink-2"><Loader2 className="size-4 animate-spin" aria-hidden />{label}</div>
export const Empty = ({ children }: { children: ReactNode }) => <p className="p-6 text-center text-ink-3">{children}</p>
export function ErrorBox({ children, onRetry }: { children?: ReactNode; onRetry?: () => void }) {
  return (
    <div role="alert" className="m-4 flex flex-wrap items-center gap-x-3 gap-y-2.5 rounded-lg bg-bad-soft px-3.5 py-3 text-[13px] leading-snug text-bad">
      <span className="flex min-w-0 flex-1 basis-64 items-start gap-2.5"><CircleAlert className="mt-px size-4 shrink-0" aria-hidden /><span className="min-w-0">{children ?? 'Không tải được dữ liệu.'}</span></span>
      {onRetry && <Button variant="danger" className="ml-auto shrink-0" onClick={onRetry}>Thử lại</Button>}
    </div>
  )
}

const NOTICE_ICON: Record<Tone, LucideIcon> = { ok: CheckCircle2, bad: CircleAlert, warn: TriangleAlert, ai: Sparkles, neutral: Info, accent: Info, solid: Info }

/** A message in a page. The icon and the text sit on one line and the text is flush with it; an `action` (a button) goes at the far end, centred
 * on the block, and drops under the text on a narrow screen. Put buttons in `action`, never inside the text. */
export function Notice({ tone = 'warn', icon, action, children }: { tone?: Tone; icon?: ReactNode; action?: ReactNode; children: ReactNode }) {
  const Icon = NOTICE_ICON[tone]
  return (
    <div role="status" className={clsx('flex flex-wrap gap-x-3 gap-y-2.5 rounded-lg px-3.5 py-3 text-[13px] leading-snug', action ? 'items-center' : 'items-start', TONES[tone])}>
      <span className="flex min-w-0 flex-1 basis-64 items-start gap-2.5">{icon ?? <Icon className="mt-px size-4 shrink-0" aria-hidden />}<span className="min-w-0">{children}</span></span>
      {action && <span className="ml-auto flex shrink-0 items-center gap-2">{action}</span>}
    </div>
  )
}

export const Card = ({ children, className }: { children: ReactNode; className?: string }) =>
  <section className={clsx('rounded-xl border border-line bg-surface', className)}>{children}</section>

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
      <div className="min-w-0 flex-1 basis-64"><h1 className="text-xl font-bold [overflow-wrap:anywhere] sm:text-2xl">{title}</h1>{subtitle && <p className="mt-1 text-[13px] text-ink-2">{subtitle}</p>}</div>
      {action}
    </header>
  )
}

/** Keeps the chosen tab in sight in a row of tabs that scrolls sideways on a narrow screen. Put the ref on the row (it must be `relative`). */
export function useChosenTabInView<E extends HTMLElement>(chosen: string) {
  const row = useRef<E>(null)
  useLayoutEffect(() => {
    const box = row.current
    const tab = box?.querySelector<HTMLElement>('[aria-selected="true"]')
    if (box && tab && box.scrollWidth > box.clientWidth) box.scrollLeft = tab.offsetLeft - (box.clientWidth - tab.offsetWidth) / 2
  }, [chosen])
  return row
}

export function Tabs<T extends string>({ tabs, value, onChange, tight }: { tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (id: T) => void; tight?: boolean }) {
  const row = useChosenTabInView<HTMLDivElement>(value)
  return (
    <div ref={row} role="tablist" className={clsx('relative flex max-w-full min-w-0 overflow-x-auto shadow-[inset_0_-1px_0_var(--color-line)] [scrollbar-width:none]', tight ? 'gap-3' : 'gap-5')}>
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={t.id === value} onClick={() => onChange(t.id)}
          className={clsx('flex shrink-0 items-center gap-1.5 border-b-2 pb-2.5 text-[13px] font-medium whitespace-nowrap max-lg:pt-1',
            t.id === value ? 'border-accent font-semibold text-accent' : 'border-transparent text-ink-2 hover:text-ink')}>
          {t.label}{t.count !== undefined && <span className={clsx('text-xs font-semibold', t.id === value ? 'text-accent' : 'text-ink-3')}>{t.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function Meter({ label, value, total, tone = 'accent' }: { label: string; value: number; total: number | null; tone?: 'accent' | 'ai' }) {
  const pct = total ? Math.min(100, Math.round((value / total) * 100)) : 0
  return (
    <div className="flex-1">
      <div className="mb-1.5 flex justify-between text-xs"><span className="text-ink-2">{label}</span><b>{value.toLocaleString('vi-VN')} / {total?.toLocaleString('vi-VN') ?? '–'}</b></div>
      <div role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={label} className="h-1.5 rounded-full bg-app">
        <div className={clsx('h-1.5 rounded-full', tone === 'ai' ? 'bg-ai' : 'bg-accent')} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

/** A dialog over the page: Escape or a click outside closes it. The caller decides what is inside. */
export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-ink/40 p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div role="dialog" aria-modal="true" aria-label={title} className={clsx('flex w-full flex-col gap-4 rounded-2xl bg-surface p-5 shadow-xl', wide ? 'max-w-xl' : 'max-w-md')}>
        <div className="flex items-center gap-2"><h2 className="flex-1 text-base font-bold">{title}</h2>
          <button type="button" aria-label="Đóng" onClick={onClose} className="grid size-8 place-items-center rounded-lg text-ink-3 hover:bg-app hover:text-ink"><X className="size-4" aria-hidden /></button></div>
        {children}
      </div>
    </div>
  )
}

const PANEL_NARROW = {
  lg: { below: '(max-width: 1023.98px)', box: 'max-lg:fixed max-lg:inset-y-0 max-lg:right-0 max-lg:z-50 max-lg:w-full max-lg:max-w-xl max-lg:overflow-y-auto max-lg:rounded-none max-lg:border-0 max-lg:shadow-xl', shut: 'max-lg:hidden', wide: 'lg:hidden' },
  xl: { below: '(max-width: 1279.98px)', box: 'max-xl:fixed max-xl:inset-y-0 max-xl:right-0 max-xl:z-50 max-xl:w-full max-xl:max-w-xl max-xl:overflow-y-auto max-xl:rounded-none max-xl:border-0 max-xl:shadow-xl', shut: 'max-xl:hidden', wide: 'xl:hidden' },
}

/** What goes beside a list on a wide screen. Below `at` there is no room beside it, so the panel lies over the page while it is `open`, with a close
 * button and a dimmed page behind; closed, it is not there at all (its "pick something" hint means nothing on a phone). */
export function SidePanel({ label, open, onClose, at = 'xl', className, children }: { label: string; open: boolean; onClose: () => void; at?: 'lg' | 'xl'; className?: string; children: ReactNode }) {
  const n = PANEL_NARROW[at]
  const box = useRef<HTMLElement>(null)
  const close = useRef(onClose)
  useEffect(() => { close.current = onClose })
  useEffect(() => {
    if (!open || !window.matchMedia?.(n.below).matches) return
    box.current?.focus()
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape' && !document.querySelector('[aria-modal="true"]')) close.current() }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [open, n.below])
  return (
    <>
      {open && <div aria-hidden className={clsx('fixed inset-0 z-40 bg-ink/40', n.wide)} onClick={onClose} />}
      <aside ref={box} tabIndex={-1} aria-label={label} className={clsx('bg-surface outline-none', n.box, !open && n.shut, className)}>
        {open && <div className={clsx('sticky top-0 z-10 flex justify-end bg-surface p-2', n.wide)}>
          <button type="button" aria-label="Đóng" onClick={onClose} className="grid size-10 place-items-center rounded-lg text-ink-2 hover:bg-app"><X className="size-5" aria-hidden /></button></div>}
        {children}
      </aside>
    </>
  )
}

export interface MenuItem { label: string; icon?: ReactNode; danger?: boolean; divider?: boolean; onClick: () => void }

/** A table that turns into one card per row on a phone, from the same markup: `block` on the table and its body, `STACK_ROW` on each row and
 * `STACK_CELL` with a `data-label` on each cell; the head row is hidden there. */
export const STACK_ROW = 'max-md:grid max-md:grid-cols-2 max-md:gap-x-3 max-md:gap-y-2.5 max-md:p-4'
export const STACK_CELL = 'max-md:block max-md:min-w-0 max-md:p-0 max-md:before:mb-0.5 max-md:before:block max-md:before:text-[11px] max-md:before:font-normal max-md:before:text-ink-3 max-md:before:content-[attr(data-label)]'

/** The "⋯" of a row: rare actions out of the way. Closes on a click outside, on Escape and after a choice. */
export function Menu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away); document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', key) }
  }, [open])
  return (
    <div ref={box} className="relative">
      <button type="button" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}
        className={clsx('grid size-8 place-items-center rounded-lg text-ink-2 hover:bg-app max-lg:size-10', open && 'bg-app')}><Ellipsis className="size-4" aria-hidden /></button>
      {open && (
        <div role="menu" className="absolute top-full right-0 z-20 mt-1 w-52 rounded-xl border border-line bg-surface p-1.5 shadow-lg">
          {items.map((it) => (
            <div key={it.label}>
              {it.divider && <div className="my-1 h-px bg-line" />}
              <button type="button" role="menuitem" onClick={() => { setOpen(false); it.onClick() }}
                className={clsx('flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-[13px] font-medium hover:bg-app', it.danger ? 'text-bad hover:bg-bad-soft' : 'text-ink')}>{it.icon}{it.label}</button>
            </div>))}
        </div>)}
    </div>
  )
}

export interface PickOption { id: string; label: string; note?: string }
const plain = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').toLowerCase()

/** Choose any number of things from a long list: what is chosen sits on top as chips, «+ Thêm» opens a list with a search box and a tick for each,
 *  «Bỏ chọn» empties it. Search ignores accents. Closes on a click outside and on Escape (without closing the dialog it sits in). */
export function MultiSelect({ options, value, onChange, addLabel = 'Thêm', searchLabel = 'Tìm theo tên…', noun = 'mục' }:
  { options: PickOption[]; value: string[]; onChange: (ids: string[]) => void; addLabel?: string; searchLabel?: string; noun?: string }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) } }
    document.addEventListener('mousedown', away); document.addEventListener('keydown', key, true)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', key, true) }
  }, [open])
  const chosen = value.map((id) => options.find((o) => o.id === id)).filter((o): o is PickOption => !!o)
  const shown = options.filter((o) => !q.trim() || plain(o.label).includes(plain(q.trim())))
  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id])
  return (
    <div ref={box} className="relative flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {chosen.map((o) => (
          <span key={o.id} className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft py-1 pr-1.5 pl-3 text-xs font-medium text-accent">
            {o.label}{o.note && <span className="font-normal text-ink-3">({o.note})</span>}
            <button type="button" aria-label={`Bỏ ${o.label}`} onClick={() => toggle(o.id)} className="grid size-4 place-items-center rounded-full hover:bg-white/70"><X className="size-3" aria-hidden /></button>
          </span>))}
        <button type="button" aria-haspopup="true" aria-expanded={open} onClick={() => { setOpen(!open); setQ('') }}
          className="inline-flex items-center gap-1 rounded-full border border-dashed border-ink-3 px-3 py-1 text-xs font-semibold text-ink-2 hover:border-accent hover:text-accent">+ {addLabel}</button>
      </div>
      {open && (
        <div role="group" aria-label={`Chọn ${noun}`} className="absolute top-full left-0 z-30 mt-1.5 w-full max-w-sm rounded-xl border border-line bg-surface p-2 shadow-lg">
          <input autoFocus type="search" aria-label={`Tìm ${noun}`} value={q} onChange={(e) => setQ(e.target.value)} placeholder={searchLabel}
            className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft" />
          <div className="mt-1.5 max-h-56 overflow-y-auto">
            {shown.length === 0 ? <p className="p-3 text-center text-xs text-ink-3">{options.length === 0 ? `Chưa có ${noun} nào để chọn.` : 'Không có kết quả.'}</p>
              : shown.map((o) => (
                <label key={o.id} className={clsx('flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] hover:bg-app', value.includes(o.id) && 'bg-accent-soft/60')}>
                  <input type="checkbox" checked={value.includes(o.id)} onChange={() => toggle(o.id)} className="size-4 accent-[var(--color-accent)]" />
                  <span className="min-w-0 flex-1 truncate">{o.label}</span>{o.note && <span className="text-xs text-ink-3">{o.note}</span>}
                </label>))}
          </div>
          <div className="mt-1.5 flex items-center justify-between border-t border-line px-1 pt-2">
            <button type="button" disabled={value.length === 0} onClick={() => onChange([])} className="text-xs font-semibold text-accent disabled:text-ink-3">Bỏ chọn</button>
            <button type="button" onClick={() => setOpen(false)} className="text-xs font-semibold text-ink-2 hover:text-ink">Xong</button>
          </div>
        </div>)}
    </div>
  )
}
