import { ChevronLeft, ChevronRight, KeyRound, LogOut, Monitor, Plus, Search, ShieldOff, UserCheck, UserX } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { explain } from '../api/client'
import { useAddMember, useClasses, useEndMemberSessions, useSendMemberLink, useSetTeacherClasses, useTeam, useUpdateMember, useTeamMfaOff } from '../api/hooks'
import { Role } from '../api/enums'
import type { Member } from '../api/types'
import { ROLE_LABEL, ROLE_OPTIONS } from '../components/can'
import { Time } from '../components/Time'
import { Avatar, Badge, Button, Card, ErrorBox, Loading, Modal, MultiSelect, Notice, PageHeader, STACK_CELL, STACK_ROW } from '../components/ui'

const input = 'w-full rounded-lg border border-line bg-surface px-3 py-2.5 text-sm font-normal outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft'
const filter = 'rounded-lg border border-line bg-surface px-3 py-2.5 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft'
type Sent = { email: string; mail_sent: boolean; kind: 'invite' | 'reset' }

/** What happened to the mail. The page never holds a password or a link: the person opens the link from their own inbox. */
function SentBox({ s, onClose }: { s: Sent; onClose: () => void }) {
  return (
    <Notice tone={s.mail_sent ? 'ok' : 'warn'}><span className="flex flex-col gap-2">
      {s.mail_sent
        ? <><b>Đã gửi thư {s.kind === 'invite' ? 'mời' : 'đặt lại mật khẩu'} tới {s.email}.</b>
          <span>{s.kind === 'invite' ? 'Họ mở liên kết trong thư để tự chọn mật khẩu rồi đăng nhập. ' : 'Mật khẩu hiện tại vẫn dùng được cho tới khi họ dùng liên kết. '}Nếu chưa thấy, nhờ họ kiểm tra thư mục spam.</span></>
        : <><b>Chưa gửi được thư tới {s.email}.</b><span>Tài khoản đã được tạo nhưng chưa ai vào được. Bấm «Gửi lại lời mời» ở dòng của họ sau khi kiểm tra cấu hình gửi thư.</span></>}
      <span><Button onClick={onClose}>Đóng</Button></span></span></Notice>
  )
}

/** Invites a person. The account is made without a password and a mail with a link goes to them: nobody reads or passes on a password. */
function CreateDialog({ onClose, onDone }: { onClose: () => void; onDone: (s: Sent) => void }) {
  const add = useAddMember()
  const give = useSetTeacherClasses()
  const [f, setF] = useState({ email: '', name: '', role: Role.STAFF as Role })
  const [picked, setPicked] = useState<string[]>([])
  const submit = (e: FormEvent) => {
    e.preventDefault()
    add.mutate(f, { onSuccess: async (r) => {
      if (f.role === Role.TEACHER && picked.length > 0) await give.mutateAsync({ id: r.id, class_ids: picked }).catch(() => undefined)  // the account exists; a failure here is shown and the list can be given from «Sửa»
      onDone({ email: r.email, mail_sent: r.mail_sent, kind: r.kind }); onClose()
    } })
  }
  return (
    <Modal title="Tạo tài khoản" onClose={onClose} wide>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <p className="text-xs text-ink-2">Hệ thống gửi thư mời tới email này; họ tự chọn mật khẩu, bạn không phải biết hay chuyển mật khẩu cho ai.</p>
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Họ tên<input className={input} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Trần Minh" /></label>
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Email<input type="email" className={input} value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} placeholder="minh@trungtam.vn" /></label>
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Vai trò<select className={input} aria-describedby="new-role-can" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
          {ROLE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.text}</option>)}</select></label>
        <RoleHint role={f.role} id="new-role-can" />
        {f.role === Role.TEACHER && <ClassPicker picked={picked} onChange={setPicked} name={f.name.trim()} />}
        {add.isError && <p role="alert" className="text-[13px] text-bad">{explain(add.error)}</p>}
        <div className="flex justify-end gap-2"><Button type="button" onClick={onClose}>Huỷ</Button>
          <Button variant="primary" type="submit" busy={add.isPending || give.isPending} disabled={f.name.trim().length < 2 || !f.email.includes('@')}><Plus className="size-4" aria-hidden />Gửi lời mời</Button></div>
      </form>
    </Modal>
  )
}

