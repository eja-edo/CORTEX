import clsx from 'clsx'
import { ArrowLeft, ArrowRight, AudioLines, Plus, ChevronDown, ExternalLink, FileText, Film, Folder, FolderOpen, GraduationCap, Languages, Mic, Search, Sparkles, Trash2, Upload, UserRound, Webhook, X } from 'lucide-react'
import { type DragEvent, type ReactNode, useRef, useState } from 'react'
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { explain } from '../api/client'
import { useAssignments, useClasses, useClassAssignments, useLesson, useLessons, useReleaseLesson, useSession, useUploadLesson } from '../api/hooks'
import type { ClassItem, LessonItem } from '../api/types'
import { can } from '../components/can'
import { Time } from '../components/Time'
import { Badge, Button, Card, Empty, ErrorBox, Label, Loading, Notice, Tabs, type Tone } from '../components/ui'
import { AssignmentBody, Compose, Draft } from './Assignments'
import { ClassroomCourses } from './ClassroomCourses'
import { ClassActions, DeleteLessonDialog, RelinkDialog } from './Classes'

const TONE: Record<LessonItem['status'], Tone> = { queued: 'neutral', working: 'accent', done: 'ok', failed: 'bad' }
const ACCEPT = 'video/*,audio/*,.mp4,.mov,.webm,.mkv,.mp3,.m4a,.wav,.ogg'
const LANG: Record<string, string> = { vi: 'Tiếng Việt', en: 'Tiếng Anh', auto: 'Tự nhận ra' }
const SUFFIXES = ['.mp4', '.mov', '.webm', '.mkv', '.mp3', '.m4a', '.wav', '.ogg']
const sizeOf = (bytes: number) => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(bytes >= 10485760 ? 0 : 1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`)
const isVideo = (name: string) => /\.(mp4|mov|webm|mkv)$/i.test(name)
const plain = (s: string) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd')
const limitOf = (mb: number) => (mb >= 1024 ? `${mb / 1024} GB` : `${mb} MB`)

/**
 * Puts a recording in this class's Drive folder. Nothing is processed here: the watcher finds the file and summarises it, like any other.
 * `hero` is the whole page's job while the class has no file yet; `compact` is a strip over the file list afterwards.
 */
function UploadBox({ maxMb, classId, hero }: { maxMb: number; classId: string; hero?: boolean }) {
  const up = useUploadLesson()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [language, setLanguage] = useState('vi')
  const [sent, setSent] = useState<string | null>(null)
  const [percent, setPercent] = useState(0)
  const [over, setOver] = useState(false)
  const tooBig = !!file && file.size > maxMb * 1024 * 1024
  const clear = () => { setFile(null); if (input.current) input.current.value = '' }
  const choose = (f: File | null) => { setFile(f); setSent(null); up.reset() }
  const send = () => file && up.mutate({ file, language, classId, onProgress: setPercent }, { onSuccess: (r) => { clear(); setPercent(0); setSent(r.name) } })
  const drop = (e: DragEvent) => {
    e.preventDefault(); setOver(false)
    const f = e.dataTransfer.files[0]
    if (f && !up.isPending && SUFFIXES.some((x) => f.name.toLowerCase().endsWith(x))) choose(f)
  }
  const limit = `mp4, mov, webm, mkv, mp3, m4a, wav, ogg · tối đa ${limitOf(maxMb)}`
  const language_ = (
    <label className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] text-ink-2"><Languages className="size-4 shrink-0" aria-hidden />
      <select value={language} onChange={(e) => setLanguage(e.target.value)} disabled={up.isPending} aria-label="Ngôn ngữ bản ghi" className="bg-transparent font-medium text-ink disabled:opacity-50">
        {Object.entries(LANG).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>)
  const chosen = file && (
    <div className="flex w-full items-center gap-3 text-left">
      <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">{isVideo(file.name) ? <Film className="size-5" aria-hidden /> : <Mic className="size-5" aria-hidden />}</span>
      <span className="min-w-0 flex-1"><b className="block truncate text-sm">{file.name}</b><span className="text-xs text-ink-2">{sizeOf(file.size)}</span></span>
      {!up.isPending && <button type="button" onClick={clear} aria-label="Bỏ tệp đã chọn" className="grid size-8 place-items-center rounded-lg text-ink-3 hover:bg-surface hover:text-ink"><X className="size-4" aria-hidden /></button>}
    </div>)
  const sendRow = (
    <div className="flex flex-wrap items-center gap-2">
      {language_}
      <Button variant="primary" busy={up.isPending} disabled={!file || tooBig} onClick={send} className="py-2">{up.isPending ? `Đang tải lên ${percent}%` : 'Tải lên Drive'}</Button>
    </div>)
  const dropProps = { onDragOver: (e: DragEvent) => { e.preventDefault(); if (!up.isPending) setOver(true) }, onDragLeave: () => setOver(false), onDrop: drop }
  return (
    <div className={clsx('flex flex-col gap-3', hero && 'items-center gap-8')}>
      <input ref={input} id="lesson-file" type="file" accept={ACCEPT} aria-label="Chọn bản ghi" disabled={up.isPending} onChange={(e) => choose(e.target.files?.[0] ?? null)} className="sr-only" />
      {hero ? (
        <div {...dropProps} className={clsx('flex w-full max-w-xl flex-col items-center gap-3.5 rounded-2xl border-2 border-dashed p-9 text-center transition-colors', over ? 'border-accent bg-accent-soft' : 'border-accent/50 bg-[#fafaff]')}>
          {file ? <>{chosen}{sendRow}</> : <>
            <span className="grid size-14 place-items-center rounded-full bg-accent-soft text-accent"><Upload className="size-6" aria-hidden /></span>
            <h2 className="text-lg font-bold">Thả bản ghi buổi học vào đây</h2>
            <p className="max-w-md text-[13px] leading-relaxed text-ink-2">Video hoặc âm thanh: {limit}. Tệp được lưu vào thư mục Drive của lớp, Cortex không giữ bản ghi.</p>
            <div className="flex flex-wrap items-center justify-center gap-2.5">
              <label htmlFor="lesson-file" className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-[13px] font-semibold text-white hover:bg-indigo-700"><FolderOpen className="size-4" aria-hidden />Chọn tệp từ máy</label>
              {language_}
            </div></>}
        </div>
      ) : (
        <div {...dropProps} className={clsx('flex flex-col gap-3 rounded-xl border border-dashed p-3 transition-colors', over ? 'border-accent bg-accent-soft' : 'border-line bg-[#fafaff]')}>
          {file ? <>{chosen}{sendRow}</> : (
            <label htmlFor="lesson-file" className="flex cursor-pointer items-center gap-3">
              <span className="grid size-[34px] shrink-0 place-items-center rounded-full bg-accent-soft text-accent"><Upload className="size-4" aria-hidden /></span>
              <span className="min-w-0"><b className="block text-[13px]">Kéo thả bản ghi vào đây hoặc <span className="text-accent underline">chọn tệp</span></b><span className="block text-xs text-ink-3">{limit}</span></span>
            </label>)}
        </div>)}
      {up.isPending && (
        <div className="flex w-full flex-col gap-1.5">
          <div role="progressbar" aria-label="Tiến độ tải lên" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} className="h-1.5 overflow-hidden rounded-full bg-app"><div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${percent}%` }} /></div>
          <p className="text-xs text-ink-3">Đừng đóng trang cho tới khi tải xong. Tệp lớn có thể mất vài phút.</p>
        </div>)}
      {tooBig && <Notice tone="bad">Tệp {Math.round(file!.size / 1048576)} MB vượt giới hạn {maxMb} MB.</Notice>}
      {sent && <Notice tone="ok">Đã lưu «{sent}» vào thư mục của lớp. Vài chục giây nữa nó sẽ hiện trong danh sách và được xử lý.</Notice>}
      {up.isError && <Notice tone="bad">{explain(up.error)}</Notice>}
      {hero && (
        <ol className="grid w-full max-w-xl grid-cols-3 gap-2 text-center">
          {[[Upload, 'Tải lên', 'Bản ghi nằm trong thư mục Drive của lớp'], [AudioLines, 'Chuyển thành chữ', 'Hệ thống tự phiên âm sau vài chục giây'], [Sparkles, 'AI viết tổng kết', 'Tổng kết và bài tập gửi vào webhook của lớp']].map(([Icon, title, hint], i) => {
            const I = Icon as typeof Upload
            return <li key={i} className="flex flex-col items-center gap-1.5 px-2"><span className="grid size-8 place-items-center rounded-full bg-app text-ink-2"><I className="size-4" aria-hidden /></span><b className="text-[13px]">{i + 1}. {title as string}</b><span className="text-xs text-ink-3">{hint as string}</span></li>
          })}
        </ol>)}
    </div>
  )
}

