import clsx from 'clsx'
import { BookOpen, CheckCircle2, ChevronDown, ExternalLink, FolderOpen, GraduationCap, Plus, Radio } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { explain } from '../api/client'
import { useAddClass, useGoogle, useGoogleCourses, useGoogleFolders } from '../api/hooks'
import type { GoogleAccount, NewClassResult } from '../api/types'
import { Button, Loading, Modal, Notice } from '../components/ui'

const input = 'h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm font-normal'

type Folder = 'new' | 'existing'
type Course = 'new' | 'existing' | 'none'

/** One thing Cortex sets up for the class: an icon, what it is, and the choices for it. */
function Step({ icon, title, desc, children }: { icon: ReactNode; title: string; desc: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-line p-4">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent" aria-hidden>{icon}</span>
        <div className="min-w-0"><h3 className="text-sm font-bold">{title}</h3><p className="text-xs leading-snug text-ink-2">{desc}</p></div>
      </div>
      {children}
    </section>
  )
}

/** A choice as a card: the radio is the whole card, so a click anywhere on it picks it. */
function Choice({ name, label, hint, checked, disabled, onChange }: { name: string; label: string; hint?: string; checked: boolean; disabled?: boolean; onChange: () => void }) {
  return (
    <label className={clsx('flex cursor-pointer items-start gap-2.5 rounded-lg border border-line px-3 py-2.5 text-[13px] has-[:checked]:border-accent has-[:checked]:bg-accent-soft',
      disabled && 'cursor-not-allowed opacity-50')}>
      <input type="radio" name={name} checked={checked} disabled={disabled} onChange={onChange} className="mt-0.5 accent-accent" />
      <span className="min-w-0"><b className="block font-semibold">{label}</b>{hint && <span className="block text-xs text-ink-2">{hint}</span>}</span>
    </label>
  )
}

const Missing = ({ what }: { what: string }) => (
  <p className="text-xs text-warn">{what} <Link to="/settings" className="font-semibold underline">Cấp quyền ở Cài đặt → Kết nối Google</Link> (bấm «Kết nối lại» ở tài khoản này).</p>
)