/** Which classes a teacher is in charge of. Chosen from a searchable list; saved with the rest of the form, as one list, so two quick changes cannot undo each other. */
function ClassPicker({ picked, onChange, name }: { picked: string[]; onChange: (ids: string[]) => void; name: string }) {
  const classes = useClasses()
  return (
    <div className="flex flex-col gap-2">
      <span className="text-[13px] font-semibold">Lớp phụ trách</span>
      {classes.isPending ? <Loading /> : classes.isError ? <ErrorBox onRetry={() => classes.refetch()} /> : (
        <MultiSelect noun="lớp" addLabel="Thêm lớp" searchLabel="Tìm theo tên lớp…" value={picked} onChange={onChange}
          options={classes.data.items.map((c) => ({ id: c.id, label: c.name, note: c.active ? undefined : 'đã tắt' }))} />)}
      {picked.length === 0 && <span className="text-xs text-ink-2">Chưa chọn lớp nào nên {name || 'giáo viên'} chưa thấy lớp nào.</span>}
    </div>
  )
}

const sameIds = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x))

/** One account: its details as a form, and the things that act on it (send a link, sign out, lock). Opened from the row's «Sửa».
 *  On your own account the role and standing are fixed and nothing signs you out. */
/** Two-step sign-in of someone else: the owner sees whether it is on and, for staff and teachers who lost their phone, turns it off. Nothing
 * secret appears here: the person signs in with their password and sets it up again on their own screen. Inside the edit form, so Enter in
 * the password box must not save the form. */
function MfaOff({ u }: { u: Member }) {
  const turnOff = useTeamMfaOff()
  const [asking, setAsking] = useState(false)
  const [password, setPassword] = useState('')
  const go = () => turnOff.mutate({ id: u.id, password }, { onSuccess: () => { setAsking(false); setPassword('') } })
  return (
    <fieldset className="flex flex-col gap-2.5 rounded-xl border border-line p-4">
      <legend className="px-1.5 text-[13px] font-bold">Xác thực 2 lớp</legend>
      <p className="flex flex-wrap items-center gap-2 text-[13px]">{u.mfa ? <Badge tone="ok">Đang bật</Badge> : <Badge>Đang tắt</Badge>}
        <span className="text-xs text-ink-2">{u.mfa ? 'Họ nhập mã từ điện thoại mỗi lần đăng nhập.' : 'Chỉ chính họ bật được, ở trang Tài khoản của họ.'}</span></p>
      {turnOff.isSuccess && <Notice tone="ok">Đã tắt và đăng xuất mọi thiết bị của {u.name}. Họ đăng nhập lại bằng mật khẩu, rồi tự bật lại nếu muốn.</Notice>}
      {u.mfa && u.role === Role.OWNER && <p className="text-xs text-ink-3">Không tắt được xác thực 2 lớp của một chủ khác ở đây. Nhờ người hỗ trợ kỹ thuật.</p>}
      {u.mfa && u.role !== Role.OWNER && (asking ? (
        <div className="flex flex-col gap-2 rounded-lg bg-warn-soft p-3">
          <p className="text-xs text-ink-2">Dùng khi {u.name} mất điện thoại và mã dự phòng. Họ sẽ bị đăng xuất khỏi mọi thiết bị và nhận thư báo. Nhập <b>mật khẩu của bạn</b> để xác nhận.</p>
          <div className="flex flex-wrap gap-2">
            <input type="password" aria-label="Mật khẩu của bạn" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); if (password) go() } }} className={`${input} min-w-0 flex-1 basis-40`} />
            <Button type="button" variant="dangerSolid" busy={turnOff.isPending} disabled={!password} onClick={go}>Tắt</Button>
            <Button type="button" onClick={() => { setAsking(false); turnOff.reset() }}>Không</Button>
          </div>
          {turnOff.isError && <p role="alert" className="text-xs text-bad">{explain(turnOff.error)}</p>}
        </div>)
        : <span><Button type="button" variant="danger" onClick={() => setAsking(true)}><ShieldOff className="size-4" aria-hidden />Tắt xác thực 2 lớp</Button></span>)}
    </fieldset>
  )
}

