import { CirclePause, CirclePlay, Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Time } from '../components/Time'
import { Badge, Button, Card, Empty, ErrorBox, Loading, Modal, Notice, PageHeader, STACK_CELL, STACK_ROW } from '../components/ui'
import { num } from '../components/format'
import { adminProblem, useCreateTenant, usePauseAll, useTenants, type NewTenantResult } from './api'
import { AI_LABEL, codeInput, input } from './bits'

function CreateTenant({ onClose }: { onClose: () => void }) {
  const create = useCreateTenant()
  const [f, setF] = useState({ name: '', timezone: 'Asia/Ho_Chi_Minh', owner_email: '', owner_name: '' })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const done: NewTenantResult | undefined = create.data
  return (
    <Modal title="Tạo doanh nghiệp" onClose={onClose} wide>
      {done ? (
        <div className="flex flex-col gap-3">
          {done.owner?.mail_sent && <Notice tone="ok">Đã tạo doanh nghiệp và gửi thư mời tới {done.owner.email}. Người đó mở liên kết trong thư để tự chọn mật khẩu.</Notice>}
          {done.owner && !done.owner.mail_sent && <Notice tone="warn">Đã tạo doanh nghiệp và tài khoản chủ, nhưng thư mời tới {done.owner.email} chưa gửi được. Mở doanh nghiệp để gửi lại.</Notice>}
          {done.owner_error && <Notice tone="warn">Đã tạo doanh nghiệp nhưng chưa mời được chủ: {done.owner_error.message} Mở doanh nghiệp để mời một chủ khác.</Notice>}
          <div className="flex justify-end gap-2"><Button onClick={onClose}>Đóng</Button><Link to={`/admin/tenants/${done.id}`}><Button variant="primary">Mở doanh nghiệp</Button></Link></div>
        </div>
      ) : (
        <form className="flex flex-col gap-3" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate({ ...f, name: f.name.trim(), owner_email: f.owner_email.trim(), owner_name: f.owner_name.trim() }) }}>
          <p className="text-[13px] text-ink-2">Doanh nghiệp được tạo kèm đủ sandbox (AI ở chế độ duyệt tay). Chủ đầu tiên nhận thư mời để tự chọn mật khẩu: không ai khác thấy mật khẩu đó.</p>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Tên doanh nghiệp<input autoFocus value={f.name} onChange={set('name')} className={input} placeholder="Trung tâm Anh ngữ ABC" /></label>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Múi giờ<input value={f.timezone} onChange={set('timezone')} className={`${input} font-mono`} /></label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Họ tên chủ<input value={f.owner_name} onChange={set('owner_name')} className={input} /></label>
            <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Email chủ<input type="email" value={f.owner_email} onChange={set('owner_email')} className={input} placeholder="chu@trungtam.vn" /></label>
          </div>
          {create.isError && <p role="alert" className="text-[13px] text-bad">{adminProblem(create.error)}</p>}
          <div className="flex justify-end gap-2"><Button type="button" onClick={onClose}>Huỷ</Button>
            <Button variant="primary" type="submit" busy={create.isPending} disabled={f.name.trim().length < 2 || f.owner_name.trim().length < 2 || !f.owner_email.includes('@')}>Tạo và gửi thư mời</Button></div>
        </form>
      )}
    </Modal>
  )
}

/** Every business at once: for an incident. Needs the code the admin's phone shows now. */
function PauseAll({ paused, onClose }: { paused: boolean; onClose: () => void }) {
  const run = usePauseAll()
  const [code, setCode] = useState('')
  return (
    <Modal title={paused ? 'Tạm dừng AI của mọi doanh nghiệp' : 'Cho AI của mọi doanh nghiệp chạy lại'} onClose={onClose}>
      {run.data ? (
        <div className="flex flex-col gap-3">
          <Notice tone="ok">Xong: {run.data.tenants} doanh nghiệp, {run.data.sandboxes_changed} sandbox đổi trạng thái. Mỗi doanh nghiệp có một dòng trong nhật ký của họ.</Notice>
          <div className="flex justify-end"><Button onClick={onClose}>Đóng</Button></div>
        </div>
      ) : (
        <form className="flex flex-col gap-3" onSubmit={(e: FormEvent) => { e.preventDefault(); run.mutate({ paused, code }) }}>
          <p className="text-[13px] text-ink-2">{paused
            ? 'AI ngừng soạn và gửi ở mọi doanh nghiệp; tin đang chờ gửi bị huỷ. Nhân viên vẫn tự trả lời khách được.'
            : 'AI chạy lại ở mọi sandbox, kể cả sandbox mà chủ doanh nghiệp đã tự dừng trước đó.'}</p>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Mã 6 số trong ứng dụng xác thực của bạn
            <input autoFocus inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} className={codeInput} placeholder="123456" /></label>
          {run.isError && <p role="alert" className="text-[13px] text-bad">{adminProblem(run.error)}</p>}
          <div className="flex justify-end gap-2"><Button type="button" onClick={onClose}>Huỷ</Button>
            <Button variant={paused ? 'dangerSolid' : 'primary'} type="submit" busy={run.isPending} disabled={!/^\d{6}$/.test(code)}>{paused ? 'Tạm dừng tất cả' : 'Cho chạy lại tất cả'}</Button></div>
        </form>
      )}
    </Modal>
  )
}

