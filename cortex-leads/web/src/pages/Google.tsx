import { CheckCircle2, Minus, Plug, Power, RefreshCw, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { explain } from '../api/client'
import { useConnectGoogle, useDeleteGoogle, useGoogle, useReconnectGoogle, useRevokeGoogle } from '../api/hooks'
import type { GoogleAccount } from '../api/types'
import { Time } from '../components/Time'
import { Badge, Button, Card, ErrorBox, Loading, Menu, Modal, Notice } from '../components/ui'

const input = 'rounded-lg border border-line px-3 py-2.5 text-sm font-normal'
const KIND = { classroom: 'Chấm bài Classroom', classroom_post: 'Đăng tổng kết lên Classroom', drive: 'Drive', drive_read: 'Đọc thư mục Drive' } as const
const BACK_ERRORS: Record<string, string> = {
  BAD_STATE: 'Phiên kết nối đã hết hạn hoặc không hợp lệ. Hãy bấm kết nối lại.', DENIED: 'Bạn đã không đồng ý cấp quyền, nên chưa nối gì.',
  NO_REFRESH_TOKEN: 'Google không trả về mã làm mới. Vào myaccount.google.com/permissions, gỡ quyền của ứng dụng này rồi kết nối lại.',
  LABEL_TAKEN: 'Đã có tài khoản Google tên này. Hãy đặt tên khác.', OTHER_ACCOUNT: 'Bạn đã đăng nhập bằng một tài khoản Google khác. Hãy đăng nhập đúng tài khoản đã nối trước đó, hoặc kết nối tài khoản mới.', EXCHANGE_FAILED: 'Google từ chối mã đăng nhập. Hãy kết nối lại.', NOT_CONFIGURED: 'Máy chủ chưa cấu hình đăng nhập Google.',
}

/** What the redirect from Google left in the address bar. */
function Outcome() {
  const [q, setQ] = useSearchParams()
  const done = q.get('connected'), error = q.get('error'), partial = q.get('partial')
  if (!done && !error) return null
  const close = () => setQ({}, { replace: true })
  const closer = <Button onClick={close}>Đóng</Button>
  return error
    ? <Notice tone="bad" action={closer}>{BACK_ERRORS[error] ?? 'Không kết nối được.'}</Notice>
    : <Notice tone={partial ? 'warn' : 'ok'} action={closer}>Đã kết nối «{done}».{partial && <> Google chưa cấp quyền {partial.split(',').map((k) => KIND[k as keyof typeof KIND] ?? k).join(', ')}: hãy kết nối lại và tick đủ các ô.</>}</Notice>
}

function ConnectForm({ configured }: { configured: boolean }) {
  const connect = useConnectGoogle()
  const [label, setLabel] = useState('')
  const [kinds, setKinds] = useState<Record<string, boolean>>({ classroom: true, classroom_post: true, drive: true, drive_read: true })
  const chosen = Object.keys(kinds).filter((k) => kinds[k])
  const submit = (e: FormEvent) => { e.preventDefault(); connect.mutate({ label: label.trim(), kinds: chosen }, { onSuccess: (r) => window.location.assign(r.url) }) }
  return (
    <Card className="p-5"><form onSubmit={submit} className="flex flex-col gap-3">
      <h2 className="text-[15px] font-bold">Kết nối một tài khoản Google</h2>
      <p className="text-[13px] text-ink-2">Mỗi giáo viên (hoặc tài khoản của trung tâm) kết nối một lần. Cần hai tài khoản khác nhau thì kết nối hai lần, rồi chọn tài khoản nào dùng cho lớp hay Drive nào.</p>
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Tên gọi<input className={input} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Google của cô Lan" /></label>
        <fieldset className="flex flex-col gap-1.5 text-[13px]"><legend className="mb-1.5 font-semibold">Dùng cho</legend>
          <span className="flex flex-wrap gap-4">{(['classroom', 'classroom_post', 'drive', 'drive_read'] as const).map((k) => (
            <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={kinds[k]} onChange={(e) => setKinds({ ...kinds, [k]: e.target.checked })} />
              {k === 'classroom' ? 'Classroom: chấm bài, giao bài' : k === 'classroom_post' ? 'Đăng tổng kết buổi học lên Classroom' : k === 'drive' ? 'Drive: thư mục của lớp, tải bản ghi lên' : 'Đọc thư mục Drive có sẵn (bản ghi Google Meet)'}</label>))}</span></fieldset>
        <Button variant="primary" type="submit" busy={connect.isPending} disabled={!configured || label.trim().length < 2 || chosen.length === 0}><Plug className="size-4" aria-hidden />Đăng nhập bằng Google</Button>
      </div>
      <p className="text-xs text-ink-3">«Drive» chỉ cho Cortex thấy những tệp do chính Cortex tạo. «Đọc thư mục Drive có sẵn» cho Cortex đọc (không sửa) mọi tệp trong Drive của tài khoản này: chỉ tick khi cần theo dõi thư mục bản ghi bạn đã có.</p>
      {connect.isError && <p role="alert" className="text-[13px] text-bad">{explain(connect.error)}</p>}
    </form></Card>
  )
}

/** What an account may be asked to do, in the order the sign-in screen lists it. */
const PERMS = [
  { key: 'classroom', title: 'Chấm bài trên Classroom', hint: 'Đọc lớp và bài nộp, ghi điểm' },
  { key: 'classroom_post', title: 'Đăng tổng kết lên Classroom', hint: 'Đăng thông báo vào lớp' },
  { key: 'drive', title: 'Lưu bản ghi vào Drive', hint: 'Chỉ thấy tệp do Cortex tạo' },
  { key: 'drive_read', title: 'Đọc Drive có sẵn', hint: 'Đọc thư mục bản ghi đã có (Google Meet)' },
] as const

function DeleteAccountDialog({ a, onClose }: { a: GoogleAccount; onClose: () => void }) {
  const del = useDeleteGoogle()
  return (
    <Modal title={`Xóa tài khoản «${a.label}»?`} onClose={onClose}>
      <p className="text-[13px] leading-relaxed text-ink-2">Tài khoản bị xóa hẳn khỏi Cortex và quyền truy cập của nó bị thu hồi ở Google. Dữ liệu trong Google (thư mục, lớp Classroom) không bị đụng tới.</p>
      {a.refs.length > 0 && <Notice tone="warn">{a.refs.length} nguồn đang dùng tài khoản này ({a.refs.map((r) => r.name).join(', ')}) vẫn giữ nguyên dữ liệu nhưng sẽ báo mất kết nối Google. Bạn nối lại với tài khoản khác ngay trong trang của từng nguồn.</Notice>}
      {del.isError && <p role="alert" className="text-xs text-bad">{explain(del.error)}</p>}
      <div className="flex justify-end gap-2"><Button onClick={onClose}>Hủy</Button><Button variant="dangerSolid" busy={del.isPending} onClick={() => del.mutate(a.id, { onSuccess: onClose })}>Xác nhận xóa</Button></div>
    </Modal>
  )
}

function RevokeAccountDialog({ a, onClose }: { a: GoogleAccount; onClose: () => void }) {
  const revoke = useRevokeGoogle()
  return (
    <Modal title={`Ngắt kết nối «${a.label}»?`} onClose={onClose}>
      <p className="text-[13px] leading-relaxed text-ink-2">Quyền truy cập bị thu hồi ở Google. {a.refs.length > 0 ? `${a.refs.length} nguồn đang dùng tài khoản này sẽ dừng (${a.refs.map((r) => r.name).join(', ')}) cho tới khi bạn kết nối lại.` : 'Chưa có nguồn nào đang dùng tài khoản này.'} Tài khoản vẫn còn trong danh sách để kết nối lại bất cứ lúc nào.</p>
      {revoke.isError && <p role="alert" className="text-xs text-bad">{explain(revoke.error)}</p>}
      <div className="flex justify-end gap-2"><Button onClick={onClose}>Hủy</Button><Button variant="dangerSolid" busy={revoke.isPending} onClick={() => revoke.mutate(a.id, { onSuccess: onClose })}>Ngắt kết nối</Button></div>
    </Modal>
  )
}

/** One Google account and what it has been allowed to do: nothing about classes or folders here, only the sign-in and its permissions. */
function Account({ a }: { a: GoogleAccount }) {
  const reconnect = useReconnectGoogle()
  const [dialog, setDialog] = useState<'revoke' | 'delete' | null>(null)
  const off = a.status === 'revoked'
  const missing = PERMS.filter((p) => !a.can[p.key])
  return (
    <div role="row" className="flex flex-col gap-4 border-t border-line px-5 py-5 first:border-t-0">
      <div className="flex flex-wrap items-center gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-accent-soft text-sm font-bold text-accent" aria-hidden>{a.label.slice(0, 1).toUpperCase()}</span>
        <span className="min-w-0 flex-1"><b className="block truncate text-sm">{a.label}</b><span className="block truncate text-xs text-ink-2">{a.email ?? 'Không rõ email'} · nối <Time iso={a.connected_at} as="when" /></span></span>
        <Badge tone={off ? 'bad' : 'ok'}>{off ? 'Đã ngắt' : 'Đang kết nối'}</Badge>
        <Button busy={reconnect.isPending} onClick={() => reconnect.mutate({ id: a.id, kinds: ['classroom', 'classroom_post', 'drive', 'drive_read'] }, { onSuccess: (r) => window.location.assign(r.url) })}><RefreshCw className="size-3.5" aria-hidden />Kết nối lại</Button>
        <Menu label="Thêm thao tác" items={[
          ...(off ? [] : [{ label: 'Ngắt kết nối', icon: <Power className="size-4" aria-hidden />, onClick: () => setDialog('revoke') }]),
          { label: 'Xóa tài khoản', icon: <Trash2 className="size-4" aria-hidden />, danger: true, divider: !off, onClick: () => setDialog('delete') }]} />
      </div>
      {off ? <p className="text-[13px] text-ink-2">Tài khoản đã bị ngắt, chưa có quyền nào. Bấm «Kết nối lại» và cho phép để dùng tiếp.</p> : (
        <ul aria-label="Quyền đã cấp" className="grid gap-x-6 gap-y-2.5 sm:grid-cols-2">
          {PERMS.map((p) => {
            const on = a.can[p.key]
            return (
              <li key={p.key} className="flex items-start gap-2.5 text-[13px]">
                <span className={on ? 'mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-ok-soft text-ok' : 'mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-app text-ink-3'}>{on ? <CheckCircle2 className="size-3.5" aria-hidden /> : <Minus className="size-3.5" aria-hidden />}</span>
                <span className="min-w-0"><b className={on ? 'block font-semibold' : 'block font-medium text-ink-3'}>{p.title}</b><span className="block text-xs text-ink-3">{on ? p.hint : 'Chưa cấp'}</span></span>
              </li>)
          })}
        </ul>)}
      {!off && missing.length > 0 && <p className="text-xs text-ink-3">Muốn cấp thêm quyền, bấm «Kết nối lại» và tick đủ các mục ở màn hình Google.</p>}
      {reconnect.isError && <p role="alert" className="text-xs text-bad">{explain(reconnect.error)}</p>}
      {dialog === 'revoke' && <RevokeAccountDialog a={a} onClose={() => setDialog(null)} />}
      {dialog === 'delete' && <DeleteAccountDialog a={a} onClose={() => setDialog(null)} />}
    </div>
  )
}

/** A section of the Settings page: which Google accounts are connected and what each may do. Classes and folders are managed on the Bài giảng page. */
export function GoogleSection() {
  const q = useGoogle()
  return (
    <section aria-labelledby="google-h" className="flex flex-col gap-5">
      <div><h2 id="google-h" className="text-lg font-bold">Kết nối Google</h2>
        <p className="text-[13px] text-ink-2">Các tài khoản Google đã kết nối và quyền mỗi tài khoản đã cấp. Lớp, thư mục Drive và webhook được chọn ở trang Bài giảng.</p></div>
      <Outcome />
      {q.isPending ? <Loading /> : q.isError ? <ErrorBox onRetry={() => q.refetch()} /> : <>
        {!q.data.configured && <Notice tone="warn">Máy chủ chưa được cấu hình để đăng nhập Google. Người quản trị cần đặt <code>CL_GOOGLE_OAUTH_CLIENT_ID</code>, <code>CL_GOOGLE_OAUTH_CLIENT_SECRET</code> và <code>CL_PUBLIC_BASE_URL</code>, rồi đăng ký địa chỉ <code>/api/v1/google/callback</code> trong Google Cloud.</Notice>}
        <Card className="overflow-hidden">
          {q.data.items.length === 0 ? <p className="p-6 text-center text-ink-3">Chưa kết nối tài khoản Google nào.</p> : q.data.items.map((a) => <Account key={a.id} a={a} />)}
        </Card>
        <ConnectForm configured={q.data.configured} />
      </>}
    </section>
  )
}
