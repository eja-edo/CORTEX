import { Paperclip, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { explain } from '../api/client'
import { useAiAssignment, useAssignmentDecision, useCreateAssignment } from '../api/hooks'
import type { AssignmentDraft, Criterion, Material, MaterialIn } from '../api/types'
import { Badge, Button, Card, Label, Notice, type Tone } from '../components/ui'

const STATUS: Record<AssignmentDraft['status'], [string, Tone]> = { draft: ['Bản nháp', 'warn'], created: ['Đã tạo trên Classroom', 'ok'], rejected: ['Đã bỏ', 'neutral'], failed: ['Lỗi', 'bad'] }
const SHARE: Record<MaterialIn['share'], string> = { VIEW: 'Học sinh chỉ xem', EDIT: 'Học sinh cùng sửa một tệp', STUDENT_COPY: 'Mỗi học sinh một bản sao' }
const label = (x: Material) => x.title || (x.kind === 'drive' ? 'Tệp trên Drive' : x.url)
const field = 'rounded-lg border border-line bg-surface px-2.5 py-2 text-[13px]'
const slug = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 24) || 'tieu_chi'

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
  const [publish, setPublish] = useState(false)
  const [due, setDue] = useState('')
  return (
    <div className="flex flex-col gap-3">
      <div><h2 className="text-base font-bold">{d.title}</h2><div className="mt-1.5 flex flex-wrap gap-1.5">{d.course && <Badge tone="accent">Lớp {d.course}</Badge>}<Badge tone={STATUS[d.status][1]}>{STATUS[d.status][0]}</Badge><Badge tone={d.origin === 'ai' ? 'ai' : 'neutral'}>{d.origin === 'ai' ? 'AI soạn' : 'Giáo viên soạn'}</Badge></div></div>
      <AssignmentBody a={d} />
      {d.error && <Notice tone="bad">Lần tạo trước lỗi: {d.error}</Notice>}
      {d.status === 'draft' && <>
        <Notice tone="ai">Chưa có gì trên Classroom. Khi bạn duyệt, bài được tạo bằng ứng dụng này (nhờ vậy sau này chấm và ghi điểm được) cùng thang điểm trên.</Notice>
        <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={publish} onChange={(e) => setPublish(e.target.checked)} />Đăng ngay cho học sinh (nếu không, tạo bản nháp trong Classroom)</label>
        <label className="flex flex-col gap-1 text-[13px]">Hạn nộp (tuỳ chọn)<input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} className={field} /></label>
        {decide.isError && <Notice tone="bad">{explain(decide.error)}</Notice>}
        {decide.isSuccess && <Notice tone="ok">Đã xử lý.</Notice>}
        <div className="flex gap-2"><Button variant="primary" className="flex-1" busy={decide.isPending} onClick={() => decide.mutate({ id: d.id, action: 'approve', publish, due: due ? new Date(due).toISOString() : null })}>Duyệt và tạo trên Classroom</Button>
          <Button variant="danger" busy={decide.isPending} onClick={() => decide.mutate({ id: d.id, action: 'reject' })}>Bỏ</Button></div></>}
    </div>
  )
}