function Done({ r, hook, onClose }: { r: NewClassResult; hook: boolean; onClose: () => void }) {
  const rows: { text: string; href?: string | null; link?: string }[] = [
    { text: 'Lớp đã được tạo trong Cortex' },
    { text: r.folder_url ? 'Thư mục Drive đã tạo, bản ghi thả vào đây sẽ được tổng kết' : 'Đã theo dõi thư mục Drive', href: r.folder_url, link: 'Mở thư mục' },
    ...(r.classroom ? [{ text: r.classroom.created ? `Lớp «${r.classroom.course}» đã được tạo trên Google Classroom` : `Đã nối lớp Classroom «${r.classroom.course}»`, href: r.classroom.url, link: 'Mở Classroom' }] : []),
    ...(r.grading ? [{ text: 'AI chấm bài đã được nối, giáo viên duyệt điểm trước khi ghi' }] : []),
    ...(hook ? [{ text: 'Kênh Mezon riêng của lớp đã được nối' }] : []),
  ]
  return (
    <div className="flex flex-col gap-4">
      <p className="text-[13px] text-ink-2">Mọi thứ đã sẵn sàng cho lớp <b className="text-ink">{r.name}</b>.</p>
      <ul className="flex flex-col gap-2">
        {rows.map((x) => (
          <li key={x.text} className="flex items-center gap-2.5 rounded-lg bg-ok-soft px-3 py-2.5 text-[13px] text-ok">
            <CheckCircle2 className="size-4 shrink-0" aria-hidden /><span className="min-w-0 flex-1">{x.text}</span>
            {x.href && <a href={x.href} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1 font-semibold underline">{x.link}<ExternalLink className="size-3" aria-hidden /></a>}
          </li>))}
      </ul>
      <div className="flex justify-end gap-2"><Button onClick={onClose}>Đóng</Button><Link to={`/classes/${r.id}`} className="inline-flex items-center rounded-lg bg-accent px-3.5 py-2 text-[13px] font-semibold text-white hover:bg-indigo-700">Mở lớp</Link></div>
    </div>
  )
}

function AddClassForm({ onDone }: { onDone: () => void }) {
  const g = useGoogle()
  const add = useAddClass()
  const [name, setName] = useState('')
  const [account, setAccount] = useState('')
  const [folderKind, setFolderKind] = useState<Folder>('new')
  const [folder, setFolder] = useState('')
  const [courseKind, setCourseKind] = useState<Course | null>(null)
  const [course, setCourse] = useState('')
  const [grade, setGrade] = useState(true)
  const [recap, setRecap] = useState<'review' | 'auto'>('review')
  const [more, setMore] = useState(false)
  const [hook, setHook] = useState('')
  const accounts: GoogleAccount[] = (g.data?.items ?? []).filter((a) => a.status === 'active' && (a.can.drive || a.can.drive_read))
  const acct = accounts.find((a) => a.id === (account || accounts[0]?.id))
  const sandbox = (g.data?.sandboxes ?? []).find((s) => s.purpose === 'lesson_recap')
  const grader = (g.data?.sandboxes ?? []).find((s) => s.purpose === 'classroom_grader')
  const canNewFolder = !!acct?.can.drive, canOldFolder = !!acct?.can.drive_read
  const canNewCourse = !!acct?.can.classroom_create && !!acct?.can.classroom_post, canOldCourse = !!acct?.can.classroom_post
  const folderMode: Folder = folderKind === 'new' && canNewFolder ? 'new' : canOldFolder ? 'existing' : 'new'
  const courseMode: Course = courseKind && (courseKind === 'none' || (courseKind === 'new' ? canNewCourse : canOldCourse)) ? courseKind : canNewCourse ? 'new' : 'none'
  const folders = useGoogleFolders(acct?.id ?? '', folderMode === 'existing' && !!acct)
  const courses = useGoogleCourses(acct?.id ?? '', courseMode === 'existing' && !!acct)
  if (g.isPending) return <Loading />
  if (!accounts.length) return <p className="text-[13px] text-ink-2">Chưa có tài khoản Google nào cấp quyền Drive. Vào <Link to="/settings" className="font-semibold text-accent underline">Cài đặt → Kết nối Google</Link>, kết nối và tick «Drive».</p>
  if (!sandbox) return <p className="text-[13px] text-ink-2">Thiếu việc «Tổng kết buổi học» của AI. Nhờ người hỗ trợ kỹ thuật thêm.</p>
  if (add.isSuccess) return <Done r={add.data} hook={!!hook.trim()} onClose={onDone} />
  const withCourse = courseMode !== 'none'
  const canGrade = !!grader && withCourse && !!acct?.can.classroom
  const ready = name.trim().length >= 2 && (folderMode === 'new' ? canNewFolder : !!folder) && (courseMode !== 'existing' || !!course)
  const picked = courses.data?.items.find((c) => c.id === course)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    add.mutate({
      sandbox_id: sandbox.id, account_id: acct!.id, name: name.trim(), folder: folderMode === 'new' ? 'new' : folder, ...(hook.trim() ? { webhook_url: hook.trim() } : {}),
      ...(courseMode === 'new' ? { classroom_new: true } : {}),
      ...(courseMode === 'existing' ? { classroom_account_id: acct!.id, classroom_course_id: course, classroom_course_name: picked?.name ?? '' } : {}),
      ...(canGrade && grade ? { grade_sandbox_id: grader!.id } : {}), ...(recap === 'auto' ? { recap_mode: 'auto' as const } : {}),
    })
  }
  const will = [folderMode === 'new' ? 'thư mục Drive' : 'theo dõi thư mục Drive', courseMode === 'new' ? 'lớp Classroom mới' : courseMode === 'existing' ? 'nối lớp Classroom' : null, canGrade && grade ? 'AI chấm bài' : null].filter(Boolean)
  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <p className="-mt-2 text-[13px] text-ink-2">Đặt tên lớp, Cortex dựng sẵn mọi thứ còn lại. Không cần sang Drive hay Classroom làm tay.</p>
      <div className={clsx('grid gap-3', accounts.length > 1 && 'sm:grid-cols-2')}>
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Tên lớp<input className={input} autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="IELTS 6.5 - sáng thứ 3" /></label>
        {accounts.length > 1 && <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Tài khoản Google
          <select className={input} value={acct?.id} onChange={(e) => { setAccount(e.target.value); setFolder(''); setCourse('') }}>{accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</select></label>}
      </div>
      {accounts.length === 1 && <p className="-mt-2 text-xs text-ink-3">Dùng tài khoản Google: <b className="text-ink-2">{acct?.label}</b></p>}

      <Step icon={<FolderOpen className="size-[18px]" />} title="Thư mục Drive" desc="Nơi lưu bản ghi buổi học. Cortex đọc bản ghi ở đây để tổng kết.">
        <div role="radiogroup" aria-label="Thư mục Drive" className="grid gap-2 sm:grid-cols-2">
          <Choice name="folder-mode" label="Tạo thư mục mới" hint="Đặt theo tên lớp, tải lên được" checked={folderMode === 'new'} disabled={!canNewFolder} onChange={() => setFolderKind('new')} />
          <Choice name="folder-mode" label="Dùng thư mục có sẵn" hint="Chỉ đọc, ví dụ bản ghi Google Meet" checked={folderMode === 'existing'} disabled={!canOldFolder} onChange={() => setFolderKind('existing')} />
        </div>
        {!canNewFolder && <Missing what="Tài khoản này chưa được cấp quyền tạo thư mục." />}
        {folderMode === 'existing' && (folders.isPending ? <Loading /> : folders.isError ? <p role="alert" className="text-xs text-bad">{explain(folders.error)}</p>
          : <select aria-label="Thư mục có sẵn" className={input} value={folder} onChange={(e) => setFolder(e.target.value)}><option value="">Chọn thư mục…</option>{folders.data.items.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select>)}
      </Step>

      <Step icon={<GraduationCap className="size-[18px]" />} title="Lớp trên Google Classroom" desc="Tổng kết buổi học được đăng vào lớp này, và bài tập của học sinh được chấm ở đây.">
        <div role="radiogroup" aria-label="Lớp Classroom" className="grid gap-2 sm:grid-cols-3">
          <Choice name="course-mode" label="Tạo lớp mới" hint="Cùng tên với lớp" checked={courseMode === 'new'} disabled={!canNewCourse} onChange={() => setCourseKind('new')} />
          <Choice name="course-mode" label="Dùng lớp có sẵn" hint="Chọn từ Classroom" checked={courseMode === 'existing'} disabled={!canOldCourse} onChange={() => setCourseKind('existing')} />
          <Choice name="course-mode" label="Không dùng" hint="Chỉ gửi qua Mezon" checked={courseMode === 'none'} onChange={() => setCourseKind('none')} />
        </div>
        {!canNewCourse && <Missing what={canOldCourse ? 'Tài khoản này chưa được cấp quyền tạo lớp mới.' : 'Tài khoản này chưa được cấp quyền dùng Classroom.'} />}
        {courseMode === 'existing' && (courses.isPending ? <Loading label="Đang lấy danh sách lớp…" /> : courses.isError ? <p role="alert" className="text-xs text-bad">{explain(courses.error)}</p>
          : <select aria-label="Lớp có sẵn" className={input} value={course} onChange={(e) => setCourse(e.target.value)}><option value="">Chọn lớp Classroom…</option>{courses.data.items.map((c) => <option key={c.id} value={c.id}>{c.name}{c.section ? ` · ${c.section}` : ''}</option>)}</select>)}
        {courseMode === 'new' && <p className="text-xs text-ink-3">Lớp sẽ có tên «{name.trim() || '…'}» và bạn là giáo viên. Mời học sinh vào lớp trên Classroom sau.</p>}
        {canGrade && (
          <label className="flex items-start gap-2.5 text-[13px]"><input type="checkbox" className="mt-0.5 size-4 accent-accent" checked={grade} onChange={(e) => setGrade(e.target.checked)} />
            <span><b className="font-semibold">AI chấm bài tập của lớp này</b><span className="block text-xs text-ink-2">AI chỉ đề xuất điểm, giáo viên duyệt thì điểm mới ghi lên Classroom. Đổi được sau ở «Sửa lớp».</span></span></label>)}
      </Step>

      <Step icon={<BookOpen className="size-[18px]" />} title="Khi tổng kết xong" desc="Bản tổng kết buổi học đi vào kênh Mezon và lớp Classroom.">
        <div role="radiogroup" aria-label="Tổng kết buổi học" className="grid gap-2 sm:grid-cols-2">
          <Choice name="recap-mode" label="Chờ giáo viên duyệt" hint="Đọc rồi bấm «Duyệt và gửi»" checked={recap === 'review'} onChange={() => setRecap('review')} />
          <Choice name="recap-mode" label="Tự động gửi" hint="Xong là gửi, không cần duyệt" checked={recap === 'auto'} onChange={() => setRecap('auto')} />
        </div>
      </Step>

      <div className="rounded-xl border border-line">
        <button type="button" aria-expanded={more} onClick={() => setMore(!more)} className="flex w-full items-center gap-2 px-4 py-3 text-left text-[13px] font-semibold">
          <Radio className="size-4 text-ink-3" aria-hidden />Kênh Mezon riêng cho lớp (tuỳ chọn)<ChevronDown className={clsx('ml-auto size-4 text-ink-3 transition-transform', more && 'rotate-180')} aria-hidden /></button>
        {more && (
          <label className="flex flex-col gap-1.5 border-t border-line px-4 py-3 text-[13px] font-semibold">Webhook Mezon của lớp
            <input className={input} value={hook} onChange={(e) => setHook(e.target.value)} placeholder="https://webhook.mezon.ai/..." autoComplete="off" />
            <span className="text-xs font-normal text-ink-3">Tổng kết của lớp này chỉ gửi vào kênh này. Bỏ trống thì dùng kênh chung của sandbox. Địa chỉ này là bí mật, hệ thống chỉ hiển thị tên máy chủ.</span></label>)}
      </div>

      {add.isError && <Notice tone="bad"><span role="alert">{explain(add.error)}</span></Notice>}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <p className="mr-auto min-w-0 text-xs text-ink-2">{ready ? <>Sẽ làm: <b className="text-ink">{will.join(' · ')}</b></> : 'Nhập tên lớp để bắt đầu.'}</p>
        <Button type="button" onClick={onDone}>Hủy</Button>
        <Button variant="primary" type="submit" busy={add.isPending} disabled={!ready}><Plus className="size-4" aria-hidden />Tạo lớp</Button>
      </div>
    </form>
  )
}

export const AddClassDialog = ({ onClose }: { onClose: () => void }) => <Modal title="Thêm lớp" onClose={onClose} wide><AddClassForm onDone={onClose} /></Modal>
