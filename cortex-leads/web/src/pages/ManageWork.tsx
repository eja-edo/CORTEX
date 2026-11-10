import { Pencil, Send, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { explain } from '../api/client'
import { useClassroomOptions, useDeleteAssignment, useEditAssignment, usePublishAssignment } from '../api/hooks'
import type { Criterion, PostingInfo } from '../api/types'
import { Time } from '../components/Time'
import { Badge, Button, Label, Notice } from '../components/ui'
import { AudienceFields, audienceReady, criteriaOf, CriteriaEditor, EVERYONE, field, POSTING, rowsOf, toIso, toLocal, WhenFields, whenReady, type Audience, type Row, type When } from './PostingFields'

type Work = PostingInfo & {
  id: string; title: string; description: string | null; max_points: number | null; due: string | null; criteria: Criterion[]
  answer_key: string | null; check_prompt?: string | null; class_id?: string
}

/** Changes a draft, or work already in Classroom: Classroom's side first (title, description, points, due date, topic, schedule), then ours
 *  (the grading guide, which Classroom does not have). Attachments and who it is given to cannot change once it exists in Classroom. */
export function EditWork({ a, classId, onDone }: { a: Work; classId?: string; onDone: () => void }) {
  const edit = useEditAssignment()
  const cls = classId ?? a.class_id ?? ''
  const options = useClassroomOptions(cls, Boolean(cls))
  const out = a.posting === 'published'
  const [title, setTitle] = useState(a.title)
  const [description, setDescription] = useState(a.description ?? '')
  const [points, setPoints] = useState(String(a.max_points ?? 10))
  const [due, setDue] = useState(toLocal(a.due))
  const [scheduled, setScheduled] = useState(toLocal(a.scheduled))
  const [aud, setAud] = useState<Audience>({ ...EVERYONE, topic: a.topic?.name ?? '' })
  const [key, setKey] = useState(a.answer_key ?? '')
  const [check, setCheck] = useState(a.check_prompt ?? '')
  const [rows, setRows] = useState<Row[]>(rowsOf(a.criteria))
  const criteria = criteriaOf(rows)
  const sum = criteria.reduce((x, c) => x + c.points, 0)
  const when: When = { mode: scheduled ? 'schedule' : 'now', due, scheduled }
  const ok = title.trim() && description.trim().length >= 10 && criteria.length > 0 && Math.abs(sum - (parseFloat(points) || 0)) < 0.01 && whenReady({ ...when, mode: out ? 'now' : when.mode }) && audienceReady(aud)
  const save = () => edit.mutate({
    id: a.id, title: title.trim(), description: description.trim(), max_points: parseInt(points), criteria, answer_key: key.trim() || null, check_prompt: check.trim() || null,
    due: toIso(due), ...(out ? {} : { scheduled: toIso(scheduled) }), topic_name: aud.topic.trim() || null,
  }, { onSuccess: onDone })
  const lab = 'flex flex-col gap-1.5 text-[13px] font-medium'
  return (
    <div className="@container flex flex-col gap-5">
      <h2 className="text-base font-bold">Sửa bài tập</h2>
      <div className="flex flex-col gap-3">
        <input aria-label="Tiêu đề" value={title} onChange={(e) => setTitle(e.target.value)} className={`${field} text-sm font-semibold`} />
        <textarea aria-label="Đề bài" rows={5} value={description} onChange={(e) => setDescription(e.target.value)} className={field} /></div>
      <div className="grid items-end gap-3 @lg:grid-cols-[6rem_1fr_1fr]">
        <label className={lab}>Tổng điểm<input aria-label="Tổng điểm" inputMode="numeric" value={points} onChange={(e) => setPoints(e.target.value)} className={field} /></label>
        <label className={lab}>Hạn nộp<span className="text-xs font-normal text-ink-3">xoá ô để bỏ hạn</span><input type="datetime-local" aria-label="Hạn nộp" value={due} onChange={(e) => setDue(e.target.value)} className={field} /></label>
        {!out && a.posting !== 'draft' && <label className={lab}>Giờ hẹn đăng<span className="text-xs font-normal text-ink-3">xoá ô để bỏ hẹn</span><input type="datetime-local" aria-label="Giờ đăng" value={scheduled} onChange={(e) => setScheduled(e.target.value)} className={field} /></label>}
      </div>
      {a.posting === 'draft' && <WhenFields value={when} onChange={(w) => { setDue(w.due); setScheduled(w.mode === 'schedule' ? w.scheduled : '') }} />}
      <hr className="border-line" />
      <AudienceFields options={options.data} value={{ ...aud, some: false }} onChange={(v) => setAud({ ...v, some: false })} />
      <p className="rounded-lg bg-app px-3 py-2 text-xs text-ink-2">Danh sách học sinh và tệp đính kèm không đổi được sau khi đã tạo trên Classroom (Classroom không cho). Cần đổi thì bỏ bản nháp và soạn lại.</p>
      <hr className="border-line" />
      <Label>Thang điểm</Label>
      <CriteriaEditor rows={rows} setRows={setRows} points={points} />
      <hr className="border-line" />
      <Label>Đáp án và cách kiểm tra</Label>
      <textarea aria-label="Đáp án" rows={4} value={key} onChange={(e) => setKey(e.target.value)} className={field} />
      <textarea aria-label="Cách kiểm tra" rows={4} value={check} onChange={(e) => setCheck(e.target.value)} className={field} />
      {edit.isError && <Notice tone="bad">{explain(edit.error)}</Notice>}
      <div className="flex gap-2"><Button variant="primary" busy={edit.isPending} disabled={!ok} onClick={save}>Lưu thay đổi</Button><Button onClick={onDone}>Huỷ</Button></div>
    </div>
  )
}

/** The steps open on work Cortex put in Classroom: show it to students (the one filled button), change it, take it down. Taking it down is quiet
 *  and asks again. Used by the class panel (with the status chips) and by the work's own page (in its header). */
export function WorkActions({ a, onEdit }: { a: Work; onEdit: () => void }) {
  const publish = usePublishAssignment()
  const del = useDeleteAssignment()
  const [confirm, setConfirm] = useState(false)
  const waiting = a.posting === 'classroom_draft' || a.posting === 'scheduled'
  return (
    <div className="flex flex-col gap-2.5">
      {publish.isError && <Notice tone="bad">{explain(publish.error)}</Notice>}
      {del.isError && <Notice tone="bad">{explain(del.error)}</Notice>}
      {confirm && <Notice tone="warn">Xoá «{a.title}» khỏi Classroom? Bài nộp của học sinh trên Classroom cũng mất. Điểm đã duyệt vẫn giữ ở đây; bài đang chờ chấm sẽ bị bỏ qua.</Notice>}
      <div className="flex flex-wrap items-center gap-2">
        {waiting && <Button variant="primary" busy={publish.isPending} onClick={() => publish.mutate(a.id)}><Send className="size-3.5" aria-hidden />Đăng cho học sinh ngay</Button>}
        <Button onClick={onEdit}><Pencil className="size-3.5" aria-hidden />Sửa</Button>
        {confirm ? <><Button variant="dangerSolid" busy={del.isPending} onClick={() => del.mutate(a.id)}>Xác nhận xoá</Button><Button onClick={() => setConfirm(false)}>Không xoá</Button></>
          : <button className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-[13px] font-medium text-ink-3 hover:bg-bad-soft hover:text-bad" onClick={() => setConfirm(true)}><Trash2 className="size-3.5" aria-hidden />Xoá khỏi Classroom</button>}
      </div>
    </div>
  )
}

/** Where the work stands, as chips: published, waiting as a draft, or scheduled for a time, then its topic and who it is for. */
export function PostingChips({ a }: { a: Work }) {
  const [text, tone] = POSTING[a.posting] ?? POSTING.classroom
  return (
    <div className="flex flex-wrap items-center gap-1.5"><Badge tone={tone}>{text}</Badge>
      {a.posting === 'scheduled' && a.scheduled && <Badge><span>Đăng lúc <Time iso={a.scheduled} as="when" /></span></Badge>}
      {a.topic?.name && <Badge>Chủ đề: {a.topic.name}</Badge>}{a.assignees && <Badge>{a.assignees.length} học sinh</Badge>}</div>
  )
}

/** The class panel's version: chips and steps together, with the edit form in place of both. */
export function ManageWork({ a, classId }: { a: Work; classId: string }) {
  const [editing, setEditing] = useState(false)
  if (editing) return <EditWork a={a} classId={classId} onDone={() => setEditing(false)} />
  return <div className="flex flex-col gap-3"><PostingChips a={a} /><WorkActions a={a} onEdit={() => setEditing(true)} /></div>
}
