import clsx from 'clsx'
import { ExternalLink, Folder, GraduationCap, Plus, Search, Webhook } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useClasses, useSession } from '../api/hooks'
import type { ClassItem } from '../api/types'
import { can } from '../components/can'
import { Badge, Button, Card, ErrorBox, Loading, PageHeader } from '../components/ui'
import { AddClassDialog, ClassActions } from './Classes'

const plain = (s: string) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd')
const FILTERS = [['all', 'Tất cả'], ['on', 'Đang chạy'], ['off', 'Đã tắt']] as const
type Filter = (typeof FILTERS)[number][0]
const COLS = 'lg:grid-cols-[minmax(0,1fr)_190px_180px_190px_100px_76px]'

/** "12 xong" with what still needs a look beside it: waiting and failed are the two numbers a teacher acts on. */
function Counts({ c }: { c: ClassItem }) {
  const { done, waiting, failed, held } = c.lessons
  return (
    <span className="flex flex-wrap items-center gap-1.5 text-[13px] text-ink-2">
      <b className="text-sm text-ink">{done}</b> xong
      {held > 0 && <Badge tone="warn">{held} chờ duyệt</Badge>}
      {waiting > 0 && <Badge tone="accent">{waiting} đang chờ</Badge>}
      {failed > 0 && <Badge tone="bad">{failed} lỗi</Badge>}
      {c.can_grade && c.grading.to_review > 0 && <Badge tone="warn">{c.grading.to_review} bài chờ chấm duyệt</Badge>}
    </span>
  )
}

function Row({ c, owner }: { c: ClassItem; owner: boolean }) {
  const hook = c.has_webhook ? c.webhook : null
  return (
    <li className={clsx('relative grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-4 border-b border-line px-5 py-3.5 transition-colors last:border-b-0 hover:bg-app/60', COLS)}>
      <div className="flex min-w-0 items-center gap-3">
        <span className={clsx('grid size-9.5 shrink-0 place-items-center rounded-[10px]', c.active ? 'bg-accent-soft text-accent' : 'bg-app text-ink-3')}><Folder className="size-[18px]" aria-hidden /></span>
        <div className="min-w-0">
          <b className={clsx('block truncate text-sm', !c.active && 'text-ink-2')}><Link to={`/classes/${c.id}`} className="after:absolute after:inset-0 after:content-['']">{c.name}</Link></b>
          <span className="block truncate text-xs text-ink-3">{c.linked ? c.account : <span className="font-medium text-bad">Mất kết nối Google</span>}<span className="lg:hidden"> · {c.lessons.done} xong{hook ? ` · ${hook}` : ''}</span></span>
        </div>
      </div>
      <div className="hidden min-w-0 flex-col gap-0.5 text-[13px] lg:flex">
        <span className="truncate">{c.owned ? 'Cortex tạo · tải lên được' : 'Thư mục có sẵn · chỉ đọc'}</span>
        {c.folder_url && <a href={c.folder_url} target="_blank" rel="noreferrer" aria-label={`Mở thư mục Drive của ${c.name}`} className="relative z-10 inline-flex items-center gap-1 self-start text-xs font-medium text-accent hover:underline">Mở trong Drive<ExternalLink className="size-3" aria-hidden /></a>}
      </div>
      <div className="hidden min-w-0 flex-col gap-1 text-[13px] lg:flex">
        <span className={clsx('flex items-center gap-1.5', c.classroom ? 'text-ink' : 'text-ink-3')}><GraduationCap className={clsx('size-[15px] shrink-0', c.classroom && 'text-accent')} aria-hidden /><span className="truncate">{c.classroom ? `Classroom: ${c.classroom.course ?? 'đã nối'}` : 'Chưa nối Classroom'}</span></span>
        <span className={clsx('flex items-center gap-1.5', hook ? 'text-ink' : 'text-ink-3')}><Webhook className={clsx('size-[15px] shrink-0', hook ? 'text-accent' : 'text-ink-3')} aria-hidden /><span className="truncate">{hook ? `Webhook: ${hook}` : 'Dùng kênh chung'}</span></span>
      </div>
      <div className="hidden lg:block"><Counts c={c} /></div>
      <div><Badge tone={c.active ? 'ok' : 'neutral'}>{c.active ? 'Đang chạy' : 'Đã tắt'}</Badge></div>
      <div className="relative z-10 flex justify-end">{owner && <ClassActions c={c} />}</div>
    </li>
  )
}

