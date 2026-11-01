import clsx from 'clsx'
import { CheckCircle2, CircleAlert, Ellipsis, Info, Loader2, Sparkles, TriangleAlert, X, type LucideIcon } from 'lucide-react'
import { type ButtonHTMLAttributes, type ReactNode, useEffect, useRef, useState } from 'react'
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

type Variant = 'primary' | 'secondary' | 'danger' | 'dangerSolid'
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-accent text-white hover:bg-indigo-700 disabled:opacity-40',
  secondary: 'bg-surface text-ink border border-line hover:bg-app disabled:opacity-40',
  danger: 'bg-surface text-bad border border-bad hover:bg-bad-soft disabled:opacity-40',
  dangerSolid: 'bg-bad text-white hover:bg-red-800 disabled:opacity-40',
}

export function Button({ variant = 'secondary', busy, className, children, disabled, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button {...rest} disabled={disabled || busy}
      className={clsx('inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-[13px] font-semibold', VARIANTS[variant], className)}>
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
    <header className="flex items-center justify-between gap-4">
      <div><h1 className="text-2xl font-bold">{title}</h1>{subtitle && <p className="mt-1 text-[13px] text-ink-2">{subtitle}</p>}</div>
      {action}
    </header>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange, tight }: { tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (id: T) => void; tight?: boolean }) {
  return (
    <div role="tablist" className={clsx('flex border-b border-line', tight ? 'gap-3' : 'gap-5')}>
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={t.id === value} onClick={() => onChange(t.id)}
          className={clsx('-mb-px flex items-center gap-1.5 border-b-2 pb-2.5 text-[13px] font-medium whitespace-nowrap',
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

export interface MenuItem { label: string; icon?: ReactNode; danger?: boolean; divider?: boolean; onClick: () => void }

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
        className={clsx('grid size-8 place-items-center rounded-lg text-ink-2 hover:bg-app', open && 'bg-app')}><Ellipsis className="size-4" aria-hidden /></button>
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