function EditDialog({ u, onClose, onSent }: { u: Member; onClose: () => void; onSent: (s: Sent) => void }) {
  const upd = useUpdateMember()
  const reset = useSendMemberLink()
  const end = useEndMemberSessions()
  const start = { name: u.name, email: u.email, role: u.role, phone: u.phone ?? '', birth: u.birth_date ?? '', nid: u.national_id ?? '' }
  const given = u.classes.map((c) => c.id)
  const setClasses = useSetTeacherClasses()
  const [f, setF] = useState(start)
  const [picked, setPicked] = useState(given)
  const [ask, setAsk] = useState<'reset' | 'disable' | null>(null)
  const off = u.status === 'disabled'
  const email = f.email.trim().toLowerCase()
  const classesChanged = f.role === Role.TEACHER && !sameIds(picked, given)
  const dirty = classesChanged || f.name.trim() !== u.name || email !== u.email || f.role !== u.role || f.phone.trim() !== start.phone || f.birth !== start.birth || f.nid.trim() !== start.nid
  const err = upd.error ?? setClasses.error ?? reset.error ?? end.error
  const save = (e: FormEvent) => {
    e.preventDefault()
    const body: Parameters<typeof upd.mutate>[0] = { id: u.id }
    if (f.name.trim() !== u.name) body.name = f.name.trim()
    if (email !== u.email) body.email = f.email.trim()
    if (f.role !== u.role) body.role = f.role
    if (f.phone.trim() !== start.phone) body.phone = f.phone.trim()
    if (f.birth !== start.birth) body.birth_date = f.birth || null
    if (f.nid.trim() !== start.nid) body.national_id = f.nid.trim()
    void (async () => {  // the role first: classes can only be given to someone who already is a teacher
      const r = Object.keys(body).length > 1 ? await upd.mutateAsync(body) : undefined
      if (classesChanged) await setClasses.mutateAsync({ id: u.id, class_ids: picked })
      if (r && body.email && r.mail_sent !== undefined) onSent({ email: r.email, mail_sent: r.mail_sent, kind: 'invite' })
      onClose()
    })().catch(() => undefined)  // a failure is shown under the form from the mutation's own state
  }
  const field = 'flex flex-col gap-1.5 text-[13px] font-semibold'
  return (
    <Modal title="Sửa tài khoản" onClose={onClose} wide>
      <form onSubmit={save} className="flex flex-col gap-3">
        <div className="flex items-center gap-3"><Avatar name={u.name} size={40} active={u.role === Role.OWNER} />
          <span className="flex flex-wrap gap-2"><Badge tone={u.role === Role.OWNER ? 'ai' : 'neutral'}>{ROLE_LABEL[u.role]}</Badge><Badge tone={statusOf(u).tone}>{statusOf(u).text}</Badge></span></div>
        <fieldset className="flex flex-col gap-3 rounded-xl border border-line p-4">
          <legend className="px-1.5 text-[13px] font-bold">Thông tin cá nhân</legend>
          <label className={field}>Họ và tên<input className={input} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          <div className="grid gap-3 md:grid-cols-2">
            <label className={field}>Ngày sinh<input type="date" className={input} value={f.birth} onChange={(e) => setF({ ...f, birth: e.target.value })} /></label>
            <label className={field}>Số CCCD<input inputMode="numeric" className={input} value={f.nid} onChange={(e) => setF({ ...f, nid: e.target.value })} placeholder="12 chữ số" /></label>
            <label className={field}>Email đăng nhập<input type="email" className={input} value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
            <label className={field}>Số điện thoại<input type="tel" className={input} value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} placeholder="0912345678" /></label>
          </div>
          {email !== u.email && <Notice tone="warn">{u.invited ? 'Thư mời sẽ được gửi lại tới địa chỉ mới.' : u.you ? 'Các thiết bị khác của bạn sẽ bị đăng xuất; thiết bị này vẫn đăng nhập. Một thư báo sẽ gửi tới địa chỉ cũ.' : `${u.name} sẽ bị đăng xuất khỏi mọi thiết bị và một thư báo sẽ gửi tới địa chỉ cũ. Mật khẩu của họ không đổi.`}</Notice>}
        </fieldset>
        <fieldset className="flex flex-col gap-3 rounded-xl border border-line p-4">
          <legend className="px-1.5 text-[13px] font-bold">Phân quyền</legend>
          <label className={field}>Vai trò
            <select className={input} aria-describedby="edit-role-can" value={f.role} disabled={u.you} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
              {ROLE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.text}</option>)}</select>
            {u.you && <span className="text-xs font-normal text-ink-3">Bạn không tự đổi vai trò của mình được; nhờ một chủ khác.</span>}</label>
          <RoleHint role={f.role} id="edit-role-can" />
          {f.role === Role.TEACHER && <ClassPicker picked={picked} onChange={setPicked} name={u.name} />}
        </fieldset>
        {!u.you && <MfaOff u={u} />}
        {err && <p role="alert" className="text-xs text-bad">{explain(err)}</p>}
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
          {!u.you && !off && (ask === 'reset' ? <span className="flex flex-wrap items-center gap-2 rounded-lg bg-warn-soft px-3 py-1.5"><span className="text-xs">Gửi thư {u.invited ? 'mời' : 'đặt lại mật khẩu'} tới {u.email}?</span><Button type="button" variant="primary" busy={reset.isPending} onClick={() => reset.mutate(u.id, { onSuccess: (r) => { onSent(r); onClose() } })}>Gửi</Button><Button type="button" onClick={() => setAsk(null)}>Không</Button></span>
            : <Button type="button" onClick={() => setAsk('reset')}><KeyRound className="size-4" aria-hidden />{u.invited ? 'Gửi lại lời mời' : 'Gửi liên kết đặt lại mật khẩu'}</Button>)}
          {!u.you && !off && <Button type="button" disabled={u.sessions === 0} busy={end.isPending} onClick={() => end.mutate(u.id)}><LogOut className="size-4" aria-hidden />Đăng xuất mọi thiết bị</Button>}
          {!u.you && (off ? <Button type="button" variant="primary" busy={upd.isPending} onClick={() => upd.mutate({ id: u.id, status: 'active' })}><UserCheck className="size-4" aria-hidden />Mở lại tài khoản</Button>
            : ask === 'disable' ? <span className="flex flex-wrap items-center gap-2 rounded-lg bg-bad-soft px-3 py-1.5"><span className="text-xs">Khoá {u.name} và đăng xuất họ ngay?</span><Button type="button" variant="dangerSolid" busy={upd.isPending} onClick={() => upd.mutate({ id: u.id, status: 'disabled' }, { onSettled: () => setAsk(null) })}>Khoá</Button><Button type="button" onClick={() => setAsk(null)}>Không</Button></span>
              : <Button type="button" variant="danger" onClick={() => setAsk('disable')}><UserX className="size-4" aria-hidden />Khoá tài khoản</Button>)}
          <span className="ml-auto flex gap-2"><Button type="button" onClick={onClose}>Huỷ</Button>
            <Button variant="primary" type="submit" busy={upd.isPending || setClasses.isPending} disabled={!dirty || f.name.trim().length < 2 || !f.email.includes('@')}>Lưu thay đổi</Button></span>
        </div>
      </form>
    </Modal>
  )
}