export function Tenants() {
  const { data, isPending, isError, refetch } = useTenants()
  const [creating, setCreating] = useState(false)
  const [all, setAll] = useState<boolean | null>(null)
  return (
    <>
      <PageHeader title="Doanh nghiệp" subtitle="Mọi doanh nghiệp trên máy chủ này. Trang này chỉ thấy số đếm và tài khoản, không thấy khách hay hội thoại."
        action={<div className="flex flex-wrap gap-2">
          <Button variant="danger" onClick={() => setAll(true)}><CirclePause className="size-4" aria-hidden />Dừng tất cả</Button>
          <Button onClick={() => setAll(false)}><CirclePlay className="size-4" aria-hidden />Chạy lại tất cả</Button>
          <Button variant="primary" onClick={() => setCreating(true)}><Plus className="size-4" aria-hidden />Tạo doanh nghiệp</Button></div>} />
      <Card className="overflow-x-auto">
        {isPending ? <Loading /> : isError ? <ErrorBox onRetry={() => refetch()} /> : !data.items.length ? <Empty>Chưa có doanh nghiệp nào. Bấm «Tạo doanh nghiệp» để mở doanh nghiệp đầu tiên.</Empty> : (
          <table className="w-full border-collapse text-left text-[13px] max-md:block">
            <thead className="max-md:hidden"><tr className="text-xs text-ink-2">{['Doanh nghiệp', 'AI', 'Tài khoản', 'Hội thoại 7 ngày', 'Đăng nhập gần nhất', 'Tạo lúc'].map((x) => <th key={x} scope="col" className="px-4 py-3 font-semibold">{x}</th>)}</tr></thead>
            <tbody className="max-md:block">
              {data.items.map((t) => {
                const [label, tone] = AI_LABEL[t.ai]
                return (
                  <tr key={t.id} className={`border-t border-line max-md:block ${STACK_ROW}`}>
                    <td data-label="Doanh nghiệp" className={`px-4 py-3 max-md:col-span-2 ${STACK_CELL}`}>
                      <Link to={`/admin/tenants/${t.id}`} className="font-semibold text-accent hover:underline">{t.name}</Link>
                      <div className="text-xs text-ink-3">{t.timezone}</div></td>
                    <td data-label="AI" className={`px-4 py-3 ${STACK_CELL}`}><Badge tone={tone}>{label}</Badge></td>
                    <td data-label="Tài khoản" className={`px-4 py-3 ${STACK_CELL}`}>{num(t.accounts)}
                      {t.owners === 0 ? <Badge tone="bad" className="ml-1.5">Không có chủ</Badge> : t.owners_waiting === t.owners ? <Badge tone="warn" className="ml-1.5">Chủ chưa kích hoạt</Badge> : null}</td>
                    <td data-label="Hội thoại 7 ngày" className={`px-4 py-3 ${STACK_CELL}`}>{num(t.conversations_7d)}</td>
                    <td data-label="Đăng nhập gần nhất" className={`px-4 py-3 ${STACK_CELL}`}>{t.last_login_at ? <Time iso={t.last_login_at} as="when" /> : <span className="text-ink-3">Chưa ai</span>}</td>
                    <td data-label="Tạo lúc" className={`px-4 py-3 ${STACK_CELL}`}><Time iso={t.created_at} as="day" /></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Card>
      {creating && <CreateTenant onClose={() => setCreating(false)} />}
      {all !== null && <PauseAll paused={all} onClose={() => setAll(null)} />}
    </>
  )
}
