import { useState } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { explain } from '../api/client'
import { useAskGrading, useGradeDecision, useGradeItem } from '../api/hooks'
import type { GradeDetail, GradeStatus } from '../api/types'
import { Time } from '../components/Time'
import { Badge, Button, ErrorBox, Label, Loading, Notice, type Tone } from '../components/ui'

export const TONE: Record<GradeStatus, Tone> = { pending: 'neutral', queued: 'neutral', working: 'accent', proposed: 'warn', approved: 'ok', rejected: 'neutral', skipped: 'neutral', failed: 'bad' }
const KIND: Record<string, string> = { text: 'Văn bản', pdf: 'PDF', docx: 'Word', audio: 'Âm thanh (bản chép lời)', video: 'Video (chỉ lấy tiếng)', image: 'Ảnh chụp (chữ do máy đọc)' }
export const num = (x: number) => String(Math.round(x * 100) / 100)

function Decide({ d }: { d: GradeDetail }) {
  const decision = useGradeDecision(d.id)
  const p = d.proposal!
  const [scores, setScores] = useState<Record<string, string>>(Object.fromEntries(p.criteria.map((c) => [c.id, num(c.score)])))
  const [feedback, setFeedback] = useState(p.feedback)
    const total = p.criteria.reduce((a, c) => a + (parseFloat(scores[c.id]) || 0), 0)
  const bad = p.criteria.some((c) => { const v = parseFloat(scores[c.id]); return Number.isNaN(v) || v < 0 || v > c.points })
  const send = (action: 'approve' | 'reject') => decision.mutate(action === 'reject' ? { action } : { action, feedback, scores: Object.fromEntries(p.criteria.map((c) => [c.id, parseFloat(scores[c.id])])) })
  return (
    <div className="flex flex-col gap-3">
      <Label>Chấm theo thang điểm</Label>
      <div className="flex flex-col gap-2">
        {p.criteria.map((c) => (
          <div key={c.id} className="rounded-lg bg-app p-3 text-[13px]">
            <div className="flex items-center gap-2"><b className="flex-1">{c.label}</b>
              <input aria-label={`Điểm ${c.label}`} inputMode="decimal" value={scores[c.id]} onChange={(e) => setScores({ ...scores, [c.id]: e.target.value })} className="w-16 rounded border border-line bg-surface px-2 py-1 text-right" />
              <span className="text-ink-3">/ {num(c.points)}</span></div>
            {c.proposed !== null && c.proposed !== c.score && <p className="mt-1 text-xs text-bad">AI đề xuất {num(c.proposed)} nhưng dẫn chứng không có trong bài nên đặt lại {num(c.score)}.</p>}
            {c.quote && <p className="mt-1 text-xs text-ink-2">“{c.quote}” {c.verified ? <Badge tone="ok">Có trong bài</Badge> : <Badge tone="bad">Không có trong bài</Badge>}</p>}
          </div>))}
      </div>
      <p className="text-sm font-bold">Tổng: {num(total)} / {num(p.max_points)}</p>
      <Label>Nhận xét cho học sinh</Label>
      <textarea aria-label="Nhận xét" value={feedback} onChange={(e) => setFeedback(e.target.value)} rows={3} className="rounded-lg border border-line bg-surface p-2 text-[13px]" />
      <Notice tone={d.ours ? 'ai' : 'warn'}>{d.ours
        ? 'Duyệt là ghi điểm này lên Classroom và trả bài cho học sinh. Nhận xét chỉ lưu ở Cortex để giáo viên xem, học sinh không nhận được nhận xét qua Classroom.'
        : 'Bài này không do ứng dụng tạo nên Google không cho ghi điểm: điểm chỉ lưu ở đây, bạn tự nhập vào Classroom.'}</Notice>
      {decision.isError && <Notice tone="bad">{explain(decision.error)}</Notice>}
      <div className="flex gap-2">
        <Button variant="primary" className="flex-1" busy={decision.isPending} disabled={bad} onClick={() => send('approve')}>Duyệt điểm</Button>
        <Button variant="danger" busy={decision.isPending} onClick={() => send('reject')}>Bỏ đề xuất</Button>
      </div>
    </div>
  )
}

export function SubmissionDetail({ id }: { id: string }) {
  const q = useGradeItem(id)
  const ask = useAskGrading()
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const d = q.data
  const p = d.proposal
  return (
    <div className="flex flex-col gap-4">
      <div><h2 className="text-base font-bold">{d.student}</h2><p className="text-xs text-ink-2">{d.work_title}</p>
        <div className="mt-1.5 flex gap-1.5"><Badge tone={TONE[d.status]}>{d.status_label}</Badge>{d.written && <Badge tone="ok">{d.decided_by === 'auto' ? 'Tự động ghi lên Classroom' : 'Đã ghi lên Classroom'}</Badge>}{!d.ours && <Badge>Chỉ gợi ý điểm</Badge>}{d.content_kind.map((k) => <Badge key={k} tone={k === 'audio' || k === 'video' || k === 'image' ? 'warn' : 'neutral'}>{KIND[k] ?? k}</Badge>)}</div></div>
      {d.reason && <Notice tone={d.status === 'failed' ? 'bad' : 'warn'}>{d.reason}</Notice>}
      {d.status === 'pending' && <Notice tone="warn" action={<Button variant="primary" busy={ask.one.isPending} onClick={() => ask.one.mutate(d.id)}>Chấm bằng AI</Button>}>Lớp này để chế độ thủ công: AI chưa đọc bài này. Bấm để nhờ AI chấm.</Notice>}
      {ask.one.isSuccess && <Notice tone="ok">Đã gửi cho AI, đề xuất điểm sẽ hiện sau ít phút.</Notice>}
      {ask.one.isError && <Notice tone="bad">{explain(ask.one.error)}</Notice>}
      {p && d.status === 'proposed' && <Notice tone="ai">Đề xuất của AI, chưa có hiệu lực. Chỉ khi bạn duyệt thì điểm mới được lưu.</Notice>}
      {p?.problems.map((x, i) => <Notice key={i} tone="warn">{x}</Notice>)}
      {p?.concerns.map((x, i) => <Notice key={`c${i}`} tone="warn">Lưu ý của AI: {x}</Notice>)}
      <section><Label>Bài làm của học sinh</Label><p className="max-h-72 overflow-y-auto rounded-lg bg-app p-3 text-[13px] leading-relaxed whitespace-pre-wrap">{d.content ?? '(chưa đọc được)'}</p></section>
      {d.status === 'proposed' && p && <Decide key={d.id} d={d} />}
      {d.final && <section><Label>Điểm đã duyệt</Label><p className="text-[13px]"><b>{num(d.final.total)} / {num(d.final.max_points)}</b> · {d.decided_by} · {d.decided_at && <Time iso={d.decided_at} as="when" />}</p><p className="text-[13px] text-ink-2">{d.final.feedback}</p></section>}
    </div>
  )
}

/** A link in a team message names one submission: send the reader to its assignment with that submission open. */
export function GradingLink() {
  const { id } = useParams()
  const q = useGradeItem(id ?? null)
  if (!id) return <Navigate to="/classes" replace />
  if (q.isPending) return <div className="p-8"><Loading /></div>
  if (q.isError) return <div className="p-8"><ErrorBox onRetry={() => q.refetch()} /></div>
  return <Navigate to={`/classes/${q.data.class_id}/assignments/${q.data.assignment_id}?item=${id}`} replace />
}