const statusOf = (u: Member) => u.status === 'disabled' ? { key: 'disabled', tone: 'bad' as const, text: 'Đã khoá' } : u.invited ? { key: 'invited', tone: 'warn' as const, text: 'Chờ kích hoạt' } : { key: 'active', tone: 'ok' as const, text: 'Đang dùng' }

function classesCell(u: Member) {
  if (u.role !== Role.TEACHER) return <span className="text-ink-3">Tất cả lớp</span>
  if (u.classes.length === 0) return <span className="text-ink-3">Chưa giao lớp</span>
  const shown = u.classes.slice(0, 2).map((c) => c.name).join(', ')
  return <span title={u.classes.map((c) => c.name).join(', ')}>{shown}{u.classes.length > 2 && ` +${u.classes.length - 2}`}</span>
}

function Row({ u, onEdit }: { u: Member; onEdit: () => void }) {
  const s = statusOf(u)
  return (
    <tr role="row" className={`border-t border-line text-sm first:border-t-0 ${STACK_ROW} ${u.status === 'disabled' ? 'bg-app/60 text-ink-2' : ''}`}>
      <td data-label="Email đăng nhập" className={`px-4 py-3 font-mono text-xs max-md:order-1 max-md:[overflow-wrap:anywhere] max-md:col-span-2 ${STACK_CELL}`}>{u.email}</td>
      <td className="px-4 py-3 font-semibold max-md:col-span-2 max-md:p-0">{u.name}{u.you && <span className="ml-2 text-xs font-normal text-ink-3">(bạn)</span>}</td>
      <td data-label="Vai trò" className={`px-4 py-3 max-md:order-2 ${STACK_CELL}`}><Badge tone={u.role === Role.OWNER ? 'ai' : 'neutral'}>{ROLE_LABEL[u.role]}</Badge></td>
      <td data-label="Lớp phụ trách" className={`max-w-56 truncate px-4 py-3 text-[13px] max-md:order-4 max-md:max-w-none ${STACK_CELL}`}>{classesCell(u)}</td>
      <td data-label="Trạng thái" className={`px-4 py-3 max-md:order-3 ${STACK_CELL}`}><Badge tone={s.tone}>{s.text}</Badge></td>
      <td data-label="Đăng nhập gần nhất" className={`px-4 py-3 text-xs text-ink-2 max-md:order-5 ${STACK_CELL}`}>{u.last_login_at ? <Time iso={u.last_login_at} as="when" /> : 'Chưa đăng nhập'}</td>
      <td data-label="Thiết bị" className={`px-4 py-3 text-xs text-ink-2 max-md:order-6 ${STACK_CELL}`}><span className="inline-flex items-center gap-1"><Monitor className="size-3.5" aria-hidden />{u.sessions}</span></td>
      <td className="sticky right-0 bg-surface px-4 py-3 text-right max-md:static max-md:order-7 max-md:col-span-2 max-md:bg-transparent max-md:p-0"><Button className="max-md:w-full" onClick={onEdit}>Sửa</Button></td>
    </tr>
  )
}

