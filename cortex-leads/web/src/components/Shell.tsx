import clsx from 'clsx'
import { Bot, ChevronDown, ChevronRight, Database, GraduationCap, Inbox, LayoutTemplate, LogOut, Menu, School, Settings, Sparkles, Brain, ScrollText, UserCog, Workflow, Wrench, X, type LucideIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useLogout } from '../api/hooks'
import type { Me } from '../api/types'
import { can } from './can'
import { Badge } from './ui'
import { Perm } from '../api/enums'

interface Leaf { label: string; icon: LucideIcon; show: boolean; to?: string; badge?: number }  // no `to`: not built yet (none today: a page that does not exist is not in the menu)
interface Group { id: string; label: string; icon: LucideIcon; items: Leaf[] }
type Entry = Leaf | Group
interface Section { label?: string; entries: Entry[] }

/** The menu. A role sees only what it may open: an entry it cannot open goes, and a group or a section left empty goes with it. */
function menuOf(me: Me): Section[] {
  const inbox = can(me, Perm.INBOX_USE)
  const settings = can(me, Perm.SETTINGS_MANAGE)
  const sections: Section[] = [
    { label: 'Công việc', entries: [
      { label: 'Hộp thư', icon: Inbox, to: '/inbox', show: inbox, badge: me.needs_person }] },
    { label: 'Nghiệp vụ', entries: [
      { id: 'teaching', label: 'Đào tạo', icon: School, items: [
        { label: 'Lớp học', icon: GraduationCap, to: '/classes', show: can(me, Perm.LESSONS_READ) },
        { label: 'Bài tập mẫu', icon: LayoutTemplate, to: '/templates', show: can(me, Perm.GRADING_USE) }] },
      { id: 'ai', label: 'Vận hành AI', icon: Workflow, items: [
        { label: 'Kỹ năng', icon: Sparkles, to: '/skills', show: can(me, Perm.SKILLS_READ) },
        { label: 'Công cụ & kết nối', icon: Wrench, to: '/tools', show: can(me, Perm.TOOLS_MANAGE) },
        { label: 'AI tổng', icon: Bot, to: '/assistant', show: can(me, Perm.ASSISTANT_USE) }] },
      { label: 'Dữ liệu', icon: Database, to: '/data', show: can(me, Perm.CATALOG_READ) }] },
    { label: 'Quản trị', entries: [
      { label: 'Nhân viên & quyền', icon: UserCog, to: '/team', show: can(me, Perm.TEAM_MANAGE) },
      { label: 'Nhật ký hoạt động', icon: ScrollText, to: '/audit', show: true },
      { label: 'Cài đặt', icon: Settings, to: '/settings', show: settings }] },
  ]
  return sections.map((s) => ({ ...s, entries: s.entries.flatMap((e): Entry[] => {
    if (!('items' in e)) return e.show ? [e] : []
    const items = e.items.filter((i) => i.show)
    return items.length > 1 ? [{ ...e, items }] : items  // a group of one is just that entry
  }) })).filter((s) => s.entries.length > 0)
}

function Item({ leaf, nested }: { leaf: Leaf; nested?: boolean }) {
  const Icon = leaf.icon
  const row = 'flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm max-lg:py-2.5'
  const glyph = <Icon className="size-[18px] shrink-0" aria-hidden />
  if (!leaf.to) return <span aria-disabled title="Sắp có" className={clsx(row, 'cursor-not-allowed font-medium text-ink-3')}>{glyph}{leaf.label}</span>
  return (
    <NavLink to={leaf.to} className={({ isActive }) => clsx(row, isActive ? 'bg-accent-soft font-semibold text-accent' : clsx('text-ink-2 hover:bg-app', !nested && 'font-medium'))}>
      {glyph}<span className="min-w-0 flex-1 truncate">{leaf.label}</span>{!!leaf.badge && <Badge tone="solid">{leaf.badge}</Badge>}
    </NavLink>
  )
}

const FOLDED_KEY = 'cortex.menu.folded'
const foldedAtStart = (id: string) => { try { return (JSON.parse(localStorage.getItem(FOLDED_KEY) ?? '[]') as string[]).includes(id) } catch { return false } }
function remember(id: string, folded: boolean) {
  try {
    const rest = (JSON.parse(localStorage.getItem(FOLDED_KEY) ?? '[]') as string[]).filter((x) => x !== id)
    localStorage.setItem(FOLDED_KEY, JSON.stringify(folded ? [...rest, id] : rest))
  } catch { /* no storage here: the menu just forgets, and starts open next time */ }
}

