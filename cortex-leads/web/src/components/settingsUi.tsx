import clsx from 'clsx'
import type { ReactNode } from 'react'
import { Card } from './ui'

/** The pieces every Settings tab is made of (pencil screens 20–24): a card with a header, rows of "what it is | the control", a footer for the save button. */
export const fieldCls = 'h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm font-normal'

export const SCard = ({ children, className }: { children: ReactNode; className?: string }) => <Card className={clsx('@container overflow-hidden', className)}>{children}</Card>

export function SHead({ title, desc, right }: { title: string; desc?: ReactNode; right?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-[18px] sm:px-6">
      <div className="min-w-0 flex-1"><h2 className="text-base font-bold">{title}</h2>{desc && <p className="mt-0.5 text-[13px] text-ink-2">{desc}</p>}</div>
      {right}
    </header>
  )
}

/** Left: what the setting is and why it matters. Right: the control. On a narrow screen they stack. */
export function SRow({ label, desc, htmlFor, children }: { label: string; desc?: ReactNode; htmlFor?: string; children: ReactNode }) {
  return (
    <div className="grid gap-x-8 gap-y-3 border-b border-line px-4 py-5 last:border-b-0 sm:px-6 @xl:grid-cols-[220px_minmax(0,1fr)]">
      <div className="flex flex-col gap-1"><label htmlFor={htmlFor} className="text-sm font-semibold">{label}</label>{desc && <p className="text-[13px] leading-snug text-ink-2">{desc}</p>}</div>
      <div className="flex min-w-0 flex-col gap-2">{children}</div>
    </div>
  )
}

export const SFoot = ({ children }: { children: ReactNode }) =>
  <footer className="flex flex-wrap items-center justify-end gap-3 border-t border-line bg-gray-50 px-4 py-3.5 sm:px-6">{children}</footer>

export const SField = ({ label, children, className }: { label: string; children: ReactNode; className?: string }) =>
  <label className={clsx('flex flex-col gap-1.5 text-[13px] font-semibold', className)}>{label}{children}</label>
