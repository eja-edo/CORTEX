import { ArrowLeft, FileText, Paperclip, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { explain } from '../api/client'
import { useAiAssignment, useAssignmentDecision, useClassroomOptions, useClassKinds, useKindTemplates, useCreateAssignment } from '../api/hooks'
import type { AssignmentDraft, AssignmentTemplate, Criterion, Material, MaterialIn } from '../api/types'
import { Badge, Button, Card, Label, Notice, type Tone } from '../components/ui'
import { AttachedFiles, DriveAttach, SHARE } from './DriveAttach'
import { EditWork } from './ManageWork'
import { addPicked, AudienceFields, audienceReady, criteriaOf, CriteriaEditor, EVERYONE, field, NOW_MODE, rowsOf, type Audience, type Row, type When, WhenFields, whenBody, whenReady } from './PostingFields'

const STATUS: Record<AssignmentDraft['status'], [string, Tone]> = { draft: ['Bản nháp', 'warn'], created: ['Đã tạo trên Classroom', 'ok'], rejected: ['Đã bỏ', 'neutral'], failed: ['Lỗi', 'bad'] }
const label = (x: Material) => x.title || (x.kind === 'drive' ? 'Tệp trên Drive' : x.kind === 'youtube' ? 'Video YouTube' : x.kind === 'form' ? 'Google Form' : x.url)

/** What the assignment asks: the brief, the rubric, the attachments and how it is checked. Shared by a draft and by a made assignment's page. */
export function AssignmentBody({ a }: { a: { description: string | null; max_points: number | null; criteria: Criterion[]; materials: Material[]; answer_key: string | null; check_prompt?: string | null; language: string | null } }) {
  const d = a
  return (
    <div className="flex flex-col gap-3">
      {d.description ? <p className="text-[13px] whitespace-pre-wrap">{d.description}</p> : <p className="text-[13px] text-ink-3">Chưa có mô tả đề bài.</p>}
      <Label>Thang điểm{d.max_points !== null && ` · tổng ${d.max_points}`}</Label>
      {d.criteria.length === 0 ? <p className="text-[13px] text-ink-3">Chưa có thang điểm.</p>
        : <ul className="list-disc pl-5 text-[13px]">{d.criteria.map((c) => <li key={c.id}>{c.label}: {c.points} điểm{c.descriptor && ` · ${c.descriptor}`}</li>)}</ul>}
      {d.materials.length > 0 && <><Label>Tệp đính kèm</Label>
        <ul className="flex flex-col gap-1 text-[13px]">{d.materials.map((x, i) => <li key={i} className="flex items-center gap-1.5"><Paperclip className="size-3.5 text-ink-3" aria-hidden />{label(x)}{x.kind === 'drive' && <span className="text-xs text-ink-3">· {SHARE[x.share]}</span>}</li>)}</ul></>}
      {d.answer_key && <p className="text-xs text-ink-2">Đáp án: {d.answer_key}</p>}
      {d.check_prompt && <p className="text-xs text-ink-2 whitespace-pre-wrap">Cách kiểm tra: {d.check_prompt}</p>}
      {d.language && <p className="text-xs text-ink-2">Bài nói: {d.language === 'en' ? 'tiếng Anh' : d.language === 'vi' ? 'tiếng Việt' : d.language}</p>}
    </div>
  )
}

export function Draft({ d }: { d: AssignmentDraft }) {
  const decide = useAssignmentDecision()
  const [when, setWhen] = useState<When>({ ...NOW_MODE, mode: d.scheduled ? 'schedule' : d.publish ? 'now' : 'draft' })
  const [editing, setEditing] = useState(false)
  return (
    <div className="flex flex-col gap-3">
      <div><h2 className="text-base font-bold">{d.title}</h2><div className="mt-1.5 flex flex-wrap gap-1.5">{d.course && <Badge tone="accent">Lớp {d.course}</Badge>}<Badge tone={STATUS[d.status][1]}>{STATUS[d.status][0]}</Badge>
        {d.origin === 'ai' && <Badge tone="ai">AI soạn</Badge>}{d.topic?.name && <Badge>Chủ đề: {d.topic.name}</Badge>}{d.assignees && <Badge>{d.assignees.length} học sinh</Badge>}</div></div>
      {editing && d.status === 'draft' ? <EditWork a={d} onDone={() => setEditing(false)} /> : <AssignmentBody a={d} />}
      {d.error && <Notice tone="bad">Lần tạo trước lỗi: {d.error}</Notice>}
      {d.status === 'draft' && !editing && <>
        <Notice tone="ai">Chưa có gì trên Classroom. Khi bạn duyệt, bài được tạo bằng ứng dụng này (nhờ vậy sau này chấm và ghi điểm được) cùng thang điểm trên.</Notice>
        <WhenFields value={{ ...when, due: when.due || '' }} onChange={setWhen} />
        {decide.isError && <Notice tone="bad">{explain(decide.error)}</Notice>}
        {decide.isSuccess && <Notice tone="ok">Đã xử lý.</Notice>}
        <div className="flex gap-2"><Button variant="primary" className="flex-1" busy={decide.isPending} disabled={!whenReady(when)} onClick={() => decide.mutate({ id: d.id, action: 'approve', ...whenBody(when) })}>Duyệt và tạo trên Classroom</Button>
          <Button onClick={() => setEditing(true)}>Sửa</Button>
          <Button variant="danger" busy={decide.isPending} onClick={() => decide.mutate({ id: d.id, action: 'reject' })}>Bỏ</Button></div></>}
    </div>
  )
}

/** Two steps: choose a kind of class, then one of its ready-made assignments. Choosing one hands it to the form, which fills its boxes. */
function TemplatePicker({ onPick }: { onPick: (t: AssignmentTemplate) => void }) {
  const kinds = useClassKinds()
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState('')
  const [done, setDone] = useState<{ name: string; kind: string } | null>(null)
  const list = kinds.data?.items ?? []
  const current = list.find((k) => k.id === kind) ?? list.find((k) => k.templates > 0) ?? list[0]
  const templates = useKindTemplates(current?.id ?? '')
  const items = templates.data?.items ?? []
  const any = list.some((k) => k.templates > 0)
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={kinds.isPending || !any} onClick={() => setOpen(!open)} aria-expanded={open}><FileText className="size-4" aria-hidden />Chọn bài tập mẫu</Button>
        {done && <span className="text-xs text-ok">Đã điền từ «{done.name}» ({done.kind}). Xem lại rồi sửa tiếp.</span>}
        {kinds.data && !any && <span className="text-xs text-ink-3">Chưa có bài tập mẫu nào. <Link to="/templates" className="font-semibold text-accent">Tạo bài tập mẫu</Link></span>}
        {kinds.isError && <span className="text-xs text-bad">Chưa lấy được danh sách bài tập mẫu.</span>}
      </div>
      {open && current && <div className="flex flex-col gap-3 rounded-lg border border-line p-3">
        <div className="flex flex-col gap-1.5"><Label>1. Chọn loại lớp</Label>
          <div role="radiogroup" aria-label="Loại lớp" className="flex flex-wrap gap-2">{list.map((k) => (
            <button key={k.id} role="radio" aria-checked={k.id === current.id} onClick={() => setKind(k.id)}
              className={`rounded-full border px-3.5 py-1.5 text-[13px] ${k.id === current.id ? 'border-accent bg-accent-soft font-semibold text-accent' : 'border-line text-ink-2 hover:border-ink-3'}`}>{k.name}</button>))}</div></div>
        <div className="flex flex-col gap-1.5"><Label>2. Chọn bài tập · {current.name} ({current.templates} bài)</Label>
          {templates.isPending && <p className="text-xs text-ink-3">Đang tải…</p>}
          {templates.isError && <p className="text-xs text-bad">Chưa lấy được bài tập của loại này.</p>}
          {templates.data && items.length === 0 && <p className="text-xs text-ink-3">Loại lớp này chưa có bài tập mẫu.</p>}
          {items.length > 0 && <ul aria-label="Bài tập mẫu" className="flex max-h-56 flex-col overflow-y-auto rounded-lg border border-line">
            {items.map((t) => <li key={t.id}><button onClick={() => { onPick(t); setDone({ name: t.name, kind: current.name }); setOpen(false) }} className="flex w-full flex-col items-start gap-0.5 border-b border-line px-3 py-2 text-left text-[13px] last:border-b-0 hover:bg-app">
              <b>{t.name}</b><span className="text-xs text-ink-3">{[t.title, t.max_points !== null && `${t.max_points} điểm`].filter(Boolean).join(' · ')}</span></button></li>)}</ul>}</div>
      </div>}
    </div>
  )
}