/** A group folds away and stays folded on the next visit, but opens by itself when the person lands on a page inside it, and marks itself while they are there. */
function MenuGroup({ g }: { g: Group }) {
  const { pathname } = useLocation()
  const [folded, setFolded] = useState(() => foldedAtStart(g.id))
  const here = g.items.some((i) => i.to && (pathname === i.to || pathname.startsWith(`${i.to}/`)))
  useEffect(() => { if (here) setFolded(false) }, [here])
  const Icon = g.icon
  const Chevron = folded ? ChevronRight : ChevronDown
  const toggle = () => { remember(g.id, !folded); setFolded(!folded) }
  return (
    <div className="flex flex-col gap-0.5">
      <button type="button" aria-expanded={!folded} aria-controls={`menu-${g.id}`} onClick={toggle}
        className={clsx('flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm font-semibold hover:bg-app max-lg:py-2.5', here ? 'text-accent' : 'text-ink')}>
        <Icon className="size-[18px] shrink-0" aria-hidden /><span className="min-w-0 flex-1 truncate">{g.label}</span><Chevron className="size-4 shrink-0 text-ink-3" aria-hidden />
      </button>
      {!folded && <div id={`menu-${g.id}`} className="ml-[18px] flex flex-col gap-0.5 border-l border-line pl-2">{g.items.map((i) => <Item key={i.label} leaf={i} nested />)}</div>}
    </div>
  )
}

export function Shell({ me }: { me: Me }) {
  const logout = useLogout()
  const { key } = useLocation()
  // Below `lg` the menu is a drawer over the page: the page behind is inert while it is open, and any move to another page closes it.
  const [menu, setMenu] = useState(false)
  const opener = useRef<HTMLButtonElement>(null)
  const closer = useRef<HTMLButtonElement>(null)
  const shut = () => { setMenu(false); opener.current?.focus() }
  useEffect(() => setMenu(false), [key])
  useEffect(() => {
    if (!menu) return
    closer.current?.focus()
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') { setMenu(false); opener.current?.focus() } }
    const wide = window.matchMedia?.('(min-width: 1024px)')
    const grown = () => { if (wide?.matches) setMenu(false) }
    window.addEventListener('keydown', esc); wide?.addEventListener('change', grown)
    return () => { window.removeEventListener('keydown', esc); wide?.removeEventListener('change', grown) }
  }, [menu])
  return (
    <div className="flex h-full overflow-hidden">
      {menu && <div aria-hidden className="fixed inset-0 z-30 bg-ink/40 lg:hidden" onClick={shut} />}
      <aside id="main-menu" className={clsx('flex min-h-0 flex-col gap-3 overflow-hidden border-r border-line bg-surface p-4 transition-transform duration-200 max-lg:fixed max-lg:inset-y-0 max-lg:left-0 max-lg:z-40 max-lg:w-[min(18rem,85vw)] max-lg:shadow-xl motion-reduce:transition-none lg:h-full lg:w-58 lg:shrink-0', !menu && 'max-lg:invisible max-lg:-translate-x-full')}>
        <nav aria-label="Điều hướng chính" className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <div className="flex items-center gap-2.5 px-2 pb-3">
            <span className="flex size-8 items-center justify-center rounded-lg bg-accent text-white" aria-hidden><Brain className="size-[18px]" /></span>
            <div className="min-w-0 flex-1"><div className="text-base font-bold">Cortex</div><div className="truncate text-[11px] text-ink-3">{me.tenant}</div></div>
            <button ref={closer} type="button" aria-label="Đóng menu" onClick={shut} className="grid size-10 place-items-center rounded-lg text-ink-2 hover:bg-app lg:hidden"><X className="size-5" aria-hidden /></button>
          </div>
          {menuOf(me).map((sec, i) => (
            <div key={sec.label ?? i} className="flex flex-col gap-0.5">
              {sec.label && <h2 className="px-2.5 pt-4 pb-1.5 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">{sec.label}</h2>}
              {sec.entries.map((e) => ('items' in e ? <MenuGroup key={e.id} g={e} /> : <Item key={e.label} leaf={e} />))}
            </div>))}
        </nav>
        <div className="flex shrink-0 flex-col gap-3">
          <NavLink to="/account" className="flex flex-col px-2 text-xs text-ink-2 hover:text-ink"><b className="truncate text-[13px] text-ink">{me.name}</b><span className="truncate">Tài khoản và mật khẩu</span></NavLink>
          <button onClick={() => logout.mutate()} className="flex items-center gap-2 px-2 text-xs text-ink-2 hover:text-ink">
            <LogOut className="size-3.5" aria-hidden />Đăng xuất · {me.staff_ref ?? me.email}
          </button>
        </div>
      </aside>
      <div inert={menu} className="flex h-full min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface px-2 lg:hidden">
          <button ref={opener} type="button" aria-label="Mở menu" aria-expanded={menu} aria-controls="main-menu" onClick={() => setMenu(true)} className="relative grid size-10 place-items-center rounded-lg text-ink hover:bg-app">
            <Menu className="size-5" aria-hidden />{!!me.needs_person && <span aria-hidden className="absolute top-2 right-2 size-2 rounded-full bg-bad" />}</button>
          <span className="flex size-7 items-center justify-center rounded-lg bg-accent text-white" aria-hidden><Brain className="size-4" /></span>
          <span className="min-w-0 truncate text-[15px] font-bold">Cortex<span className="ml-2 text-xs font-normal text-ink-3">{me.tenant}</span></span>
        </header>
        <main className="min-h-0 min-w-0 flex-1 overflow-hidden"><Outlet /></main>
      </div>
    </div>
  )
}
