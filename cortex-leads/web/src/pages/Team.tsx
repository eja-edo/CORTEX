import { Copy, KeyRound, Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { explain } from '../api/client'
import { useAddMember, useEndMemberSessions, useResetMember, useTeam, useUpdateMember } from '../api/hooks'
import type { Member } from '../api/types'
import { Time } from '../components/Time'
import { Badge, Button, Card, ErrorBox, Loading, Notice, PageHeader } from '../components/ui'

const input = 'rounded-lg border border-line px-3 py-2.5 text-sm font-normal'
const ROLE = { owner: 'Chủ', staff: 'Nhân viên' } as const
type Secret = { email: string; password: string; why: 'new' | 'reset' }

/** The one moment a temporary password exists in clear. It is not stored by the page beyond this box. */
function SecretBox({ s, onClose }: { s: Secret; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  return (
    <Notice tone="warn"><span className="flex flex-col gap-2">
      <b>{s.why === 'new' ? 'Đã tạo tài khoản' : 'Đã đặt lại mật khẩu'} cho {s.email}.</b>
      <span>Mật khẩu tạm <b>chỉ hiện một lần</b>. Gửi cho họ qua kênh riêng; họ phải đặt mật khẩu mới ngay lần đăng nhập đầu.</span>
      <span className="flex items-center gap-2"><code className="rounded bg-surface px-2 py-1 font-mono text-sm" aria-label="Mật khẩu tạm">{s.password}</code>
        <Button onClick={() => { void navigator.clipboard?.writeText(s.password); setCopied(true) }}><Copy className="size-4" aria-hidden />{copied ? 'Đã chép' : 'Chép'}</Button>
        <Button onClick={onClose}>Đã lưu, đóng</Button></span></span></Notice>
  )
}

function AddForm({ onDone }: { onDone: (s: Secret) => void }) {
  const add = useAddMember()
  const [f, setF] = useState({ email: '', name: '', role: 'staff' as 'owner' | 'staff' })
  const submit = (e: FormEvent) => { e.preventDefault(); add.mutate(f, { onSuccess: (r) => { onDone({ email: r.email, password: r.temporary_password, why: 'new' }); setF({ email: '', name: '', role: 'staff' }) } }) }
  return (
    <Card className="p-5"><form onSubmit={submit} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Họ tên<input className={input} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Trần Minh" /></label>
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Email<input type="email" className={input} value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} placeholder="minh@trungtam.vn" /></label>
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Vai trò<select className={input} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as 'owner' | 'staff' })}>
        <option value="staff">Nhân viên: trả lời khách, duyệt nháp</option><option value="owner">Chủ: toàn quyền, gồm quản lý tài khoản</option></select></label>
      <Button variant="primary" type="submit" busy={add.isPending} disabled={f.name.trim().length < 2 || !f.email.includes('@')}><Plus className="size-4" aria-hidden />Thêm tài khoản</Button>
      {add.isError && <p role="alert" className="w-full text-[13px] text-bad">{explain(add.error)}</p>}
    </form></Card>
  )
}

