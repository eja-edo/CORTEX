import { ArrowLeft, CirclePause, CirclePlay, KeyRound, LogOut, Mail, Pencil, Plus, ShieldOff, Wrench } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Time } from '../components/Time'
import { Badge, Button, Card, ErrorBox, Label, Loading, Menu, Modal, Notice, PageHeader, STACK_CELL, STACK_ROW } from '../components/ui'
import { num } from '../components/format'
import { adminProblem, useEditAccount, useEndSessions, useEnsureSandboxes, useInviteOwner, usePauseTenant, useResetMfa, useSendLink, useTenant, type AdminAccount } from './api'
import { AI_LABEL, codeInput, input } from './bits'

const ROLE: Record<AdminAccount['role'], string> = { owner: 'Chủ', staff: 'Nhân viên', teacher: 'Giáo viên' }

function InviteOwner({ tenantId, onClose }: { tenantId: string; onClose: () => void }) {
  const invite = useInviteOwner(tenantId)
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  return (
    <Modal title="Mời thêm chủ" onClose={onClose}>
      {invite.data ? (
        <div className="flex flex-col gap-3">
          <Notice tone={invite.data.mail_sent ? 'ok' : 'warn'}>{invite.data.mail_sent ? `Đã gửi thư mời tới ${invite.data.email}.` : `Đã tạo tài khoản nhưng thư tới ${invite.data.email} chưa gửi được; bấm «Gửi lại liên kết» ở dòng của người đó.`}</Notice>
          <div className="flex justify-end"><Button onClick={onClose}>Đóng</Button></div>
        </div>
      ) : (
        <form className="flex flex-col gap-3" onSubmit={(e: FormEvent) => { e.preventDefault(); invite.mutate({ email: email.trim(), name: name.trim() }) }}>
          <p className="text-[13px] text-ink-2">Dùng khi doanh nghiệp không còn chủ nào vào được (chủ cũ nghỉ, mất email). Người được mời tự chọn mật khẩu từ liên kết trong thư.</p>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Họ tên<input autoFocus value={name} onChange={(e) => setName(e.target.value)} className={input} /></label>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={input} /></label>
          {invite.isError && <p role="alert" className="text-[13px] text-bad">{adminProblem(invite.error)}</p>}
          <div className="flex justify-end gap-2"><Button type="button" onClick={onClose}>Huỷ</Button>
            <Button variant="primary" type="submit" busy={invite.isPending} disabled={name.trim().length < 2 || !email.includes('@')}>Gửi thư mời</Button></div>
        </form>
      )}
    </Modal>
  )
}

/** Turning off someone's second step: the admin's own code, now (an attacker holding only an admin session gets nowhere). */
function ResetMfa({ tenantId, who, onClose }: { tenantId: string; who: AdminAccount; onClose: () => void }) {
  const reset = useResetMfa(tenantId)
  const [code, setCode] = useState('')
  return (
    <Modal title="Tắt xác thực 2 lớp" onClose={onClose}>
      {reset.data ? (
        <div className="flex flex-col gap-3">
          <Notice tone="ok">Đã tắt xác thực 2 lớp của {who.email}; {reset.data.sessions_ended} thiết bị bị đăng xuất. Người đó nhận thư báo, đăng nhập lại bằng mật khẩu và nên bật lại 2 lớp.</Notice>
          <div className="flex justify-end"><Button onClick={onClose}>Đóng</Button></div>
        </div>
      ) : (
        <form className="flex flex-col gap-3" onSubmit={(e: FormEvent) => { e.preventDefault(); reset.mutate({ userId: who.id, code }) }}>
          <Notice tone="warn">Chỉ làm khi đã xác minh đúng là {who.name} ({who.email}) mất cả điện thoại lẫn mã dự phòng. Việc này được ghi vào nhật ký của doanh nghiệp, kèm tên bạn.</Notice>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Mã 6 số trong ứng dụng xác thực của bạn
            <input autoFocus inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} className={codeInput} placeholder="123456" /></label>
          {reset.isError && <p role="alert" className="text-[13px] text-bad">{adminProblem(reset.error)}</p>}
          <div className="flex justify-end gap-2"><Button type="button" onClick={onClose}>Huỷ</Button>
            <Button variant="dangerSolid" type="submit" busy={reset.isPending} disabled={!/^\d{6}$/.test(code)}>Tắt xác thực 2 lớp</Button></div>
        </form>
      )}
    </Modal>
  )
}

