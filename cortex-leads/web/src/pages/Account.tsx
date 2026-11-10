import { KeyRound, LogOut, Monitor, Search, ShieldCheck, Smartphone } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { explain } from '../api/client'
import { useChangePassword, useLogoutAll, useMySessions, useRevokeSession, useSession } from '../api/hooks'
import type { MySession } from '../api/types'
import { Perm } from '../api/enums'
import { ROLE_LABEL, can } from '../components/can'
import { SCard, SFoot, SHead, SRow, fieldCls } from '../components/settingsUi'
import { Time } from '../components/Time'
import { TwoStep } from '../components/TwoStep'
import { Avatar, Badge, Button, ErrorBox, Loading, Modal, Notice, PageHeader } from '../components/ui'

/** How many devices the page shows before «Xem tất cả». */
const SHOWN = 5

function device(ua: string | null) {
  const u = ua ?? ''
  const browser = /Edg\//.test(u) ? 'Edge' : /Chrome\//.test(u) ? 'Chrome' : /Firefox\//.test(u) ? 'Firefox' : /Safari\//.test(u) ? 'Safari' : 'Trình duyệt'
  const os = /Windows/.test(u) ? 'Windows' : /Android/.test(u) ? 'Android' : /iPhone|iPad/.test(u) ? 'iOS' : /Mac OS/.test(u) ? 'macOS' : /Linux/.test(u) ? 'Linux' : ''
  return { label: os ? `${browser} · ${os}` : browser, phone: /Android|iPhone|iPad|Mobile/.test(u) }
}

/** This device first, then the one used most recently: the list a person scans for "is that me?". */
const ordered = (items: MySession[]) =>
  [...items].sort((a, b) => Number(b.current) - Number(a.current) || b.last_seen_at.localeCompare(a.last_seen_at))

function Profile() {
  const { data: me } = useSession()
  if (!me) return null
  return (
    <SCard>
      <div className="flex flex-wrap items-center gap-4 px-4 py-5 sm:px-6">
        <Avatar name={me.name} size={56} active />
        <div className="min-w-0 flex-1 basis-56">
          <p className="text-lg font-bold [overflow-wrap:anywhere]">{me.name}</p>
          <p className="text-[13px] text-ink-2 [overflow-wrap:anywhere]">{me.email}</p>
          <p className="mt-2 flex flex-wrap gap-1.5"><Badge tone={me.role === 'owner' ? 'ai' : 'neutral'}>{ROLE_LABEL[me.role]}</Badge><Badge>{me.tenant}</Badge></p>
        </div>
      </div>
      <p className="border-t border-line bg-gray-50 px-4 py-3 text-xs text-ink-2 sm:px-6">
        {can(me, Perm.TEAM_MANAGE)
          ? <>Tên, email và vai trò sửa ở <Link to="/team" className="font-semibold text-accent hover:underline">Nhân viên &amp; quyền</Link>.</>
          : 'Muốn đổi tên, email hay vai trò, nhờ chủ trung tâm sửa giúp.'}
      </p>
    </SCard>
  )
}

export function PasswordForm() {
  const change = useChangePassword()
  const [cur, setCur] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const mismatch = again.length > 0 && again !== next
  const submit = (e: FormEvent) => { e.preventDefault(); change.mutate({ current: cur, new: next }, { onSuccess: () => { setCur(''); setNext(''); setAgain('') } }) }
  return (
    <SCard><form onSubmit={submit}>
      <SHead title="Đổi mật khẩu" desc="Đổi mật khẩu sẽ đăng xuất mọi thiết bị khác của bạn." />
      <SRow label="Mật khẩu hiện tại" htmlFor="pw-current">
        <input id="pw-current" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} className={fieldCls} /></SRow>
      <SRow label="Mật khẩu mới" htmlFor="pw-new" desc="Ít nhất 10 ký tự, có cả chữ và số, không chứa email hay tên của bạn.">
        <input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} className={fieldCls} />
        <input aria-label="Nhập lại mật khẩu mới" placeholder="Nhập lại mật khẩu mới" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} className={fieldCls} />
        {mismatch && <p role="alert" className="text-[13px] text-bad">Hai mật khẩu chưa giống nhau.</p>}
      </SRow>
      {(change.isError || change.isSuccess) && <div className="px-4 pb-4 sm:px-6">
        {change.isError && <p role="alert" className="text-[13px] text-bad">{explain(change.error)}</p>}
        {change.isSuccess && <Notice tone="ok">Đã đổi mật khẩu.{change.data.other_sessions_ended > 0 ? ` ${change.data.other_sessions_ended} thiết bị khác đã bị đăng xuất.` : ''}</Notice>}
      </div>}
      <SFoot><Button variant="primary" type="submit" busy={change.isPending} disabled={!cur || next.length < 10 || next !== again}><KeyRound className="size-4" aria-hidden />Đổi mật khẩu</Button></SFoot>
    </form></SCard>
  )
}