function Row({ u, onSecret }: { u: Member; onSecret: (s: Secret) => void }) {
  const upd = useUpdateMember()
  const reset = useResetMember()
  const end = useEndMemberSessions()
  const [ask, setAsk] = useState<'reset' | 'disable' | null>(null)
  const off = u.status === 'disabled'
  const err = upd.error ?? reset.error ?? end.error
  return (
    <div role="row" className="flex flex-col gap-2 border-t border-line px-4 py-3">
      <div className="flex items-center gap-3">
        <span className="min-w-0 flex-1"><b className="block truncate text-sm">{u.name}{u.you && <span className="ml-2 text-xs font-normal text-ink-3">(bạn)</span>}</b><span className="block truncate text-xs text-ink-2">{u.email}</span></span>
        <span className="w-24"><Badge tone={u.role === 'owner' ? 'ai' : 'neutral'}>{ROLE[u.role]}</Badge></span>
        <span className="w-32"><Badge tone={off ? 'bad' : u.must_change_password ? 'warn' : 'ok'}>{off ? 'Đã khoá' : u.must_change_password ? 'Chưa đặt mật khẩu' : 'Đang dùng'}</Badge></span>
        <span className="w-36 text-xs text-ink-2">{u.last_login_at ? <>Đăng nhập <Time iso={u.last_login_at} as="when" /></> : 'Chưa đăng nhập'}</span>
        <span className="w-20 text-xs text-ink-2">{u.sessions} thiết bị</span>
      </div>
      {!u.you && <div className="flex flex-wrap items-center gap-2">
        <Button busy={upd.isPending} onClick={() => upd.mutate({ id: u.id, role: u.role === 'owner' ? 'staff' : 'owner' })}>{u.role === 'owner' ? 'Hạ xuống nhân viên' : 'Nâng lên chủ'}</Button>
        {!off && <Button disabled={u.sessions === 0} busy={end.isPending} onClick={() => end.mutate(u.id)}>Đăng xuất mọi thiết bị</Button>}
        {ask === 'reset' ? <><span className="text-xs">Đặt lại mật khẩu của {u.name}?</span><Button variant="primary" busy={reset.isPending} onClick={() => reset.mutate(u.id, { onSuccess: (r) => { onSecret({ email: r.email, password: r.temporary_password, why: 'reset' }); setAsk(null) } })}>Đặt lại</Button><Button onClick={() => setAsk(null)}>Không</Button></>
          : <Button onClick={() => setAsk('reset')}><KeyRound className="size-4" aria-hidden />Đặt lại mật khẩu</Button>}
        {off ? <Button variant="primary" busy={upd.isPending} onClick={() => upd.mutate({ id: u.id, status: 'active' })}>Mở lại tài khoản</Button>
          : ask === 'disable' ? <><span className="text-xs">Khoá {u.name} và đăng xuất họ ngay?</span><Button variant="dangerSolid" busy={upd.isPending} onClick={() => upd.mutate({ id: u.id, status: 'disabled' }, { onSettled: () => setAsk(null) })}>Khoá</Button><Button onClick={() => setAsk(null)}>Không</Button></>
            : <Button variant="danger" onClick={() => setAsk('disable')}>Khoá tài khoản</Button>}
      </div>}
      {err && <p role="alert" className="text-xs text-bad">{explain(err)}</p>}
    </div>
  )
}

export function Team() {
  const q = useTeam()
  const [secret, setSecret] = useState<Secret | null>(null)
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-8">
      <PageHeader title="Nhân viên & quyền" subtitle="Mỗi người một tài khoản riêng, để nhật ký ghi đúng ai làm gì. Khoá một tài khoản là họ ra khỏi hệ thống ngay." />
      {secret && <SecretBox s={secret} onClose={() => setSecret(null)} />}
      <AddForm onDone={setSecret} />
      <Card className="overflow-hidden">
        {q.isPending ? <Loading /> : q.isError ? <ErrorBox onRetry={() => q.refetch()} /> : q.data.items.map((u) => <Row key={u.id} u={u} onSecret={setSecret} />)}
      </Card>
      <Card className="flex max-w-3xl flex-col gap-2 p-5 text-[13px] text-ink-2"><h2 className="text-[15px] font-bold text-ink">Hai vai trò</h2>
        <p><b className="text-ink">Nhân viên:</b> xem hộp thư, duyệt và gửi tin, đặt lịch, soạn nháp kỹ năng, xem nhật ký của chính mình.</p>
        <p><b className="text-ink">Chủ:</b> mọi việc của nhân viên, cộng bật/tắt kỹ năng và công cụ, nguồn dữ liệu, dừng khẩn cấp, AI tổng, toàn bộ nhật ký và tài khoản.</p></Card>
    </div>
  )
}