/** Name and sign-in email. Moving the email of an account already in use needs the admin's code: it signs the person out everywhere and
 * the old address is told. An invitation never opened simply goes again to the corrected address. */
function EditAccount({ tenantId, who, onClose }: { tenantId: string; who: AdminAccount; onClose: () => void }) {
  const edit = useEditAccount(tenantId)
  const [name, setName] = useState(who.name)
  const [email, setEmail] = useState(who.email)
  const [code, setCode] = useState('')
  const moving = email.trim().toLowerCase() !== who.email.toLowerCase()
  const needsCode = moving && !who.invited
  const changed = moving || name.trim() !== who.name
  const done = edit.data
  return (
    <Modal title="Sửa tài khoản" onClose={onClose}>
      {done ? (
        <div className="flex flex-col gap-3">
          <Notice tone={done.mail_sent === false ? 'warn' : 'ok'}>
            {!done.email_moved ? 'Đã lưu.'
              : who.invited ? (done.mail_sent ? `Đã đổi email và gửi lại thư mời tới ${done.email}. Liên kết gửi tới địa chỉ cũ không còn dùng được.` : `Đã đổi email sang ${done.email}, nhưng thư mời chưa gửi được; bấm «Gửi lại thư mời».`)
              : `Đã đổi email sang ${done.email}; ${done.sessions_ended} thiết bị bị đăng xuất.${done.mail_sent ? ` Địa chỉ cũ (${who.email}) đã nhận thư báo.` : ' Thư báo tới địa chỉ cũ chưa gửi được.'}`}</Notice>
          <div className="flex justify-end"><Button onClick={onClose}>Đóng</Button></div>
        </div>
      ) : (
        <form className="flex flex-col gap-3" onSubmit={(e: FormEvent) => {
          e.preventDefault()
          edit.mutate({ userId: who.id, ...(name.trim() !== who.name && { name: name.trim() }), ...(moving && { email: email.trim() }), ...(needsCode && { code }) })
        }}>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Họ tên<input autoFocus value={name} onChange={(e) => setName(e.target.value)} className={input} /></label>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Email đăng nhập<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={input} /></label>
          {moving && (who.invited
            ? <Notice tone="neutral">Người này chưa kích hoạt: thư mời sẽ được gửi lại tới địa chỉ mới, liên kết cũ hết hiệu lực.</Notice>
            : <>
              <Notice tone="warn">Tài khoản đang được dùng. Đổi email sẽ đăng xuất người đó ở mọi thiết bị và gửi thư báo tới địa chỉ cũ. Chỉ làm khi đã xác minh đúng là {who.name} yêu cầu.</Notice>
              <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Mã 6 số trong ứng dụng xác thực của bạn
                <input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} className={codeInput} placeholder="123456" /></label>
            </>)}
          {edit.isError && <p role="alert" className="text-[13px] text-bad">{adminProblem(edit.error)}</p>}
          <div className="flex justify-end gap-2"><Button type="button" onClick={onClose}>Huỷ</Button>
            <Button variant="primary" type="submit" busy={edit.isPending}
              disabled={!changed || name.trim().length < 2 || !email.includes('@') || (needsCode && !/^\d{6}$/.test(code))}>Lưu</Button></div>
        </form>
      )}
    </Modal>
  )
}

