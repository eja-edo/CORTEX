import { Brain, LogOut, Monitor } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { explain } from '../api/client'
import { useChangePassword, useLogoutAll, useLogout, useMySessions, useRevokeSession, useSession } from '../api/hooks'
import { Time } from '../components/Time'
import { Badge, Button, Card, ErrorBox, Label, Loading, Notice, PageHeader } from '../components/ui'

const input = 'rounded-lg border border-line px-3 py-2.5 text-sm font-normal'
const device = (ua: string | null) => {
  const u = ua ?? ''
  const browser = /Edg\//.test(u) ? 'Edge' : /Chrome\//.test(u) ? 'Chrome' : /Firefox\//.test(u) ? 'Firefox' : /Safari\//.test(u) ? 'Safari' : 'Trình duyệt'
  const os = /Windows/.test(u) ? 'Windows' : /Android/.test(u) ? 'Android' : /iPhone|iPad/.test(u) ? 'iOS' : /Mac OS/.test(u) ? 'macOS' : /Linux/.test(u) ? 'Linux' : ''
  return os ? `${browser} · ${os}` : browser
}

export function PasswordForm({ forced }: { forced?: boolean }) {
  const change = useChangePassword()
  const [cur, setCur] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const mismatch = again.length > 0 && again !== next
  const submit = (e: FormEvent) => { e.preventDefault(); change.mutate({ current: cur, new: next }, { onSuccess: () => { setCur(''); setNext(''); setAgain('') } }) }
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold">{forced ? 'Mật khẩu tạm bạn được cấp' : 'Mật khẩu hiện tại'}
        <input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} className={input} /></label>
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Mật khẩu mới
        <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} className={input} />
        <span className="text-xs font-normal text-ink-3">Ít nhất 10 ký tự, có cả chữ và số, không chứa email hay tên của bạn.</span></label>
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Nhập lại mật khẩu mới
        <input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} className={input} /></label>
      {mismatch && <p role="alert" className="text-[13px] text-bad">Hai mật khẩu chưa giống nhau.</p>}
      {change.isError && <p role="alert" className="text-[13px] text-bad">{explain(change.error)}</p>}
      {change.isSuccess && !forced && <Notice tone="ok">Đã đổi mật khẩu.{change.data.other_sessions_ended > 0 ? ` ${change.data.other_sessions_ended} thiết bị khác đã bị đăng xuất.` : ''}</Notice>}
      <Button variant="primary" type="submit" busy={change.isPending} disabled={!cur || next.length < 10 || next !== again}>Đổi mật khẩu</Button>
    </form>
  )
}

/** Shown instead of the whole console until a temporary password has been replaced. */
export function ForcedPassword() {
  const logout = useLogout()
  return (
    <div className="flex h-full items-center justify-center p-6">
      <Card className="w-full max-w-sm p-8">
        <div className="mb-5 flex items-center gap-3"><span className="flex size-10 items-center justify-center rounded-lg bg-accent text-white" aria-hidden><Brain className="size-5" /></span>
          <div><h1 className="text-xl font-bold">Đặt mật khẩu mới</h1><p className="text-xs text-ink-2">Mật khẩu tạm chỉ dùng được một lần.</p></div></div>
        <PasswordForm forced />
        <button onClick={() => logout.mutate()} className="mt-4 flex items-center gap-2 text-xs text-ink-2 hover:text-ink"><LogOut className="size-3.5" aria-hidden />Đăng xuất</button>
      </Card>
    </div>
  )
}

function Sessions() {
  const q = useMySessions()
  const revoke = useRevokeSession()
  const all = useLogoutAll()
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-center justify-between"><h2 className="text-[15px] font-bold">Thiết bị đang đăng nhập</h2>
        <Button variant="danger" busy={all.isPending} onClick={() => all.mutate()}>Đăng xuất khỏi mọi thiết bị</Button></div>
      {q.data.items.map((s) => (
        <div key={s.id} className="flex items-center gap-3 border-t border-line pt-3">
          <Monitor className="size-5 text-ink-3" aria-hidden />
          <div className="min-w-0 flex-1"><p className="text-[13px] font-semibold">{device(s.user_agent)}{s.current && <Badge tone="ok" className="ml-2">Thiết bị này</Badge>}</p>
            <p className="text-xs text-ink-2">{s.ip ?? 'không rõ địa chỉ'} · đăng nhập <Time iso={s.created_at} as="dateTime" /> · hoạt động <Time iso={s.last_seen_at} as="when" /></p></div>
          {!s.current && <Button busy={revoke.isPending} onClick={() => revoke.mutate(s.id)}>Đăng xuất thiết bị này</Button>}
        </div>))}
      {(revoke.isError || all.isError) && <Notice tone="bad">{explain(revoke.error ?? all.error)}</Notice>}
    </Card>
  )
}

export function Account() {
  const { data: me } = useSession()
  if (!me) return null
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-8">
      <PageHeader title="Tài khoản" subtitle="Đăng nhập, mật khẩu và các thiết bị của bạn." />
      <div className="flex max-w-4xl flex-col gap-5">
        <Card className="flex flex-col gap-2 p-5"><Label>Bạn</Label>
          <p className="text-[15px] font-bold">{me.name}</p>
          <p className="text-[13px] text-ink-2">{me.email} · {me.role === 'owner' ? 'Chủ' : 'Nhân viên'} · {me.tenant}</p></Card>
        <Card className="flex max-w-md flex-col gap-3 p-5"><h2 className="text-[15px] font-bold">Đổi mật khẩu</h2><PasswordForm />
          <p className="text-xs text-ink-3">Đổi mật khẩu sẽ đăng xuất mọi thiết bị khác của bạn.</p></Card>
        <Sessions />
      </div>
    </div>
  )
}
