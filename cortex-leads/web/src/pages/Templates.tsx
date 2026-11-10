import { Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { explain } from '../api/client'
import { useClassKinds, useCreateKind, useDeleteKind, useDeleteTemplate, useKindTemplates, useRenameKind, useSaveTemplate, useSession } from '../api/hooks'
import type { AssignmentTemplate, AssignmentTemplateIn, MaterialIn } from '../api/types'
import { can } from '../components/can'
import { Badge, Button, Card, Empty, ErrorBox, Label, Loading, Notice, PageHeader } from '../components/ui'
import { AttachedFiles, DriveAttach } from './DriveAttach'
import { addPicked, CriteriaEditor, criteriaOf, field, rowsOf, type Row } from './PostingFields'
import { Perm } from '../api/enums'

const text = (v: string) => v.trim() || null

/** The form of one template: the same boxes as "Soạn bài tập", every one optional but the name. */
function TemplateForm({ kindId, t, onDone }: { kindId: string; t?: AssignmentTemplate; onDone: () => void }) {
  const save = useSaveTemplate()
  const [name, setName] = useState(t?.name ?? '')
  const [title, setTitle] = useState(t?.title ?? '')
  const [description, setDescription] = useState(t?.description ?? '')
  const [points, setPoints] = useState(t?.max_points ? String(t.max_points) : '')
  const [rows, setRows] = useState<Row[]>(rowsOf(t?.criteria ?? []))
  const [answerKey, setAnswerKey] = useState(t?.answer_key ?? '')
  const [checkPrompt, setCheckPrompt] = useState(t?.check_prompt ?? '')
  const [language, setLanguage] = useState(t?.language ?? '')
  const [topic, setTopic] = useState(t?.topic_name ?? '')
  const [files, setFiles] = useState<MaterialIn[]>(t?.materials ?? [])
  const criteria = criteriaOf(rows)
  const sum = criteria.reduce((a, c) => a + c.points, 0)
  const total = parseInt(points) || null
  const rubricOk = criteria.length === 0 || total === null || Math.abs(sum - total) < 0.01
  const body: AssignmentTemplateIn = { name: name.trim(), title: text(title), description: text(description), max_points: total, criteria: criteria.length ? criteria : null, answer_key: text(answerKey),
    check_prompt: text(checkPrompt), language: language || null, topic_name: text(topic), materials: files.filter((f) => f.url.trim()).map((f) => ({ ...f, url: f.url.trim() })) }
  return (
    <Card className="flex flex-col gap-3 p-5">
      <input aria-label="Tên bài tập mẫu" placeholder="Tên bài tập mẫu (để chọn lại sau này)" value={name} onChange={(e) => setName(e.target.value)} className={`${field} text-sm font-semibold`} />
      <input aria-label="Tiêu đề" placeholder="Tiêu đề bài tập" value={title} onChange={(e) => setTitle(e.target.value)} className={field} />
      <textarea aria-label="Đề bài" placeholder="Đề bài cho học sinh" rows={5} value={description} onChange={(e) => setDescription(e.target.value)} className={field} />
      <label className="flex items-center gap-2 text-[13px] font-medium">Tổng điểm<input aria-label="Tổng điểm" inputMode="numeric" value={points} onChange={(e) => setPoints(e.target.value)} className={`${field} w-20`} /></label>
      <Label>Thang điểm</Label>
      <CriteriaEditor rows={rows} setRows={setRows} points={points} />
      <Label>Tệp đính kèm</Label>
      <AttachedFiles files={files} setFiles={setFiles} />
      {files.length < 10 && <DriveAttach onPick={(picked) => setFiles((cur) => addPicked(cur, picked))} />}
      <p className="text-xs text-ink-3">Tệp trên Drive của một giáo viên chỉ mở được với người có quyền xem tệp đó.</p>
      <Label>Đáp án và cách kiểm tra</Label>
      <textarea aria-label="Đáp án" placeholder="Đáp án (tuỳ chọn)" rows={3} value={answerKey} onChange={(e) => setAnswerKey(e.target.value)} className={field} />
      <textarea aria-label="Cách kiểm tra" placeholder="Cách kiểm tra (tuỳ chọn)" rows={2} value={checkPrompt} onChange={(e) => setCheckPrompt(e.target.value)} className={field} />
      <div className="grid gap-2 sm:grid-cols-2">
        <input aria-label="Chủ đề trong Classroom" placeholder="Chủ đề trong Classroom (tuỳ chọn)" value={topic} onChange={(e) => setTopic(e.target.value)} className={field} />
        <select aria-label="Ngôn ngữ bài nói" value={language} onChange={(e) => setLanguage(e.target.value)} className={field}><option value="">Bài nói: tự nhận ra</option><option value="vi">Bài nói: Tiếng Việt</option><option value="en">Bài nói: Tiếng Anh</option></select>
      </div>
      {save.isError && <Notice tone="bad">{explain(save.error)}</Notice>}
      {!rubricOk && <p className="text-xs text-bad">Thang điểm cộng lại phải bằng tổng điểm.</p>}
      <div className="flex gap-2"><Button variant="primary" className="flex-1" busy={save.isPending} disabled={name.trim().length < 2 || !rubricOk}
        onClick={() => save.mutate({ kindId, id: t?.id, body }, { onSuccess: onDone })}>{t ? 'Lưu thay đổi' : 'Lưu bài tập mẫu'}</Button><Button onClick={onDone}>Huỷ</Button></div>
    </Card>
  )
}

function KindTemplates({ kindId, manage }: { kindId: string; manage: boolean }) {
  const list = useKindTemplates(kindId)
  const del = useDeleteTemplate()
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  useEffect(() => setEditing(null), [kindId])
  if (list.isPending) return <Loading />
  if (list.isError) return <ErrorBox onRetry={() => list.refetch()} />
  const open = editing === 'new' ? <TemplateForm kindId={kindId} onDone={() => setEditing(null)} />
    : list.data.items.filter((t) => t.id === editing).map((t) => <TemplateForm key={t.id} kindId={kindId} t={t} onDone={() => setEditing(null)} />)
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="min-w-0 text-sm font-semibold">Bài tập mẫu của «{list.data.kind.name}»</h2>
        {!editing && manage && <Button variant="primary" onClick={() => setEditing('new')}><Plus className="size-4" aria-hidden />Thêm bài tập mẫu</Button>}</div>
      {open}
      {!editing && list.data.items.length === 0 && <Card><Empty>Loại lớp này chưa có bài tập mẫu.</Empty></Card>}
      {!editing && list.data.items.map((t) => (
        <Card key={t.id} className="flex flex-wrap items-start justify-between gap-3 p-4">
          <div className="flex min-w-0 flex-1 basis-40 flex-col gap-1"><b className="text-sm">{t.name}</b>
            <p className="truncate text-xs text-ink-2">{[t.title, t.max_points !== null && `${t.max_points} điểm`, t.criteria.length > 0 && `${t.criteria.length} tiêu chí`, t.materials.length > 0 && `${t.materials.length} tệp`].filter(Boolean).join(' · ')}</p></div>
          {manage && <div className="flex shrink-0 gap-2"><Button onClick={() => setEditing(t.id)}>Sửa</Button>
            <Button variant="danger" aria-label={`Xoá ${t.name}`} busy={del.isPending && del.variables === t.id} onClick={() => { if (window.confirm(`Xoá bài tập mẫu «${t.name}»? Các bài đã đăng không bị ảnh hưởng.`)) del.mutate(t.id) }}>Xoá</Button></div>}
        </Card>))}
      {del.isError && <Notice tone="bad">{explain(del.error)}</Notice>}
    </div>
  )
}