export function TenantPage() {
  const { id = '' } = useParams()
  const { data: t, isPending, isError, refetch } = useTenant(id)
  const ensure = useEnsureSandboxes(id)
  const pause = usePauseTenant(id)
  const link = useSendLink(id)
  const end = useEndSessions(id)
  const [inviting, setInviting] = useState(false)
  const [mfaFor, setMfaFor] = useState<AdminAccount | null>(null)
  const [editing, setEditing] = useState<AdminAccount | null>(null)
  const [said, setSaid] = useState<{ tone: 'ok' | 'warn' | 'bad'; text: string } | null>(null)
  if (isPending) return <Loading />
  if (isError || !t) return <ErrorBox onRetry={() => refetch()}>Không tải được doanh nghiệp này.</ErrorBox>
  const [aiLabel, aiTone] = AI_LABEL[t.ai]
  const fail = (e: unknown) => setSaid({ tone: 'bad', text: adminProblem(e) })
  const sendLink = (a: AdminAccount) => link.mutate(a.id, {
    onSuccess: (r) => setSaid(r.mail_sent ? { tone: 'ok', text: `Đã gửi liên kết ${r.kind === 'invite' ? 'kích hoạt' : 'đặt lại mật khẩu'} tới ${r.email}.` } : { tone: 'warn', text: `Thư tới ${r.email} chưa gửi được. Kiểm tra cấu hình SMTP rồi thử lại.` }),
    onError: fail })
  const endAll = (a: AdminAccount) => end.mutate(a.id, { onSuccess: (r) => setSaid({ tone: 'ok', text: `Đã đăng xuất ${r.ended} thiết bị của ${a.email}.` }), onError: fail })
  const setAi = (paused: boolean, sandbox_id?: string) => pause.mutate({ paused, sandbox_id }, { onSuccess: () => setSaid(null), onError: fail })
  return (
    <>
      <Link to="/admin" className="inline-flex items-center gap-1 text-[13px] text-ink-2 hover:text-ink"><ArrowLeft className="size-3.5" aria-hidden />Mọi doanh nghiệp</Link>
      <PageHeader title={t.name} subtitle={t.timezone} action={<Badge tone={aiTone}>{aiLabel}</Badge>} />
      <p className="-mt-4 text-[13px] text-ink-2">Tạo ngày <Time iso={t.created_at} as="day" /> · {num(t.accounts)} tài khoản · {num(t.conversations_7d)} hội thoại có tin khách trong 7 ngày</p>
      {said && <Notice tone={said.tone}>{said.text}</Notice>}

      <Card className="flex flex-col gap-3 p-4 sm:p-5">
        <div className="flex flex-wrap items-center gap-2"><Label>Sandbox</Label>
          <div className="ml-auto flex flex-wrap gap-2">
            {t.ai !== 'paused' && <Button variant="danger" busy={pause.isPending} onClick={() => setAi(true)}><CirclePause className="size-4" aria-hidden />Dừng AI của doanh nghiệp</Button>}
            {t.ai !== 'running' && t.ai !== 'none' && <Button busy={pause.isPending} onClick={() => setAi(false)}><CirclePlay className="size-4" aria-hidden />Cho chạy lại tất cả</Button>}
          </div></div>
        {t.sandboxes_missing.length > 0 && (
          <Notice tone="warn" action={<Button busy={ensure.isPending} onClick={() => ensure.mutate(undefined, { onSuccess: (r) => setSaid({ tone: 'ok', text: `Đã thêm ${r.added.length} sandbox.` }), onError: fail })}><Wrench className="size-4" aria-hidden />Bổ sung</Button>}>
            Thiếu {t.sandboxes_missing.length} sandbox mà doanh nghiệp mới đều có ({t.sandboxes_missing.join(', ')}).</Notice>)}
        <ul className="divide-y divide-line">
          {t.sandbox_list.map((sb) => (
            <li key={sb.id} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5 text-[13px]">
              <span className="min-w-0 flex-1 basis-48 font-medium">{sb.title || sb.label} <span className="font-mono text-xs text-ink-3">{sb.purpose}</span></span>
              <Badge tone={sb.send_mode === 'auto' ? 'ai' : 'neutral'}>{sb.send_mode === 'auto' ? 'Tự gửi' : 'Duyệt tay'}</Badge>
              <Badge tone={sb.status === 'active' ? 'ok' : 'bad'}>{sb.status === 'active' ? 'Đang chạy' : 'Tạm dừng'}</Badge>
              <Button className="px-2.5 py-1" disabled={pause.isPending} onClick={() => setAi(sb.status === 'active', sb.id)}>{sb.status === 'active' ? 'Dừng' : 'Chạy lại'}</Button>
            </li>))}
        </ul>
      </Card>

      <Card className="overflow-x-auto">
        <div className="flex flex-wrap items-center gap-2 p-4 pb-2 sm:px-5"><Label>Tài khoản</Label>
          <Button className="ml-auto" onClick={() => setInviting(true)}><Plus className="size-4" aria-hidden />Mời thêm chủ</Button></div>
        {t.owners === 0 && <div className="px-4 pb-2 sm:px-5"><Notice tone="bad">Doanh nghiệp không còn chủ nào đang hoạt động: không ai quản lý được tài khoản và cài đặt. Hãy mời một chủ.</Notice></div>}
        <table className="w-full border-collapse text-left text-[13px] max-md:block">
          <thead className="max-md:hidden"><tr className="text-xs text-ink-2">{['Email', 'Họ tên', 'Vai trò', 'Trạng thái', '2 lớp', 'Đăng nhập gần nhất', 'Thiết bị', ''].map((x) => <th key={x} scope="col" className="px-4 py-3 font-semibold">{x}</th>)}</tr></thead>
          <tbody className="max-md:block">
            {t.account_list.map((a) => (
              <tr key={a.id} className={`border-t border-line max-md:block ${STACK_ROW}`}>
                <td data-label="Email" className={`px-4 py-3 font-medium [overflow-wrap:anywhere] max-md:col-span-2 ${STACK_CELL}`}>{a.email}</td>
                <td data-label="Họ tên" className={`px-4 py-3 ${STACK_CELL}`}>{a.name}</td>
                <td data-label="Vai trò" className={`px-4 py-3 ${STACK_CELL}`}>{ROLE[a.role]}</td>
                <td data-label="Trạng thái" className={`px-4 py-3 ${STACK_CELL}`}>{a.status === 'disabled' ? <Badge tone="bad">Đã khoá</Badge> : a.invited ? <Badge tone="warn">Chưa kích hoạt</Badge> : <Badge tone="ok">Hoạt động</Badge>}</td>
                <td data-label="2 lớp" className={`px-4 py-3 ${STACK_CELL}`}>{a.mfa ? <Badge tone="accent">Bật</Badge> : <span className="text-ink-3">Tắt</span>}</td>
                <td data-label="Đăng nhập gần nhất" className={`px-4 py-3 ${STACK_CELL}`}>{a.last_login_at ? <Time iso={a.last_login_at} as="when" /> : <span className="text-ink-3">Chưa</span>}</td>
                <td data-label="Thiết bị" className={`px-4 py-3 ${STACK_CELL}`}>{num(a.sessions)}</td>
                <td className={`px-4 py-3 text-right max-md:col-span-2 ${STACK_CELL}`}>
                  <Menu label={`Thao tác với ${a.email}`} items={[
                    { label: 'Sửa tên hoặc email', icon: <Pencil className="size-4" aria-hidden />, onClick: () => setEditing(a) },
                    ...(a.status !== 'active' ? [] : [
                    { label: a.invited ? 'Gửi lại thư mời' : 'Gửi liên kết đặt lại mật khẩu', icon: <Mail className="size-4" aria-hidden />, onClick: () => sendLink(a) },
                    ...(a.mfa ? [{ label: 'Tắt xác thực 2 lớp', icon: <ShieldOff className="size-4" aria-hidden />, danger: true, onClick: () => setMfaFor(a) }] : []),
                    ...(a.sessions ? [{ label: 'Đăng xuất mọi thiết bị', icon: <LogOut className="size-4" aria-hidden />, onClick: () => endAll(a) }] : []),
                    ])]} />
                </td>
              </tr>))}
          </tbody>
        </table>
        <p className="flex items-start gap-2 border-t border-line px-4 py-3 text-xs text-ink-3 sm:px-5"><KeyRound className="mt-px size-3.5 shrink-0" aria-hidden />
          Trang quản trị không đặt và không thấy mật khẩu của ai: chỉ gửi liên kết để chính người đó tự chọn. Máy chủ chưa có thư thì dùng <code>cli reset-password</code>.</p>
      </Card>
      {inviting && <InviteOwner tenantId={id} onClose={() => setInviting(false)} />}
      {editing && <EditAccount tenantId={id} who={editing} onClose={() => setEditing(null)} />}
      {mfaFor && <ResetMfa tenantId={id} who={mfaFor} onClose={() => setMfaFor(null)} />}
    </>
  )
}