export function Compose({ sources, onDone }: { sources: { id: string; label: string }[]; onDone: () => void }) {
  const create = useCreateAssignment()
  const ai = useAiAssignment()
  const [source, setSource] = useState(sources[0]?.id ?? '')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [points, setPoints] = useState('10')
  const [language, setLanguage] = useState('')
  const [answerKey, setAnswerKey] = useState('')
  const [checkPrompt, setCheckPrompt] = useState('')
  const [rows, setRows] = useState<{ label: string; points: string; descriptor: string }[]>([{ label: '', points: '', descriptor: '' }])
  const [files, setFiles] = useState<MaterialIn[]>([])
  const [topic, setTopic] = useState('')
  const [level, setLevel] = useState('')
  const [minutes, setMinutes] = useState('20')
  const criteria: Criterion[] = rows.filter((r) => r.label.trim()).map((r, i) => ({ id: `${slug(r.label)}${i}`, label: r.label.trim(), points: parseFloat(r.points) || 0, descriptor: r.descriptor }))
  const sum = criteria.reduce((a, c) => a + c.points, 0)
  const ok = source && title.trim() && description.trim().length >= 10 && criteria.length > 0 && Math.abs(sum - (parseFloat(points) || 0)) < 0.01
  return (
    <div className="flex flex-col gap-5">
      <Card className="flex flex-col gap-3 p-5"><Label>Nhờ AI soạn bản nháp</Label>
        <input aria-label="Chủ đề" placeholder="Chủ đề hoặc mục tiêu, ví dụ: thì hiện tại hoàn thành" value={topic} onChange={(e) => setTopic(e.target.value)} className={field} />
        <div className="flex gap-2"><input aria-label="Trình độ" placeholder="Trình độ (A1, lớp 6…)" value={level} onChange={(e) => setLevel(e.target.value)} className={`${field} flex-1`} />
          <input aria-label="Số phút" inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value)} className={`${field} w-20`} /><span className="self-center text-xs text-ink-3">phút</span></div>
        {ai.isError && <Notice tone="bad">{explain(ai.error)}</Notice>}
        <Button busy={ai.isPending} disabled={!source || topic.trim().length < 3} onClick={() => ai.mutate({ class_id: source, topic: topic.trim(), level, minutes: parseInt(minutes) || 20 }, { onSuccess: onDone })}>Soạn bản nháp</Button></Card>
      <Card className="flex flex-col gap-3 p-5"><Label>Hoặc tự soạn</Label>
        {sources.length > 1 && <select aria-label="Lớp" value={source} onChange={(e) => setSource(e.target.value)} className={field}>{sources.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</select>}
        <input aria-label="Tiêu đề" placeholder="Tiêu đề" value={title} onChange={(e) => setTitle(e.target.value)} className={field} />
        <textarea aria-label="Đề bài" placeholder="Đề bài cho học sinh" rows={4} value={description} onChange={(e) => setDescription(e.target.value)} className={field} />
        <label className="flex items-center gap-2 text-[13px]">Tổng điểm<input aria-label="Tổng điểm" inputMode="numeric" value={points} onChange={(e) => setPoints(e.target.value)} className={`${field} w-20`} /></label>
        <label className="flex flex-col gap-1 text-[13px]">Nếu học sinh nộp bài nói, các em nói bằng
          <select aria-label="Ngôn ngữ bài nói" value={language} onChange={(e) => setLanguage(e.target.value)} className={field}><option value="">Tự nhận ra</option><option value="vi">Tiếng Việt</option><option value="en">Tiếng Anh</option></select></label>
        <Label>Đáp án và cách kiểm tra</Label>
        <textarea aria-label="Đáp án" placeholder="Đáp án (tuỳ chọn): đáp án đúng, hoặc nội dung bài mẫu để so với bài học sinh nộp" rows={4} value={answerKey} onChange={(e) => setAnswerKey(e.target.value)} className={field} />
        <textarea aria-label="Cách kiểm tra" placeholder="Cách kiểm tra (tuỳ chọn): bảo AI so bài học sinh với đáp án thế nào, ví dụ: phải chép đủ các đoạn, đúng từng từ, bỏ qua dấu câu; ảnh chữ viết tay thì đọc kỹ rồi so" rows={3} value={checkPrompt} onChange={(e) => setCheckPrompt(e.target.value)} className={field} />
        <p className="text-xs text-ink-3">Bài nộp là ảnh chụp thì AI nhìn thẳng vào ảnh và làm theo cách kiểm tra này.</p>
        <Label>Tệp đính kèm</Label>
        <p className="text-xs text-ink-3">Dán địa chỉ tệp trên Google Drive (tài khoản đã nối phải đọc được tệp) hoặc một đường dẫn web. Địa chỉ khác Drive được đính kèm như đường dẫn.</p>
        {files.map((f, i) => <div key={i} className="flex flex-col gap-1.5 rounded-lg border border-line p-2">
          <div className="flex gap-2"><input aria-label={`Địa chỉ tệp ${i + 1}`} placeholder="https://drive.google.com/file/d/…" value={f.url} onChange={(e) => setFiles(files.map((x, j) => (j === i ? { ...x, url: e.target.value } : x)))} className={`${field} flex-1`} />
            <button aria-label={`Bỏ tệp ${i + 1}`} className="text-ink-3 hover:text-bad" onClick={() => setFiles(files.filter((_, j) => j !== i))}><Trash2 className="size-4" /></button></div>
          <input aria-label={`Tên tệp ${i + 1}`} placeholder="Tên hiển thị trong bản nháp (tuỳ chọn)" value={f.title ?? ''} onChange={(e) => setFiles(files.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} className={field} />
          <select aria-label={`Quyền của học sinh với tệp ${i + 1}`} value={f.share} onChange={(e) => setFiles(files.map((x, j) => (j === i ? { ...x, share: e.target.value as MaterialIn['share'] } : x)))} className={field}>{Object.entries(SHARE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>)}
        {files.length < 10 && <button className="flex items-center gap-1 self-start text-[13px] font-semibold text-accent" onClick={() => setFiles([...files, { url: '', title: '', share: 'VIEW' }])}><Paperclip className="size-4" aria-hidden />Đính kèm tệp</button>}
        <Label>Thang điểm</Label>
        {rows.map((r, i) => <div key={i} className="flex gap-2">
          <input aria-label={`Tiêu chí ${i + 1}`} placeholder="Tiêu chí" value={r.label} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} className={`${field} flex-1`} />
          <input aria-label={`Điểm tiêu chí ${i + 1}`} placeholder="Điểm" inputMode="decimal" value={r.points} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, points: e.target.value } : x)))} className={`${field} w-16`} />
          <button aria-label={`Bỏ tiêu chí ${i + 1}`} className="text-ink-3 hover:text-bad" onClick={() => setRows(rows.filter((_, j) => j !== i))}><Trash2 className="size-4" /></button></div>)}
        <button className="flex items-center gap-1 self-start text-[13px] font-semibold text-accent" onClick={() => setRows([...rows, { label: '', points: '', descriptor: '' }])}><Plus className="size-4" aria-hidden />Thêm tiêu chí</button>
        <p className={`text-xs ${Math.abs(sum - (parseFloat(points) || 0)) < 0.01 ? 'text-ink-3' : 'text-bad'}`}>Cộng các tiêu chí: {sum} / {parseFloat(points) || 0}{Math.abs(sum - (parseFloat(points) || 0)) >= 0.01 && ' (phải bằng tổng điểm)'}</p>
        {create.isError && <Notice tone="bad">{explain(create.error)}</Notice>}
        <Button variant="primary" busy={create.isPending} disabled={!ok} onClick={() => create.mutate({ class_id: source, title: title.trim(), description: description.trim(), max_points: parseInt(points), criteria, answer_key: answerKey.trim() || null, check_prompt: checkPrompt.trim() || null, language: language || null, materials: files.filter((f) => f.url.trim()).map((f) => ({ ...f, url: f.url.trim() })) }, { onSuccess: onDone })}>Lưu bản nháp</Button></Card>
    </div>
  )
}