/** A full page for a new assignment: what students see on the left, how and to whom it goes out on the right. */
export function Compose({ sources, onDone, onCancel }: { sources: { id: string; label: string }[]; onDone: () => void; onCancel?: () => void }) {
  const create = useCreateAssignment()
  const ai = useAiAssignment()
  const [source, setSource] = useState(sources[0]?.id ?? '')
  const options = useClassroomOptions(source, Boolean(source))
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [points, setPoints] = useState('10')
  const [language, setLanguage] = useState('')
  const [answerKey, setAnswerKey] = useState('')
  const [checkPrompt, setCheckPrompt] = useState('')
  const [rows, setRows] = useState<Row[]>([{ label: '', points: '', descriptor: '' }])
  const [files, setFiles] = useState<MaterialIn[]>([])
  const [when, setWhen] = useState<When>(NOW_MODE)
  const [aud, setAud] = useState<Audience>(EVERYONE)
  const [topic, setTopic] = useState('')
  const [level, setLevel] = useState('')
  const [minutes, setMinutes] = useState('20')
  const criteria: Criterion[] = criteriaOf(rows)
  const sum = criteria.reduce((a, c) => a + c.points, 0)
  const ok = source && title.trim() && description.trim().length >= 10 && criteria.length > 0 && Math.abs(sum - (parseFloat(points) || 0)) < 0.01 && whenReady(when) && audienceReady(aud)
  /** Only the boxes the template has a value for change, so what was typed already is not wiped by an empty one. */
  const fill = (t: AssignmentTemplate) => {
    if (t.title) setTitle(t.title)
    if (t.description) setDescription(t.description)
    if (t.max_points !== null) setPoints(String(t.max_points))
    if (t.criteria.length) setRows(rowsOf(t.criteria))
    if (t.answer_key) setAnswerKey(t.answer_key)
    if (t.check_prompt) setCheckPrompt(t.check_prompt)
    if (t.language) setLanguage(t.language)
    if (t.topic_name) setAud((a) => ({ ...a, topic: t.topic_name! }))
    if (t.materials.length) setFiles(t.materials.map((x) => ({ url: x.url, title: x.title ?? '', share: x.share })))
  }
  const save = () => create.mutate({ class_id: source, title: title.trim(), description: description.trim(), max_points: parseInt(points), criteria, answer_key: answerKey.trim() || null, check_prompt: checkPrompt.trim() || null, language: language || null, materials: files.filter((f) => f.url.trim()).map((f) => ({ ...f, url: f.url.trim() })), ...whenBody(when), topic_name: aud.topic.trim() || null, assignees: aud.some ? aud.students : [] }, { onSuccess: onDone })
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-3">
        {onCancel && <button onClick={onCancel} className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent"><ArrowLeft className="size-4" aria-hidden />Bài tập</button>}
        <h2 className="text-lg font-bold">Soạn bài tập mới</h2></div>
      <Card className="flex flex-col gap-3 p-5">
        <div className="flex flex-wrap items-center gap-2"><Sparkles className="size-4 text-ai" aria-hidden /><Label>Nhờ AI soạn bản nháp</Label><span className="text-xs text-ink-3">· tuỳ chọn: AI viết đề và thang điểm, bạn sửa lại rồi mới duyệt</span></div>
        <div className="flex flex-wrap items-center gap-2">
          <input aria-label="Chủ đề" placeholder="Chủ đề hoặc mục tiêu, ví dụ: thì hiện tại hoàn thành" value={topic} onChange={(e) => setTopic(e.target.value)} className={`${field} min-w-60 flex-1`} />
          <input aria-label="Trình độ" placeholder="Trình độ (A1, lớp 6…)" value={level} onChange={(e) => setLevel(e.target.value)} className={`${field} w-44`} />
          <span className="flex items-center gap-1.5"><input aria-label="Số phút" inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value)} className={`${field} w-16`} /><span className="text-xs text-ink-3">phút</span></span>
          <Button busy={ai.isPending} disabled={!source || topic.trim().length < 3} onClick={() => ai.mutate({ class_id: source, topic: topic.trim(), level, minutes: parseInt(minutes) || 20 }, { onSuccess: onDone })}>Soạn bản nháp</Button></div>
        {ai.isError && <Notice tone="bad">{explain(ai.error)}</Notice>}
      </Card>
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card className="flex flex-col gap-4 p-5"><Label>Hoặc tự soạn</Label>
          {sources.length > 1 && <select aria-label="Lớp" value={source} onChange={(e) => setSource(e.target.value)} className={field}>{sources.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</select>}
          <TemplatePicker onPick={fill} />
          <input aria-label="Tiêu đề" placeholder="Tiêu đề" value={title} onChange={(e) => setTitle(e.target.value)} className={`${field} text-sm font-semibold`} />
          <textarea aria-label="Đề bài" placeholder="Đề bài cho học sinh" rows={6} value={description} onChange={(e) => setDescription(e.target.value)} className={field} />
          <hr className="border-line" />
          <Label>Tệp đính kèm</Label>
          <p className="-mt-2 text-xs text-ink-3">Chọn tệp từ Google Drive của giáo viên.</p>
          <AttachedFiles files={files} setFiles={setFiles} />
          {files.length < 10 && <DriveAttach key={source} classId={source} onPick={(picked) => setFiles((cur) => addPicked(cur, picked))} />}
          <hr className="border-line" />
          <Label>Thang điểm</Label>
          <CriteriaEditor rows={rows} setRows={setRows} points={points} />
          <hr className="border-line" />
          <Label>Đáp án và cách kiểm tra</Label>
          <textarea aria-label="Đáp án" placeholder="Đáp án (tuỳ chọn): đáp án đúng, hoặc nội dung bài mẫu để so với bài học sinh nộp" rows={4} value={answerKey} onChange={(e) => setAnswerKey(e.target.value)} className={field} />
          <textarea aria-label="Cách kiểm tra" placeholder="Cách kiểm tra (tuỳ chọn): bảo AI so bài học sinh với đáp án thế nào, ví dụ: phải chép đủ các đoạn, đúng từng từ, bỏ qua dấu câu; ảnh chữ viết tay thì đọc kỹ rồi so" rows={3} value={checkPrompt} onChange={(e) => setCheckPrompt(e.target.value)} className={field} />
          <p className="-mt-2 text-xs text-ink-3">Bài nộp là ảnh chụp thì AI nhìn thẳng vào ảnh và làm theo cách kiểm tra này.</p>
        </Card>
        <div className="flex flex-col gap-4 lg:sticky lg:top-4">
          <Card className="flex flex-col gap-4 p-5">
            <label className="flex items-center gap-2 text-[13px] font-medium">Tổng điểm<input aria-label="Tổng điểm" inputMode="numeric" value={points} onChange={(e) => setPoints(e.target.value)} className={`${field} w-20`} /></label>
            <hr className="border-line" />
            <WhenFields value={when} onChange={setWhen} />
            <hr className="border-line" />
            <AudienceFields options={options.data} value={aud} onChange={setAud} />
            <hr className="border-line" />
            <label className="flex flex-col gap-1.5 text-[13px] font-medium">Nếu học sinh nộp bài nói, các em nói bằng
              <select aria-label="Ngôn ngữ bài nói" value={language} onChange={(e) => setLanguage(e.target.value)} className={`${field} font-normal`}><option value="">Tự nhận ra</option><option value="vi">Tiếng Việt</option><option value="en">Tiếng Anh</option></select></label>
          </Card>
          <Card className="flex flex-col gap-3 p-4">
            {create.isError && <Notice tone="bad">{explain(create.error)}</Notice>}
            {!ok && <p className="text-xs text-ink-3">Cần có tiêu đề, đề bài (ít nhất 10 ký tự) và thang điểm cộng đúng bằng tổng điểm.</p>}
            <p className="text-xs text-ink-3">Lưu xong, bản nháp mới ở Cortex. Bạn duyệt thì bài mới được tạo trên Classroom.</p>
            <div className="flex gap-2"><Button variant="primary" className="flex-1" busy={create.isPending} disabled={!ok} onClick={save}>Lưu bản nháp</Button>{onCancel && <Button onClick={onCancel}>Huỷ</Button>}</div>
          </Card>
        </div>
      </div>
    </div>
  )
}