/** The classes: one Drive folder and one Mezon channel each. Open a class to see its files and what the AI wrote from them. */
export function Lessons() {
  const q = useClasses()
  const me = useSession().data
  const [term, setTerm] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [adding, setAdding] = useState(false)
  const owner = can(me, 'sources.manage')
  const items = q.data?.items ?? []
  const count = (f: Filter) => items.filter((c) => f === 'all' || (f === 'on') === c.active).length
  const shown = items.filter((c) => (filter === 'all' || (filter === 'on') === c.active) && [c.name, c.account ?? '', c.webhook ?? ''].some((v) => plain(v).includes(plain(term.trim()))))
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-6 lg:px-10 lg:py-8 [&>*]:shrink-0">
      <PageHeader title="Lớp học" subtitle="Mỗi lớp có bài giảng (bản ghi và tổng kết AI) và bài tập (nộp bài và chấm điểm). Mở lớp để xem."
        action={owner && <Button variant="primary" className="px-4 py-2.5" onClick={() => setAdding(true)}><Plus className="size-4" aria-hidden />Thêm lớp</Button>} />
      {adding && <AddClassDialog onClose={() => setAdding(false)} />}
      {q.isPending ? <Loading /> : q.isError ? <ErrorBox onRetry={() => q.refetch()} /> : items.length === 0 ? (
        <Card className="flex flex-col items-center gap-2 p-12 text-center">
          <span className="grid size-12 place-items-center rounded-full bg-accent-soft text-accent"><Folder className="size-6" aria-hidden /></span>
          <p className="text-[13px] text-ink-3">{owner ? 'Chưa có lớp nào. Bấm «Thêm lớp» để tạo lớp đầu tiên.' : 'Chưa có lớp nào. Nhờ chủ thêm lớp.'}</p>
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <label className="relative block w-full max-w-sm"><Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
              <input type="search" aria-label="Tìm lớp" value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Tìm lớp theo tên, tài khoản hoặc webhook" className="w-full rounded-lg border border-line bg-surface py-2.5 pr-3 pl-9 text-[13px]" /></label>
            <div role="group" aria-label="Lọc theo trạng thái" className="flex gap-0.5 rounded-lg bg-[#e9ecf2] p-[3px]">
              {FILTERS.map(([k, label]) => (
                <button key={k} onClick={() => setFilter(k)} aria-pressed={filter === k}
                  className={clsx('rounded-md px-3 py-1.5 text-[13px]', filter === k ? 'bg-surface font-semibold text-ink shadow-sm' : 'font-medium text-ink-2 hover:text-ink')}>{label}<span aria-hidden className="ml-1.5 text-ink-3">{count(k)}</span></button>))}
            </div>
          </div>
          <Card>
            <div aria-hidden className={clsx('hidden grid-cols-1 items-center gap-4 rounded-t-xl border-b border-line bg-[#f9fafb] px-5 py-2.5 text-[11px] font-semibold tracking-wider text-ink-3 lg:grid', COLS)}>
              <span>LỚP</span><span>THƯ MỤC DRIVE</span><span>NƠI GỬI TỔNG KẾT</span><span>BUỔI HỌC VÀ BÀI TẬP</span><span>TRẠNG THÁI</span><span />
            </div>
            {shown.length === 0 ? <p className="p-8 text-center text-[13px] text-ink-3">Không có lớp nào khớp.</p>
              : <ul>{shown.map((c) => <Row key={c.id} c={c} owner={owner} />)}</ul>}
            <p className="border-t border-line px-5 py-3 text-xs text-ink-3">{shown.length === items.length ? `${items.length} lớp` : `${shown.length} / ${items.length} lớp`} · danh sách tự cập nhật khi có buổi mới</p>
          </Card>
        </>)}
    </div>
  )
}