const MediaIcon = ({ item, className }: { item: Pick<LessonItem, 'has_media' | 'media_type'>; className?: string }) =>
  item.has_media ? (item.media_type === 'video' ? <Film className={className} aria-hidden /> : <Mic className={className} aria-hidden />) : <FileText className={className} aria-hidden />

/** What came of one recording: the player, the AI's recap, the homework, and the words of the class. */
function Content({ id, canDelete, onDeleted }: { id: string; canDelete: boolean; onDeleted: () => void }) {
  const q = useLesson(id)
  const [showText, setShowText] = useState(false)
  const [asking, setAsking] = useState(false)
  const release = useReleaseLesson()
  const canRelease = can(useSession().data, 'lessons.release')
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const d = q.data
  const src = `/api/v1/lessons/${d.id}/media`
  return (
    <>
      <header className="flex flex-wrap items-center gap-4 border-b border-line px-6 py-4">
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <h2 className="text-lg leading-snug font-bold break-words">{d.name}</h2>
          <div className="flex flex-wrap gap-1.5"><Badge tone={TONE[d.status]}>{d.status_label}</Badge>{d.language && <Badge>{LANG[d.language] ?? d.language}</Badge>}{d.origin && <Badge>{d.origin}</Badge>}</div>
        </div>
        <div className="flex gap-2">
          {d.video_url && <a href={d.video_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-[13px] font-semibold hover:bg-app"><ExternalLink className="size-3.5" aria-hidden />Mở tệp trong Drive</a>}
          {canDelete && <Button variant="danger" onClick={() => setAsking(true)}><Trash2 className="size-3.5" aria-hidden />Xóa tệp</Button>}
        </div>
      </header>
      <div className="flex flex-col gap-5 p-6">
        {d.has_media && (
          <section aria-label="Xem lại bản ghi" className="overflow-hidden rounded-xl border border-line bg-app">
            {d.media_type === 'video'
              ? <video key={d.id} controls preload="metadata" src={src} className="aspect-video max-h-72 w-full bg-ink" />
              : <audio key={d.id} controls preload="metadata" src={src} className="w-full p-2" />}
          </section>)}
        {d.problem && <Notice tone={d.status === 'failed' ? 'bad' : 'warn'}>{d.problem}{d.status !== 'failed' && ` · đã thử ${d.attempts} lần`}</Notice>}
        {d.awaiting_release && <Notice tone="warn" action={canRelease && <Button variant="primary" busy={release.isPending} onClick={() => release.mutate(d.id)}>Duyệt và gửi</Button>}>
          Tổng kết này đang chờ giáo viên duyệt. Chưa gửi vào kênh Mezon{d.classroom ? ' và chưa đăng lên Google Classroom' : ''}; đọc kỹ rồi bấm «Duyệt và gửi».</Notice>}
        {release.isError && <Notice tone="bad">{explain(release.error)}</Notice>}
        {d.released && d.released_by && d.released_by !== 'auto' && <p className="text-xs text-ink-3">Đã duyệt và gửi bởi {d.released_by}{d.released_at && <> · <Time iso={d.released_at} as="when" /></>}.</p>}
        {d.classroom && d.classroom.state !== 'held' && <Notice tone={d.classroom.state === 'failed' ? 'bad' : d.classroom.state === 'posted' ? 'ok' : 'warn'}>{
          d.classroom.state === 'posted' ? `Đã đăng lên Google Classroom${d.classroom.course ? ` (${d.classroom.course})` : ''}.`
            : d.classroom.state === 'failed' ? `Không đăng được lên Google Classroom: ${d.classroom.error}` : 'Đang chờ đăng lên Google Classroom.'}</Notice>}
        {d.recap ? (
          <>
            <Notice tone="ai">Bản nháp do AI viết từ bản ghi. Giáo viên xem lại trước khi gửi phụ huynh.</Notice>
            <section className="flex flex-col gap-1.5"><Label>Tổng kết</Label><p className="text-[13px] leading-relaxed">{d.recap.summary}</p></section>
            {(d.recap.sections ?? []).length > 0 ? (
              <section className="flex flex-col gap-3"><Label>Nội dung bài giảng</Label>
                <ol className="flex flex-col gap-4">{(d.recap.sections ?? []).map((sec, i) => (
                  <li key={i} className="flex flex-col gap-1.5 rounded-xl border border-line p-4">
                    <h3 className="text-sm font-bold"><span className="mr-1.5 text-accent">{i + 1}.</span>{sec.title}</h3>
                    <ul className="flex list-disc flex-col gap-1.5 pl-5 text-[13px] leading-relaxed marker:text-ink-3">{sec.points.map((p, j) => <li key={j}>{p}</li>)}</ul>
                  </li>))}</ol></section>
            ) : d.recap.topics.length > 0 && <section className="flex flex-col gap-1.5"><Label>Nội dung chính</Label><ul className="flex flex-wrap gap-1.5">{d.recap.topics.map((t, i) => <li key={i}><Badge tone="accent" className="!whitespace-normal text-left">{t}</Badge></li>)}</ul></section>}
            <section className="flex flex-col gap-1.5"><Label>Bài tập về nhà</Label>
              {d.recap.homework.length === 0 ? <p className="text-[13px] text-ink-3">Không có bài tập nào được giao trong bản ghi.</p>
                : <ul className="flex flex-col gap-1.5">{d.recap.homework.map((h, i) => (
                  <li key={i} className="flex items-center gap-2.5 rounded-lg bg-app px-3 py-2.5 text-[13px] leading-snug"><span className="size-3.5 shrink-0 rounded-full border-2 border-ink-3" aria-hidden /><span className="min-w-0 flex-1 font-medium">{h.task}</span>{h.due && <Badge tone="warn">hạn {h.due}</Badge>}</li>))}</ul>}</section>
            {d.recap.class_notes && <section className="flex flex-col gap-1.5"><Label>Nhận xét chung</Label><p className="text-[13px] leading-relaxed">{d.recap.class_notes}</p></section>}
          </>
        ) : !d.problem && <Empty>{d.status === 'working' ? 'Đang chuyển giọng nói thành chữ và viết tổng kết…' : 'Đang chờ tới lượt xử lý.'}</Empty>}
        {d.transcript && (
          <section className="border-t border-line pt-3.5"><button className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent" onClick={() => setShowText(!showText)} aria-expanded={showText}>{showText ? 'Ẩn bản chữ' : `Xem bản chữ (${d.transcript.length.toLocaleString('vi-VN')} ký tự)`}<ChevronDown className={clsx('size-4 transition-transform', showText && 'rotate-180')} aria-hidden /></button>
            {showText && <p className="mt-2 max-h-96 overflow-y-auto rounded-lg bg-app p-3 text-xs leading-relaxed whitespace-pre-wrap text-ink-2">{d.transcript}</p>}</section>)}
      </div>
      {asking && <DeleteLessonDialog id={d.id} name={d.name} onClose={() => setAsking(false)} onDeleted={onDeleted} />}
    </>
  )
}

function Fact({ label, icon, value, sub, last }: { label: string; icon: ReactNode; value: ReactNode; sub?: ReactNode; last?: boolean }) {
  return (
    <div className={clsx('flex min-w-0 flex-col gap-1 px-5', !last && 'xl:border-r xl:border-line')}>
      <span className="text-[11px] font-semibold tracking-wider text-ink-3">{label}</span>
      <span className="flex min-w-0 items-center gap-1.5 text-sm font-semibold"><span className="shrink-0 text-ink-2">{icon}</span><span className="truncate">{value}</span></span>
      {sub && <span className="truncate text-xs text-ink-3">{sub}</span>}
    </div>)
}

function Info({ c }: { c: ClassItem }) {
  const { waiting, failed, done } = c.lessons
  return (
    <Card className="grid gap-y-4 py-4 sm:grid-cols-2 xl:grid-cols-5">
      <Fact label="THƯ MỤC DRIVE" icon={<Folder className="size-[15px]" aria-hidden />} value={c.owned ? c.name : 'Thư mục có sẵn'}
        sub={c.folder_url ? <a href={c.folder_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-accent hover:underline">Mở trong Drive<ExternalLink className="size-3" aria-hidden /></a> : undefined} />
      <Fact label="GOOGLE CLASSROOM" icon={<GraduationCap className={clsx('size-[15px]', c.classroom && 'text-accent')} aria-hidden />} value={c.classroom ? (c.classroom.course ?? 'Lớp Classroom') : 'Chưa nối lớp'}
        sub={c.classroom ? (c.policy.recap_mode === 'auto' ? 'Tổng kết tự đăng khi xong' : 'Tổng kết đăng sau khi giáo viên duyệt') : 'Sửa lớp để chọn lớp Classroom'} />
      <Fact label="WEBHOOK MEZON (TÙY CHỌN)" icon={<Webhook className={clsx('size-[15px]', c.has_webhook && 'text-accent')} aria-hidden />} value={c.has_webhook ? c.webhook : 'Kênh chung'}
        sub={c.has_webhook ? 'Mezon · kênh riêng của lớp' : `Dùng kênh của sandbox ${c.sandbox}`} />
      <Fact label="TÀI KHOẢN GOOGLE" icon={<UserRound className="size-[15px]" aria-hidden />} value={c.account ?? 'Chưa nối tài khoản'} sub={!c.linked ? 'Mất kết nối Google' : c.owned ? 'Cortex tạo thư mục · tải lên được' : 'Thư mục có sẵn · chỉ đọc'} />
      <Fact last label="BUỔI HỌC" icon={<FileText className="size-[15px]" aria-hidden />} value={`${done} xong`} sub={done + waiting + failed === 0 ? 'Chưa có bản ghi nào' : `${waiting} đang chờ · ${failed} lỗi${c.lessons.held ? ` · ${c.lessons.held} chờ duyệt` : ''}`} />
    </Card>
  )
}

function FileRow({ l, on, pick }: { l: LessonItem; on: boolean; pick: (id: string) => void }) {
  return (
    <li><button onClick={() => pick(l.id)} aria-pressed={on}
      className={clsx('flex w-full items-start gap-3 border-b border-l-[3px] border-b-line px-4 py-3 text-left transition-colors', on ? 'border-l-accent bg-accent-soft' : 'border-l-transparent hover:bg-app/70')}>
      <span className={clsx('grid size-9 shrink-0 place-items-center rounded-[9px]', l.status === 'failed' ? 'bg-bad-soft text-bad' : on ? 'bg-surface text-accent' : 'bg-app text-ink-2')}><MediaIcon item={l} className="size-4" /></span>
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <b className="truncate text-[13px]">{l.name}</b>
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-3"><Badge tone={TONE[l.status]}>{l.status_label}</Badge><span>nhận <Time iso={l.created_at} as="when" /></span></span>
        {l.problem && <span className="text-xs text-bad">{l.problem}</span>}
      </span>
    </button></li>)
}

type ClassTab = 'lessons' | 'assignments'

/** The class's pieces of work: Cortex's drafts and the ones made in Classroom, with where their submissions stand. A made one opens its own page. */
function AssignmentsTab({ c }: { c: ClassItem }) {
  const works = useClassAssignments(c.id)
  const drafts = useAssignments(c.id)
  const [composing, setComposing] = useState(false)
  const [picked, setPicked] = useState<string | null>(null)
  const owner = can(useSession().data, 'sources.manage')
  if (!c.can_grade) return owner ? <ClassroomCourses /> : <Notice tone="warn">Lớp này chưa nối khoá học Classroom để chấm bài. Nhờ chủ trung tâm nối ở trang này.</Notice>
  if (works.isPending || drafts.isPending) return <Loading />
  if (works.isError || drafts.isError) return <ErrorBox onRetry={() => { works.refetch(); drafts.refetch() }} />
  const draft = drafts.data.items.find((d) => d.id === picked && d.status === 'draft')
  const made = works.data.items.find((a) => a.id === picked && a.state === 'created')
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <section aria-label="Bài tập của lớp" className="flex min-w-0 flex-col gap-3">
        <div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">Bài tập</h2>
          <Button variant="primary" onClick={() => { setComposing(true); setPicked(null) }}><Plus className="size-4" aria-hidden />Soạn bài tập</Button></div>
        {works.data.items.length === 0 && <Card><Empty>Chưa có bài tập nào. Soạn bài mới, hoặc bài giáo viên tạo trên Classroom sẽ hiện ở đây khi có thang điểm.</Empty></Card>}
        {works.data.items.map((a) => {
          const body = (
            <>
              <div className="flex items-center gap-2"><b className="min-w-0 flex-1 truncate text-sm">{a.title}</b>
                {a.state === 'draft' ? <Badge tone="warn">Bản nháp</Badge> : <Badge tone={a.ours ? 'ok' : 'neutral'}>{a.ours ? 'Cortex tạo' : 'Tạo trên Classroom'}</Badge>}</div>
              <p className="flex flex-wrap items-center gap-1.5 text-xs text-ink-2">
                {a.max_points !== null && <span>{a.max_points} điểm</span>}
                {a.counts.proposed > 0 && <Badge tone="warn">{a.counts.proposed} chờ duyệt</Badge>}
                {a.counts.pending > 0 && <Badge tone="accent">{a.counts.pending} chờ bấm chấm</Badge>}
                {a.counts.approved > 0 && <Badge tone="ok">{a.counts.approved} đã duyệt</Badge>}
                {a.state === 'created' && !a.gradable && <Badge>Chưa có thang điểm</Badge>}
                {a.state === 'created' && a.submissions === 0 && a.gradable && <span className="text-ink-3">Chưa có bài nộp</span>}
              </p>
            </>)
          const cls = `flex flex-col gap-1.5 rounded-xl border bg-surface p-4 text-left hover:border-accent ${picked === a.id ? 'border-accent' : 'border-line'}`
          return <button key={a.id} onClick={() => { setPicked(a.id); setComposing(false) }} aria-pressed={picked === a.id} className={cls}>{body}</button>
        })}
      </section>
      <Card className="self-start p-5 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
        {composing ? <Compose sources={[{ id: c.id, label: c.name }]} onDone={() => setComposing(false)} />
          : draft ? <Draft key={draft.id} d={draft} />
          : made ? (
            <div key={made.id} className="flex flex-col gap-3">
              <div><h2 className="text-base font-bold">{made.title}</h2>
                <div className="mt-1.5 flex flex-wrap gap-1.5"><Badge tone={made.ours ? 'ok' : 'neutral'}>{made.ours ? 'Cortex tạo' : 'Tạo trên Classroom'}</Badge>{made.due && <Badge>Hạn <Time iso={made.due} as="when" /></Badge>}</div></div>
              <Link to={`/classes/${c.id}/assignments/${made.id}`} className="inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2 text-[13px] font-semibold text-white">Mở chi tiết bài tập<ArrowRight className="size-4" aria-hidden />{made.submissions > 0 && <span className="opacity-80">· {made.submissions} học sinh</span>}</Link>
              <AssignmentBody a={made} />
            </div>)
          : <Empty>Chọn một bài tập để xem đề bài, hoặc soạn bài mới.</Empty>}
      </Card>
    </div>
  )
}

export function ClassPage() {
  const { classId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const me = useSession().data
  const classes = useClasses()
  const lessons = useLessons(classId)  // the files of the class, and the upload limit
  const [term, setTerm] = useState('')
  const [relink, setRelink] = useState(false)
  const picked = params.get('file')
  const tab: ClassTab = params.get('tab') === 'assignments' ? 'assignments' : 'lessons'
  const pick = (id: string | null) => setParams(id ? { file: id } : {}, { replace: true })
  const owner = can(me, 'sources.manage')
  if (classes.isPending) return <div className="p-8"><Loading /></div>
  if (classes.isError) return <div className="p-8"><ErrorBox onRetry={() => classes.refetch()} /></div>
  const c = classes.data.items.find((x) => x.id === classId)
  if (!c) return <div className="flex flex-col gap-4 p-8"><Link to="/classes" className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent"><ArrowLeft className="size-4" aria-hidden />Tất cả lớp</Link><Notice tone="warn">Không có lớp này. Có thể nó đã bị xóa.</Notice></div>
  const ready = !!lessons.data && !lessons.isPlaceholderData  // another class's files must not show while this one loads
  const items = ready ? lessons.data!.items : []
  const shown = items.filter((l) => plain(l.name).includes(plain(term.trim())))
  const canUpload = c.can_upload && ready
  const hero = ready && items.length === 0
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-6 lg:px-10 lg:py-7 [&>*]:shrink-0">
      <nav aria-label="Vị trí" className="flex items-center gap-2 text-[13px]">
        <ArrowLeft className="size-3.5 text-ink-2" aria-hidden /><Link to="/classes" className="font-medium text-ink-2 hover:text-accent">Lớp học</Link><span className="text-ink-3">/</span><b>{c.name}</b>
      </nav>
      <header className="flex flex-wrap items-center gap-3.5">
        <span className="grid size-12 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent"><Folder className="size-[22px]" aria-hidden /></span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5"><h1 className="truncate text-2xl font-bold">{c.name}</h1><Badge tone={c.active ? 'ok' : 'neutral'}>{c.active ? 'Đang chạy' : 'Đã tắt'}</Badge></div>
          <p className="mt-1 text-[13px] text-ink-2">Lớp này nhận bản ghi từ thư mục Drive và gửi tổng kết qua webhook bên dưới.</p>
        </div>
        <div className="flex items-center gap-2">
          {owner && <ClassActions c={c} header onDeleted={() => nav('/classes', { replace: true })} />}
          {canUpload && <Button variant="primary" className="py-2.5" onClick={() => document.getElementById('lesson-file')?.click()}><Upload className="size-4" aria-hidden />Tải bản ghi lên</Button>}
        </div>
      </header>
      {!c.linked && <Notice tone="bad" action={owner && <Button variant="primary" onClick={() => setRelink(true)}>Nối lại với Google</Button>}>
        Tài khoản Google của lớp {c.account ? `«${c.account}» đã bị ngắt kết nối` : 'đã bị xóa'}, nên lớp tạm dừng đọc thư mục và tải lên. Các buổi học và tổng kết vẫn được giữ.</Notice>}
      {relink && <RelinkDialog c={c} onClose={() => setRelink(false)} />}
      <Info c={c} />
      <Tabs value={tab} onChange={(t) => setParams(t === 'assignments' ? { tab: t } : {}, { replace: true })} tabs={[
        { id: 'lessons', label: 'Bài giảng', count: c.lessons.done + c.lessons.waiting + c.lessons.failed },
        { id: 'assignments', label: 'Bài tập', count: c.can_grade ? c.grading.assignments : undefined }]} />
      {tab === 'assignments' ? <AssignmentsTab c={c} />
        : !ready && !lessons.isError ? <Loading /> : lessons.isError ? <ErrorBox onRetry={() => lessons.refetch()} /> : hero ? (
        <Card className="flex min-h-96 items-center justify-center p-8">
          {canUpload ? <UploadBox hero maxMb={lessons.data!.max_mb} classId={c.id} />
            : <Notice tone="warn">{c.owned ? 'Chưa tải lên được: lớp đang tắt hoặc tài khoản Google cần kết nối lại.' : 'Thư mục có sẵn chỉ đọc: thả bản ghi vào thư mục trong Drive để nó được tổng kết.'}</Notice>}
        </Card>
      ) : (
        <Card className="grid min-h-[34rem] overflow-hidden lg:grid-cols-[23.75rem_minmax(0,1fr)]">
          <section aria-label="Các tệp của lớp" className="flex min-w-0 flex-col border-line max-lg:border-b lg:border-r">
            <div className="flex flex-col gap-3 p-4">
              <div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">Tệp trong thư mục</h2><Badge>{items.length} tệp</Badge></div>
              <label className="relative block"><Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
                <input type="search" aria-label="Tìm tệp" value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Tìm tệp" className="w-full rounded-lg bg-app py-2 pr-3 pl-9 text-[13px]" /></label>
              {canUpload ? <UploadBox maxMb={lessons.data!.max_mb} classId={c.id} />
                : <Notice tone="warn">{c.owned ? 'Chưa tải lên được: lớp đang tắt hoặc tài khoản Google cần kết nối lại.' : 'Thư mục có sẵn chỉ đọc: thả bản ghi vào thư mục trong Drive để nó được tổng kết.'}</Notice>}
            </div>
            {shown.length === 0 && <p className="p-6 text-center text-[13px] text-ink-3">Không có tệp nào khớp «{term}».</p>}
            <ul className="border-t border-line">{shown.map((l) => <FileRow key={l.id} l={l} on={picked === l.id} pick={pick} />)}</ul>
          </section>
          <div className="min-w-0">
            {picked ? <Content key={picked} id={picked} canDelete={c.owned && can(me, 'lessons.upload')} onDeleted={() => pick(null)} /> : (
              <div className="flex h-full min-h-72 flex-col items-center justify-center gap-2 p-8 text-center">
                <span className="grid size-10 place-items-center rounded-full bg-accent-soft text-accent"><Sparkles className="size-5" aria-hidden /></span>
                <p className="max-w-56 text-[13px] text-ink-3">Chọn một tệp để xem lại bản ghi và đọc tổng kết.</p>
              </div>)}
          </div>
        </Card>)}
    </div>
  )
}

/** A link from a message names one lesson: send the reader to its class with that file open. */
export function LessonLink() {
  const { id = '' } = useParams()
  const q = useLesson(id)
  if (q.isPending) return <div className="p-8"><Loading /></div>
  if (q.isError) return <div className="p-8"><ErrorBox onRetry={() => q.refetch()} /></div>
  return <Navigate to={`/classes/${q.data.class_id}?file=${id}`} replace />
}
