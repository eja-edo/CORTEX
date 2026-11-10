import { Pencil, Power, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { explain } from '../api/client'
import { useDeleteClass, useDeleteLesson, useEditClass, useGoogle, useGoogleCourses, useGoogleFolders, useRelinkClass } from '../api/hooks'
import type { ClassItem, GradingMode, RecapMode } from '../api/types'
import { Button, Loading, Menu, Modal } from '../components/ui'

const input = 'w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm font-normal'

export interface Post { account: string; id: string; name: string }
const noPost: Post = { account: '', id: '', name: '' }

/** Where a recap goes first: a Google Classroom course. Any signed-in account that may post can be used (not only the one that owns the Drive folder).
 * Whether a recap goes out by itself or waits for a teacher is the class's `recap_mode` (Sửa lớp), not a setting of the course. */
function ClassroomPicker({ value, onChange }: { value: Post; onChange: (p: Post) => void }) {
  const g = useGoogle()
  const accounts = (g.data?.items ?? []).filter((a) => a.status === 'active' && a.can.classroom_post)
  const account = value.account || accounts[0]?.id || ''
  const courses = useGoogleCourses(account, !!account)
  if (g.isPending) return <Loading />
  return (
    <fieldset className="flex flex-col gap-1.5 text-[13px]"><legend className="mb-1 font-semibold">Đăng tổng kết lên Google Classroom</legend>
      {accounts.length === 0 ? (
        <p className="text-xs text-ink-3">Chưa có tài khoản Google nào được cấp quyền đăng lên Classroom. <Link to="/settings" className="font-semibold text-accent underline">Kết nối tài khoản Google</Link> và tick «Đăng tổng kết buổi học lên Classroom».</p>
      ) : (
        <>
          {accounts.length > 1 && <select aria-label="Tài khoản đăng" className={input} value={account} onChange={(e) => onChange({ ...noPost, account: e.target.value })}>{accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</select>}
          {courses.isPending ? <Loading /> : courses.isError ? <p role="alert" className="text-bad">{explain(courses.error)}</p> : (
            <select aria-label="Lớp Classroom" className={input} value={value.id}
              onChange={(e) => onChange({ ...value, account, id: e.target.value, name: courses.data.items.find((c) => c.id === e.target.value)?.name ?? '' })}>
              <option value="">Không đăng lên Classroom</option>
              {courses.data.items.map((c) => <option key={c.id} value={c.id}>{c.name}{c.section ? ` · ${c.section}` : ''}</option>)}
            </select>)}
        </>)}
    </fieldset>
  )
}

export { AddClassDialog } from './AddClass'

/** A class whose Google account is gone (deleted or cut off): pick an account and a folder for it again. Its lessons, recaps and webhook stay. */
export function RelinkDialog({ c, onClose }: { c: ClassItem; onClose: () => void }) {
  const g = useGoogle()
  const relink = useRelinkClass()
  const [account, setAccount] = useState('')
  const [mode, setMode] = useState<'new' | 'existing'>('new')
  const [folder, setFolder] = useState('')
  const accounts = (g.data?.items ?? []).filter((a) => a.status === 'active' && (a.can.drive || a.can.drive_read))
  const acct = accounts.find((a) => a.id === (account || accounts[0]?.id))
  const kind = mode === 'new' && acct?.can.drive ? 'new' : acct?.can.drive_read ? 'existing' : 'new'
  const folders = useGoogleFolders(acct?.id ?? '', kind === 'existing' && !!acct)
  return (
    <Modal title={`Nối lại lớp «${c.name}» với Google`} onClose={onClose} wide>
      {g.isPending ? <Loading /> : !accounts.length
        ? <p className="text-[13px] text-ink-2">Chưa có tài khoản Google nào cấp quyền Drive. Vào <Link to="/settings" className="font-semibold text-accent underline">Cài đặt → Kết nối Google</Link> để kết nối, rồi quay lại đây.</p>
        : <>
          <p className="text-[13px] text-ink-2">Các buổi học, tổng kết và webhook của lớp được giữ nguyên. Chọn tài khoản và thư mục Drive mới để lớp chạy lại.</p>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Tài khoản Google<select className={input} value={acct?.id} onChange={(e) => setAccount(e.target.value)}>{accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</select></label>
          <fieldset className="flex flex-col gap-1.5 text-[13px]"><legend className="mb-1 font-semibold">Thư mục lưu bản ghi</legend>
            <label className="flex items-center gap-2"><input type="radio" name="relink-mode" checked={kind === 'new'} disabled={!acct?.can.drive} onChange={() => setMode('new')} />Tạo thư mục mới trong Drive (tải lên được)</label>
            <label className="flex items-center gap-2"><input type="radio" name="relink-mode" checked={kind === 'existing'} disabled={!acct?.can.drive_read} onChange={() => setMode('existing')} />Dùng thư mục có sẵn (chỉ đọc)</label>
            {kind === 'existing' && (folders.isPending ? <Loading /> : folders.isError ? <p role="alert" className="text-bad">{explain(folders.error)}</p>
              : <select aria-label="Thư mục có sẵn" className={input} value={folder} onChange={(e) => setFolder(e.target.value)}><option value="">Chọn thư mục…</option>{folders.data.items.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select>)}
          </fieldset>
          {relink.isError && <p role="alert" className="text-xs text-bad">{explain(relink.error)}</p>}
          <div className="flex justify-end gap-2"><Button onClick={onClose}>Hủy</Button>
            <Button variant="primary" busy={relink.isPending} disabled={!acct || (kind === 'existing' && !folder)} onClick={() => relink.mutate({ id: c.id, account_id: acct!.id, folder: kind === 'new' ? 'new' : folder }, { onSuccess: onClose })}>Nối lại</Button></div>
        </>}
    </Modal>
  )
}

const RECAP_MODES: Record<RecapMode, [string, string]> = {
  auto: ['Tự động gửi', 'Tổng kết xong là gửi vào kênh Mezon và đăng lên Classroom, không cần ai duyệt.'],
  review: ['Chờ duyệt', 'Tổng kết được giữ lại. Giáo viên đọc rồi bấm «Duyệt và gửi» thì mới gửi đi.'],
}
const GRADING_MODES: Record<GradingMode, [string, string]> = {
  manual: ['Thủ công', 'AI chỉ chấm khi giáo viên bấm «Chấm bằng AI». Bài nộp mới chỉ được liệt kê.'],
  review: ['AI chấm, giáo viên duyệt', 'AI đề xuất điểm cho mọi bài nộp mới. Giáo viên duyệt thì điểm mới được ghi lên Classroom.'],
  auto_write: ['AI chấm và tự ghi điểm', 'Bài đạt đủ điều kiện (bài do Cortex tạo, dẫn chứng đều có trong bài, không có lưu ý) được ghi điểm và trả cho học sinh ngay. Bài còn lại vẫn chờ giáo viên.'],
}

/** One automation row of "Sửa lớp": the choice in words and a button that opens a short list to pick another. */
function PolicyRow<T extends string>({ title, options, choices, value, onChange, note, disabled }: { title: string; options: Record<T, [string, string]>; choices?: T[]; value: T; onChange: (v: T) => void; note?: string; disabled?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="flex items-center gap-3 rounded-lg border border-line px-3 py-2.5 text-[13px]">
      <div className="min-w-0 flex-1"><b className="block">{title}</b><span className="block truncate text-xs text-ink-2">{disabled ?? options[value][0]}</span></div>
      <Button type="button" disabled={!!disabled} onClick={() => setOpen(true)} aria-label={`Đổi cách ${title.toLowerCase()}`}>Đổi</Button>
      {open && (
        <Modal title={title} onClose={() => setOpen(false)}>
          <div role="radiogroup" aria-label={title} className="flex flex-col gap-2">
            {(choices ?? (Object.keys(options) as T[])).map((k) => (
              <label key={k} className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-line p-3 text-[13px] has-[:checked]:border-accent has-[:checked]:bg-accent-soft">
                <input type="radio" name={title} checked={value === k} onChange={() => { onChange(k); setOpen(false) }} className="mt-0.5" />
                <span><b className="block">{options[k][0]}</b><span className="text-xs text-ink-2">{options[k][1]}</span></span>
              </label>))}
          </div>
          {note && <p className="text-xs text-ink-3">{note}</p>}
        </Modal>)}
    </div>
  )
}

/** Rename a class, change where its recaps go, and say how much of its work the AI does by itself. A webhook address is a secret: it is only ever written here, and only its host is shown back.
 *  `teacher`: what a teacher may change in their own class. The server refuses the rest; this only does not offer it. */
function EditClassDialog({ c, onClose, teacher }: { c: ClassItem; onClose: () => void; teacher?: boolean }) {
  const edit = useEditClass()
  const [name, setName] = useState(c.name)
  const [hook, setHook] = useState('')
  const [post, setPost] = useState<Post>({ account: c.classroom?.account_id ?? '', id: c.classroom?.course_id ?? '', name: c.classroom?.course ?? '' })
  const [recap, setRecap] = useState<RecapMode>(c.policy.recap_mode)
  const [grading, setGrading] = useState<GradingMode>(c.policy.grading_mode)
  const changedPost = post.id !== (c.classroom?.course_id ?? '')
  const save = () => edit.mutate({ id: c.id, ...(name.trim() !== c.name ? { name: name.trim() } : {}), ...(hook.trim() ? { webhook_url: hook.trim() } : {}),
    ...(changedPost ? { classroom_account_id: post.account, classroom_course_id: post.id, classroom_course_name: post.name } : {}),
    ...(recap !== c.policy.recap_mode ? { recap_mode: recap } : {}), ...(grading !== c.policy.grading_mode ? { grading_mode: grading } : {}) }, { onSuccess: onClose })
  return (
    <Modal title="Sửa lớp" onClose={onClose}>
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Tên lớp<input className={input} value={name} onChange={(e) => setName(e.target.value)} /></label>
      {!teacher && <ClassroomPicker value={post} onChange={setPost} />}
      {!teacher && <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Webhook mới (tuỳ chọn)
        <input className={input} value={hook} onChange={(e) => setHook(e.target.value)} placeholder={c.has_webhook ? 'Dán địa chỉ mới để thay' : 'https://webhook.mezon.ai/...'} autoComplete="off" />
        <span className="text-xs font-normal text-ink-3">{c.has_webhook ? `Đang gửi tới ${c.webhook}. Địa chỉ là bí mật nên chỉ hiện tên máy chủ.` : 'Bỏ trống thì tổng kết đi theo kênh chung của sandbox.'}</span></label>}
      <fieldset className="flex flex-col gap-2"><legend className="mb-1.5 text-[13px] font-semibold">Tự động hóa của lớp</legend>
        <PolicyRow title="Tổng kết bài giảng" options={RECAP_MODES} value={recap} onChange={setRecap} disabled={c.sandbox_id ? undefined : 'Lớp này không tổng kết bài giảng'} />
        <PolicyRow title="Chấm bài tập" options={GRADING_MODES} choices={teacher ? ['manual', 'review'] : undefined} value={grading} onChange={setGrading} disabled={c.can_grade ? undefined : 'Chưa nối khoá học Classroom để chấm bài'}
          note="Điểm được ghi lên Classroom. Nhận xét của AI chỉ lưu ở Cortex để giáo viên xem, học sinh không nhận được nhận xét qua Classroom." />
      </fieldset>
      {edit.isError && <p role="alert" className="text-xs text-bad">{explain(edit.error)}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        {c.has_webhook && !teacher && <Button variant="danger" busy={edit.isPending} onClick={() => edit.mutate({ id: c.id, webhook_url: null }, { onSuccess: onClose })}>Bỏ webhook riêng</Button>}
        <Button onClick={onClose}>Hủy</Button>
        <Button variant="primary" busy={edit.isPending} disabled={name.trim().length < 2} onClick={save}>Lưu</Button>
      </div>
    </Modal>
  )
}

/** A delete that says what goes and what stays, and waits for a second click. */
export function ConfirmDialog({ title, question, busy, error, onConfirm, onClose }: { title: string; question: string; busy?: boolean; error?: string | null; onConfirm: () => void; onClose: () => void }) {
  return (
    <Modal title={title} onClose={onClose}>
      <p className="text-[13px] leading-relaxed text-ink-2">{question}</p>
      {error && <p role="alert" className="text-xs text-bad">{error}</p>}
      <div className="flex justify-end gap-2"><Button onClick={onClose}>Hủy</Button><Button variant="dangerSolid" busy={busy} onClick={onConfirm}>Xác nhận xóa</Button></div>
    </Modal>
  )
}

function DeleteClassDialog({ c, onClose, onDeleted }: { c: ClassItem; onClose: () => void; onDeleted?: () => void }) {
  const del = useDeleteClass()
  const n = c.lessons.done + c.lessons.failed + c.lessons.waiting
  return <ConfirmDialog title={`Xóa lớp «${c.name}»?`} busy={del.isPending} error={del.isError ? explain(del.error) : null} onClose={onClose}
    question={`Lớp${n > 0 ? ` cùng ${n} buổi học (bản chữ, tổng kết)` : ''} sẽ bị xóa khỏi Cortex. Thư mục và tệp trong Drive vẫn được giữ nguyên.`}
    onConfirm={() => del.mutate(c.id, { onSuccess: onDeleted })} />
}

export function DeleteLessonDialog({ id, name, onClose, onDeleted }: { id: string; name: string; onClose: () => void; onDeleted?: () => void }) {
  const del = useDeleteLesson()
  return <ConfirmDialog title={`Xóa «${name}»?`} busy={del.isPending} error={del.isError ? explain(del.error) : null} onClose={onClose}
    question="Tệp được chuyển vào thùng rác của thư mục Drive, bản chữ và tổng kết bị xóa khỏi Cortex."
    onConfirm={() => del.mutate(id, { onSuccess: onDeleted })} />
}

/** A teacher's way into "Sửa lớp" for a class of theirs. */
export function TeacherClassEdit({ c, header }: { c: ClassItem; header?: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      {header
        ? <Button onClick={() => setOpen(true)}><Pencil className="size-3.5" aria-hidden />Sửa</Button>
        : <button type="button" aria-label="Sửa" title="Sửa lớp" onClick={() => setOpen(true)} className="grid size-8 place-items-center rounded-lg text-ink-2 hover:bg-app"><Pencil className="size-4" aria-hidden /></button>}
      {open && <EditClassDialog c={c} teacher onClose={() => setOpen(false)} />}
    </>
  )
}

/** What the owner can do to a class, in one place for the list and for the class page: edit, switch off or on, delete. */
export function ClassActions({ c, header, onDeleted }: { c: ClassItem; header?: boolean; onDeleted?: () => void }) {
  const edit = useEditClass()
  const [dialog, setDialog] = useState<'edit' | 'delete' | null>(null)
  const close = () => setDialog(null)
  return (
    <div className="flex items-center gap-1">
      {header
        ? <Button onClick={() => setDialog('edit')}><Pencil className="size-3.5" aria-hidden />Sửa</Button>
        : <button type="button" aria-label="Sửa" title="Sửa lớp" onClick={() => setDialog('edit')} className="grid size-8 place-items-center rounded-lg text-ink-2 hover:bg-app"><Pencil className="size-4" aria-hidden /></button>}
      <Menu label="Thêm thao tác" items={[
        { label: 'Sửa lớp', icon: <Pencil className="size-4" aria-hidden />, onClick: () => setDialog('edit') },
        { label: c.active ? 'Tắt lớp' : 'Bật lại lớp', icon: <Power className="size-4" aria-hidden />, onClick: () => edit.mutate({ id: c.id, active: !c.active }) },
        { label: 'Xóa lớp', icon: <Trash2 className="size-4" aria-hidden />, danger: true, divider: true, onClick: () => setDialog('delete') }]} />
      {dialog === 'edit' && <EditClassDialog c={c} onClose={close} />}
      {dialog === 'delete' && <DeleteClassDialog c={c} onClose={close} onDeleted={onDeleted} />}
    </div>
  )
}