const ROLE_CAN: Record<Role, string> = {
  [Role.STAFF]: 'Xem hộp thư, duyệt và gửi tin cho khách, đặt lịch. Không thấy lớp học nào; chỉ xem nhật ký của mình.',
  [Role.TEACHER]: 'Chỉ thấy các lớp được giao: bài giảng, tổng kết, bài tập, chấm bài. Không có hộp thư khách, không đổi được kết nối Google, không bật tự ghi điểm.',
  [Role.OWNER]: 'Mọi việc: mọi lớp, kỹ năng, công cụ, cài đặt, dừng khẩn cấp, toàn bộ nhật ký và tài khoản.',
}
/** Outside the label, tied to the select by `aria-describedby`: the select's name stays «Vai trò». */
const RoleHint = ({ role, id }: { role: Role; id: string }) => <p id={id} className="-mt-1 text-xs leading-snug text-ink-2">{ROLE_CAN[role]}</p>

const SIZES = [10, 20, 50]

export function Team() {
  const q = useTeam()
  const [sent, setSent] = useState<Sent | null>(null)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [role, setRole] = useState<'' | Role>('')
  const [status, setStatus] = useState('')
  const [size, setSize] = useState(10)
  const [page, setPage] = useState(1)
  const items = q.data?.items
  const rows = useMemo(() => {
    const s = search.trim().toLowerCase()
    return (items ?? []).filter((u) => (!s || u.name.toLowerCase().includes(s) || u.email.toLowerCase().includes(s)) && (!role || u.role === role) && (!status || statusOf(u).key === status))
  }, [items, search, role, status])
  const pages = Math.max(1, Math.ceil(rows.length / size))
  const at = Math.min(page, pages)
  const shown = rows.slice((at - 1) * size, at * size)
  const editUser = items?.find((u) => u.id === editing)
  const reset = (fn: () => void) => { fn(); setPage(1) }
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-4 sm:p-6 lg:p-8 [&>*]:shrink-0">
      <PageHeader title="Nhân viên & quyền" subtitle={q.data ? `${q.data.items.length} tài khoản.` : undefined}
        action={<Button variant="primary" onClick={() => setCreating(true)}><Plus className="size-4" aria-hidden />Tạo tài khoản</Button>} />
      {sent && <SentBox s={sent} onClose={() => setSent(null)} />}
      <div className="flex flex-wrap items-center gap-3">
        <label className="relative flex-1 max-sm:basis-full sm:min-w-64 md:max-w-sm"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
          <input aria-label="Tìm tài khoản" className={`${filter} w-full pl-9`} placeholder="Tìm theo tên hoặc email" value={search} onChange={(e) => reset(() => setSearch(e.target.value))} /></label>
        <select aria-label="Lọc theo vai trò" className={filter} value={role} onChange={(e) => reset(() => setRole(e.target.value as '' | Role))}>
          <option value="">Tất cả vai trò</option>{Object.values(Role).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select>
        <select aria-label="Lọc theo trạng thái" className={filter} value={status} onChange={(e) => reset(() => setStatus(e.target.value))}>
          <option value="">Tất cả trạng thái</option><option value="active">Đang dùng</option><option value="invited">Chờ kích hoạt</option><option value="disabled">Đã khoá</option></select>
      </div>
      <Card className="overflow-x-auto">
        {q.isPending ? <Loading /> : q.isError ? <ErrorBox onRetry={() => q.refetch()} /> : (
          <table className="w-full border-collapse text-left max-md:block md:min-w-[880px]">
            <thead className="max-md:hidden"><tr className="text-xs text-ink-2">{['Email đăng nhập', 'Họ tên', 'Vai trò', 'Lớp phụ trách', 'Trạng thái', 'Đăng nhập gần nhất', 'Thiết bị', ''].map((h) => <th key={h} scope="col" className={`px-4 py-3 font-semibold ${h ? '' : 'sticky right-0 bg-surface'}`}>{h}</th>)}</tr></thead>
            <tbody className="max-md:block">{shown.map((u) => <Row key={u.id} u={u} onEdit={() => setEditing(u.id)} />)}
              {shown.length === 0 && <tr><td colSpan={8} className="p-6 text-center text-ink-3">Không có tài khoản nào khớp.</td></tr>}</tbody>
          </table>)}
      </Card>
      {q.data && <div className="flex flex-wrap items-center gap-3 text-[13px] text-ink-2">
        <span>{rows.length === 0 ? 'Không có kết quả' : <>Hiển thị <b>{(at - 1) * size + 1}–{Math.min(at * size, rows.length)}</b> trong tổng <b>{rows.length}</b> kết quả</>}</span>
        <label className="flex items-center gap-2">Số dòng/trang<select aria-label="Số dòng mỗi trang" className={filter} value={size} onChange={(e) => { setSize(Number(e.target.value)); setPage(1) }}>{SIZES.map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
        <nav aria-label="Trang" className="ml-auto flex items-center gap-1">
          <Button aria-label="Trang trước" disabled={at <= 1} onClick={() => setPage(at - 1)}><ChevronLeft className="size-4" aria-hidden /></Button>
          {Array.from({ length: pages }, (_, i) => i + 1).map((n) => <Button key={n} variant={n === at ? 'primary' : 'secondary'} aria-current={n === at ? 'page' : undefined} onClick={() => setPage(n)}>{n}</Button>)}
          <Button aria-label="Trang sau" disabled={at >= pages} onClick={() => setPage(at + 1)}><ChevronRight className="size-4" aria-hidden /></Button>
        </nav>
      </div>}
      {creating && <CreateDialog onClose={() => setCreating(false)} onDone={setSent} />}
      {editUser && <EditDialog key={editUser.id} u={editUser} onClose={() => setEditing(null)} onSent={setSent} />}
    </div>
  )
}