function DeviceRow({ s }: { s: MySession }) {
  const revoke = useRevokeSession()
  const d = device(s.user_agent)
  const Icon = d.phone ? Smartphone : Monitor
  return (
    <li className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3.5 last:border-b-0 sm:px-6">
      <span className={`grid size-10 shrink-0 place-items-center rounded-full ${s.current ? 'bg-ok-soft text-ok' : 'bg-app text-ink-2'}`}><Icon className="size-5" aria-hidden /></span>
      <div className="min-w-0 flex-1 basis-52">
        <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">{d.label}{s.current && <Badge tone="ok">Thiết bị này</Badge>}</p>
        <p className="text-xs text-ink-2">{s.ip ?? 'không rõ địa chỉ'} · hoạt động <Time iso={s.last_seen_at} as="when" /> · đăng nhập <Time iso={s.created_at} as="dateTime" /></p>
        {revoke.isError && <p role="alert" className="mt-1 text-xs text-bad">{explain(revoke.error)}</p>}
      </div>
      {!s.current && <Button aria-label="Đăng xuất thiết bị này" busy={revoke.isPending} onClick={() => revoke.mutate(s.id)}><LogOut className="size-3.5" aria-hidden />Đăng xuất</Button>}
    </li>
  )
}

/** Every device, in a window: the page keeps only the few a person checks most of the time. */
function AllDevices({ items, onClose }: { items: MySession[]; onClose: () => void }) {
  const [term, setTerm] = useState('')
  const t = term.trim().toLowerCase()
  const shown = items.filter((s) => !t || device(s.user_agent).label.toLowerCase().includes(t) || (s.ip ?? '').includes(t))
  return (
    <Modal title={`Tất cả thiết bị đang đăng nhập (${items.length})`} onClose={onClose} wide>
      <label className="relative block"><Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
        <input type="search" aria-label="Lọc thiết bị" placeholder="Lọc theo trình duyệt, hệ điều hành hoặc địa chỉ IP" value={term} onChange={(e) => setTerm(e.target.value)} className={`${fieldCls} pl-9`} /></label>
      <ul aria-label="Mọi thiết bị" className="-mx-5 max-h-[60vh] overflow-y-auto border-y border-line">
        {shown.map((s) => <DeviceRow key={s.id} s={s} />)}
        {shown.length === 0 && <li className="px-6 py-8 text-center text-[13px] text-ink-3">Không có thiết bị nào khớp.</li>}
      </ul>
      <div className="flex justify-end"><Button onClick={onClose}>Đóng</Button></div>
    </Modal>
  )
}

function Devices() {
  const q = useMySessions()
  const all = useLogoutAll()
  const [open, setOpen] = useState(false)
  const [ask, setAsk] = useState(false)
  const items = useMemo(() => ordered(q.data?.items ?? []), [q.data])
  if (q.isPending) return <SCard><Loading /></SCard>
  if (q.isError) return <SCard><ErrorBox onRetry={() => q.refetch()} /></SCard>
  const more = items.length > SHOWN
  return (
    <SCard>
      <SHead title="Thiết bị đang đăng nhập" desc={`${items.length} thiết bị. Thấy thiết bị lạ thì đăng xuất nó rồi đổi mật khẩu.`}
        right={more && <Button onClick={() => setOpen(true)}>Xem tất cả ({items.length})</Button>} />
      <ul aria-label="Thiết bị gần đây">{items.slice(0, SHOWN).map((s) => <DeviceRow key={s.id} s={s} />)}</ul>
      {more && <p className="border-t border-line px-4 py-2.5 text-xs text-ink-3 sm:px-6">Đang hiện {SHOWN} thiết bị dùng gần nhất. <button type="button" onClick={() => setOpen(true)} className="font-semibold text-accent hover:underline">Xem cả {items.length}</button></p>}
      <SFoot>
        {ask ? <span className="flex flex-wrap items-center justify-end gap-2 text-[13px] text-ink-2">Đăng xuất cả máy đang dùng?
          <Button onClick={() => setAsk(false)}>Không</Button><Button variant="dangerSolid" busy={all.isPending} onClick={() => all.mutate()}>Đăng xuất hết</Button></span>
          : <Button variant="danger" onClick={() => setAsk(true)}><ShieldCheck className="size-4" aria-hidden />Đăng xuất khỏi mọi thiết bị</Button>}
        {all.isError && <p role="alert" className="w-full text-right text-[13px] text-bad">{explain(all.error)}</p>}
      </SFoot>
      {open && <AllDevices items={items} onClose={() => setOpen(false)} />}
    </SCard>
  )
}

export function Account() {
  const { data: me } = useSession()
  if (!me) return null
  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-8">
      {/* one centred column: the header lines up with the cards under it */}
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
        <PageHeader title="Tài khoản" subtitle="Thông tin của bạn, mật khẩu, xác thực 2 lớp và các thiết bị đang đăng nhập." />
        <Profile />
        <PasswordForm />
        <TwoStep />
        <Devices />
      </div>
    </div>
  )
}
