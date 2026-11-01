import { ArrowLeft, Search } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { explain } from '../api/client'
import { useAskGrading, useClassAssignments, useGrading } from '../api/hooks'
import type { GradeItem } from '../api/types'
import { Time } from '../components/Time'
import { Badge, Button, Card, Empty, ErrorBox, Loading, Notice, Tabs } from '../components/ui'
import { AssignmentBody } from './Assignments'
import { num, SubmissionDetail, TONE } from './Grading'

type Part = 'brief' | 'students'
type Tab = 'proposed' | 'pending' | 'approved' | 'other' | 'all'
const OTHER = ['skipped', 'failed', 'rejected', 'queued', 'working']

/** One piece of work of a class: the students' submissions on the left, the one picked on the right, where a teacher checks it and decides.
 * What happens to a grade after that is the class's policy (Sửa lớp), not a choice made here. */
export function AssignmentPage() {
  const { classId = '', assignmentId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const picked = params.get('item')
  const works = useClassAssignments(classId)
  const work = works.data?.items.find((a) => a.id === assignmentId)
  const [part, setPart] = useState<Part>(picked ? 'students' : 'brief')
  const [tab, setTab] = useState<Tab>(picked ? 'all' : 'proposed')
  const [term, setTerm] = useState('')
  const q = useGrading(tab === 'other' ? 'all' : tab, { assignmentId })
  const ask = useAskGrading()
  const pick = (id: string | null) => setParams(id ? { item: id } : {}, { replace: true })
  if (works.isPending) return <div className="p-8"><Loading /></div>
  if (works.isError) return <div className="p-8"><ErrorBox onRetry={() => works.refetch()} /></div>
  if (!work) return <div className="flex flex-col gap-4 p-8"><Link to={`/classes/${classId}?tab=assignments`} className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent"><ArrowLeft className="size-4" aria-hidden />Về lớp</Link><Notice tone="warn">Không có bài tập này.</Notice></div>
  const counts = q.data?.counts ?? work.counts
  const needle = term.trim().toLowerCase()
  const items = (q.data?.items ?? []).filter((i) => (tab !== 'other' || OTHER.includes(i.status)) && (!needle || i.student.toLowerCase().includes(needle)))
  const mode = works.data.class.grading_mode
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-6 lg:px-10 lg:py-7 [&>*]:shrink-0">
      <nav aria-label="Vị trí" className="flex items-center gap-2 text-[13px]">
        <ArrowLeft className="size-3.5 text-ink-2" aria-hidden /><Link to="/classes" className="font-medium text-ink-2 hover:text-accent">Lớp học</Link><span className="text-ink-3">/</span>
        <Link to={`/classes/${classId}?tab=assignments`} className="font-medium text-ink-2 hover:text-accent">{works.data.class.name}</Link><span className="text-ink-3">/</span><b>{work.title}</b>
      </nav>
      <header className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-2xl font-bold">{work.title}</h1>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Badge tone={work.ours ? 'ok' : 'neutral'}>{work.ours ? 'Cortex tạo · ghi điểm được' : 'Tạo trên Classroom · chỉ gợi ý điểm'}</Badge>
            {work.max_points !== null && <Badge>{num(work.max_points)} điểm</Badge>}
            {!work.gradable && <Badge tone="warn">Chưa có thang điểm</Badge>}
            {work.due && <Badge>Hạn <Time iso={work.due} as="when" /></Badge>}
          </div>
        </div>
        {work.counts.pending > 0 && <Button variant="primary" busy={ask.all.isPending} onClick={() => ask.all.mutate(work.id)}>Chấm bằng AI cả {work.counts.pending} bài</Button>}
      </header>
      {ask.all.isError && <Notice tone="bad">{explain(ask.all.error)}</Notice>}
      {ask.all.isSuccess && <Notice tone="ok">Đã gửi {ask.all.data.queued} bài cho AI.</Notice>}
      {mode === 'manual' && work.counts.pending === 0 && <Notice tone="ai">Lớp này để chế độ thủ công: bài nộp mới sẽ chờ bạn bấm «Chấm bằng AI».</Notice>}
      {!work.gradable && <Notice tone="warn">Bài tập này chưa có thang điểm nên AI không chấm. Nhờ chủ nhập thang điểm.</Notice>}
      <Tabs value={part} onChange={setPart} tabs={[{ id: 'brief', label: 'Đề bài' }, { id: 'students', label: 'Học sinh', count: work.submissions }]} />
      {part === 'brief' ? <Card className="max-w-3xl p-5"><AssignmentBody a={work} /></Card> : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <label className="relative block w-full max-w-xs"><Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
              <input type="search" aria-label="Tìm học sinh" value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Tìm học sinh" className="w-full rounded-lg border border-line bg-surface py-2 pr-3 pl-9 text-[13px]" /></label>
            <Tabs value={tab} onChange={(t) => { setTab(t); pick(null) }} tabs={[
              { id: 'proposed', label: 'Chờ duyệt', count: counts.proposed }, { id: 'pending', label: 'Chờ bấm chấm', count: counts.pending },
              { id: 'approved', label: 'Đã duyệt', count: counts.approved }, { id: 'other', label: 'Bỏ qua và lỗi', count: counts.skipped + counts.failed + counts.waiting + counts.rejected },
              { id: 'all', label: 'Tất cả' }]} />
          </div>
          {q.isPending ? <Loading /> : q.isError ? <ErrorBox onRetry={() => q.refetch()} /> : (
        <div className="grid min-h-0 gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <div className="flex min-w-0 flex-col gap-3">
            {items.length === 0 && <Card><Empty>{needle ? `Không có học sinh nào khớp «${term.trim()}».` : tab === 'proposed' ? 'Không có bài nào chờ duyệt. Bài nộp mới sẽ hiện ở đây khi AI đã đề xuất điểm.' : 'Không có mục nào.'}</Empty></Card>}
            {items.map((i: GradeItem) => (
              <button key={i.id} onClick={() => pick(i.id)} aria-pressed={picked === i.id} className={`flex flex-col gap-1.5 rounded-xl border bg-surface p-4 text-left ${picked === i.id ? 'border-accent' : 'border-line'}`}>
                <div className="flex items-center gap-2"><b className="min-w-0 flex-1 truncate text-sm">{i.student}</b>{i.total !== null && i.max_points !== null && <span className="text-sm font-bold">{num(i.total)}/{num(i.max_points)}</span>}<Badge tone={TONE[i.status]}>{i.status_label}</Badge></div>
                <p className="flex flex-wrap items-center gap-1.5 text-xs text-ink-2"><Time iso={i.created_at} as="when" />
                  {i.flags.length > 0 && <Badge tone="bad">Bài có câu xin điểm</Badge>}{i.problems > 0 && <Badge tone="warn">{i.problems} lưu ý</Badge>}{i.reason && <span className="text-bad">{i.reason}</span>}</p>
              </button>))}
          </div>
          <Card className="self-start p-5">{picked ? <SubmissionDetail key={picked} id={picked} /> : <Empty>Chọn một bài nộp để xem và duyệt điểm.</Empty>}</Card>
        </div>)}
        </div>)}
    </div>
  )
}