/** Kinds of class on the left, the ready-made assignments of the chosen kind on the right. */
export function Templates() {
  const manage = can(useSession().data, Perm.TEMPLATES_MANAGE)  // a teacher reads what the business keeps, and posts from it
  const kinds = useClassKinds()
  const create = useCreateKind()
  const rename = useRenameKind()
  const remove = useDeleteKind()
  const [picked, setPicked] = useState('')
  const [name, setName] = useState('')
  const items = kinds.data?.items ?? []
  const current = items.find((k) => k.id === picked) ?? items[0]
  if (kinds.isPending) return <div className="p-4 sm:p-8"><Loading /></div>
  if (kinds.isError) return <div className="p-4 sm:p-8"><ErrorBox onRetry={() => kinds.refetch()} /></div>
  const add = () => create.mutate(name.trim(), { onSuccess: (k) => { setName(''); setPicked(k.id) } })
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-4 sm:p-6 lg:px-10 lg:py-7 [&>*]:shrink-0">
      <PageHeader title="Bài tập mẫu" subtitle="Mỗi loại lớp có những bài tập riêng. Khi đăng bài, chọn một bài tập mẫu để điền sẵn các ô." />
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-5 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <Card className="flex flex-col gap-3 p-4">
          <Label>Loại lớp</Label>
          {items.length === 0 && <p className="text-[13px] text-ink-3">{manage ? 'Chưa có loại lớp nào. Thêm loại đầu tiên, ví dụ «IELTS» hay «Thiếu nhi».' : 'Chưa có loại lớp nào.'}</p>}
          <ul className="flex flex-col gap-1">{items.map((k) => (
            <li key={k.id}><button aria-pressed={current?.id === k.id} onClick={() => setPicked(k.id)}
              className={`flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-[13px] ${current?.id === k.id ? 'bg-accent-soft font-semibold text-accent' : 'hover:bg-app'}`}>
              <span className="truncate">{k.name}</span><span className="flex shrink-0 gap-1"><Badge>{k.templates} mẫu</Badge></span></button></li>))}</ul>
          {manage && <div className="flex gap-2"><input aria-label="Tên loại lớp mới" placeholder="Tên loại lớp mới" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && name.trim().length >= 2 && add()} className={`${field} min-w-0 flex-1`} />
            <Button variant="primary" busy={create.isPending} disabled={name.trim().length < 2} onClick={add}>Thêm</Button></div>}
          {create.isError && <Notice tone="bad">{explain(create.error)}</Notice>}
          {current && manage && <div className="flex gap-2 border-t border-line pt-3">
            <Button onClick={() => { const n = window.prompt('Tên mới của loại lớp', current.name); if (n && n.trim().length >= 2) rename.mutate({ id: current.id, name: n.trim() }) }}>Đổi tên</Button>
            <Button variant="danger" busy={remove.isPending} onClick={() => { if (window.confirm(`Xoá loại lớp «${current.name}» cùng ${current.templates} bài tập mẫu? Các bài đã đăng không bị ảnh hưởng.`)) remove.mutate(current.id, { onSuccess: () => setPicked('') }) }}>Xoá loại lớp</Button></div>}
          {rename.isError && <Notice tone="bad">{explain(rename.error)}</Notice>}
        </Card>
        {current ? <KindTemplates kindId={current.id} manage={manage} /> : <Card><Empty>{manage ? 'Thêm một loại lớp để bắt đầu.' : 'Chưa có loại lớp nào.'}</Empty></Card>}
      </div>
    </div>
  )
}
