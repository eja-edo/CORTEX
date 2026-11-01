import { Check, Lock, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { explain } from '../api/client'
import { useCreateSkill, useEditSkill, useFormOptions, usePreviewSkill, useSkill } from '../api/hooks'
import type { SkillSpec } from '../api/types'
import { Button, Card, ErrorBox, Label, Loading, Notice, PageHeader } from '../components/ui'

const BLANK: SkillSpec = { template: 'khach_im', slug: '', description: '', instructions: '', after_hours: 20, intent: null, max_touches: 2, never_say: [], must_handoff: [] }
const valid = (s: SkillSpec) => /^[a-z0-9][a-z0-9-]{2,29}$/.test(s.slug) && s.description.trim().length >= 10 && s.instructions.trim().length >= 20

const Field = ({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) =>
  <label className="flex flex-1 flex-col gap-1.5 text-[13px] font-semibold">{label}{children}{hint && <span className="text-xs font-normal text-ink-3">{hint}</span>}</label>
const input = 'rounded-lg border border-line px-3 py-2.5 text-sm font-normal'

function Chips({ label, hint, values, onChange }: { label: string; hint: string; values: string[]; onChange: (v: string[]) => void }) {
  const [draft, setDraft] = useState('')
  const add = () => { const t = draft.trim(); if (t && !values.includes(t) && t.length <= 60) onChange([...values, t]); setDraft('') }
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[13px] font-semibold">{label}</span>
      <div className="flex flex-wrap items-center gap-2">
        {values.map((v) => <span key={v} className="inline-flex items-center gap-1.5 rounded-full bg-app px-2.5 py-1 text-xs font-medium">{v}
          <button type="button" aria-label={`Bỏ ${v}`} onClick={() => onChange(values.filter((x) => x !== v))}><X className="size-3 text-ink-3" /></button></span>)}
        <input aria-label={label} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }} onBlur={add}
          placeholder="Gõ rồi Enter" className="min-w-32 flex-1 rounded-lg border border-line px-2.5 py-1.5 text-xs" />
      </div>
      <span className="text-xs text-ink-3">{hint}</span>
    </div>
  )
}

export function SkillForm() {
  const { id } = useParams()
  const skill = useSkill(id)
  if (id && skill.isPending) return <Loading />
  if (id && (skill.isError || !skill.data?.form || !skill.data.can.edit)) return <div className="p-8"><Notice tone="warn">Kỹ năng này không sửa được ở đây (không tạo từ form, hoặc đã bị xoá).</Notice></div>
  return <Editor id={id} initial={id ? skill.data!.form! : BLANK} status={skill.data?.status} sandbox={skill.data?.sandbox} />
}

function Editor({ id, initial, status, sandbox }: { id?: string; initial: SkillSpec; status?: string; sandbox?: string }) {
  const opts = useFormOptions()
  const preview = usePreviewSkill()
  const create = useCreateSkill()
  const edit = useEditSkill(id ?? '')
  const nav = useNavigate()
  const [spec, setSpec] = useState<SkillSpec>(initial)
  const set = <K extends keyof SkillSpec>(k: K, v: SkillSpec[K]) => setSpec((s) => ({ ...s, [k]: v }))
  const ok = valid(spec)

  // The right-hand summary is the server's own reading of the form (lint included), refreshed as the person types.
  const { mutate: run } = preview
  useEffect(() => {
    if (!ok) return
    const t = setTimeout(() => run(spec), 400)
    return () => clearTimeout(t)
  }, [spec, ok, run])

  if (opts.isPending) return <Loading />
  if (opts.isError) return <ErrorBox onRetry={() => opts.refetch()} />
  if (!opts.data.has_sandbox) return <div className="p-8"><Notice tone="warn">Doanh nghiệp chưa có sandbox chăm sóc khách. Hãy tạo ở mục Sandbox trước.</Notice></div>
  const errors = preview.data?.errors ?? []
  const sum = preview.data?.summary
  const editing = !!id
  const m = editing ? edit : create
  const save = () => (editing ? edit.mutate(spec, { onSuccess: () => nav(`/skills/${id}`) }) : create.mutate(spec, { onSuccess: () => nav('/skills') }))

  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-8">
      <p className="text-[13px] text-ink-2"><Link to="/skills" className="hover:underline">Kỹ năng</Link> / {editing && <><Link to={`/skills/${id}`} className="hover:underline">{spec.slug && `tuy-chinh-${spec.slug}`}</Link> / </>}<b className="text-ink">{editing ? 'Sửa' : 'Tạo kỹ năng'}</b></p>
      <PageHeader title={editing ? `Sửa kỹ năng tuy-chinh-${spec.slug}` : 'Tạo kỹ năng từ mẫu'} />
      {editing && <Notice tone="ai"><span><b>Bạn đang sửa kỹ năng này.</b> {status === 'draft' ? 'Đang là bản nháp nên chưa ảnh hưởng khách.' : 'Lưu sẽ áp dụng ngay.'} Mỗi lần sửa được lưu lại và khôi phục được. {status === 'shadow' ? 'Kỹ năng đang chạy thử: số lượt thử tính lại từ đầu vì nội dung đã đổi. ' : ''}Tên kỹ năng không đổi được.{sandbox ? ` Chạy trong sandbox ${sandbox}.` : ''}</span></Notice>}
      <div className="flex min-h-0 flex-1 gap-5">
        <Card className="flex min-w-0 flex-1 flex-col gap-5 p-6">
          <div className="flex flex-col gap-1.5"><span className="text-[13px] font-semibold">Mẫu</span>
            <div role="radiogroup" aria-label="Mẫu" className="flex gap-3">{opts.data.templates.map((t) => (
              <button key={t.id} role="radio" aria-checked={spec.template === t.id} onClick={() => set('template', t.id)}
                className={`flex-1 rounded-[10px] border p-3.5 text-left text-sm font-semibold ${spec.template === t.id ? 'border-2 border-accent bg-accent-soft' : 'border-line'}`}>{t.label}</button>))}</div></div>
          <div className="flex gap-4">
            <Field label="Tên ngắn" hint="Chữ thường, số, gạch ngang"><input className={input} value={spec.slug} disabled={editing} onChange={(e) => set('slug', e.target.value)} placeholder="nhac-gia" /></Field>
            <Field label="Mô tả một câu"><input className={input} value={spec.description} onChange={(e) => set('description', e.target.value)} placeholder="Hỏi lại khách đã hỏi giá rồi im quá nửa ngày" /></Field>
          </div>
          {spec.template === 'khach_im' && (
            <div className="flex gap-4">
              <Field label="Hỏi lại sau khi khách im (giờ)"><input type="number" min={4} max={72} className={input} value={spec.after_hours} onChange={(e) => set('after_hours', Number(e.target.value))} /></Field>
              <Field label="Chỉ với khách có ý định"><select className={input} value={spec.intent ?? ''} onChange={(e) => set('intent', e.target.value || null)}>
                <option value="">Mọi khách</option>{opts.data.intents.map((i) => <option key={i.id} value={i.id}>{i.label}</option>)}</select></Field>
              <div className="flex flex-col gap-1.5"><span className="text-[13px] font-semibold">Số lần nhắn tối đa</span>
                <div role="radiogroup" aria-label="Số lần nhắn tối đa" className="flex overflow-hidden rounded-lg border border-line">{[1, 2, 3].map((n) => (
                  <button key={n} role="radio" aria-checked={spec.max_touches === n} onClick={() => set('max_touches', n)} className={`px-5 py-2.5 text-[13px] font-semibold ${spec.max_touches === n ? 'bg-accent text-white' : 'text-ink-2'}`}>{n}</button>))}</div></div>
            </div>)}
          <Field label="Cách làm của doanh nghiệp" hint="Viết như dặn một nhân viên mới. Càng cụ thể càng tốt."><textarea rows={4} className={input} value={spec.instructions} onChange={(e) => set('instructions', e.target.value)} /></Field>
          <Chips label="Cụm không được nói thêm" hint="Cộng thêm vào các cụm cấm sẵn của doanh nghiệp, không thay thế." values={spec.never_say} onChange={(v) => set('never_say', v)} />
          <Chips label="Việc phải chuyển cho người thêm" hint="Cộng thêm vào: giảm giá, khiếu nại, ngoài catalog, đòi gặp người." values={spec.must_handoff} onChange={(v) => set('must_handoff', v)} />
        </Card>
        <div className="flex w-96 shrink-0 flex-col gap-4">
          <Card className="flex flex-col gap-3 p-5" >
            <h2 className="text-[15px] font-bold">Kỹ năng này sẽ làm gì</h2>
            {!sum ? <p className="text-[13px] text-ink-3">{ok ? 'Đang kiểm tra…' : 'Điền tên, mô tả và cách làm để xem.'}</p> : <>
              <Label>Khi nào chạy</Label><p className="text-[13px]">{sum.trigger}</p>
              <Label>AI được dùng</Label>{sum.tools.map((t) => <p key={t} className="flex gap-2 text-[13px]"><Check className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />{t}</p>)}</>}
          </Card>
          <Card className="flex flex-col gap-3 p-5">
            <h2 className="text-[15px] font-bold">Luôn bị khoá với kỹ năng từ form</h2>
            {opts.data.locked.map((t) => <p key={t} className="flex gap-2 text-[13px]"><Lock className="mt-0.5 size-4 shrink-0 text-ink-3" aria-hidden />{t}</p>)}
          </Card>
          <Notice tone="ai"><span><b>Luật chung luôn áp dụng.</b> {opts.data.always}</span></Notice>
          {errors.length > 0 && <Notice tone="bad"><span>{errors.join('; ')}</span></Notice>}
          {m.isError && <Notice tone="bad">{explain(m.error)}</Notice>}
          <div className="flex gap-2"><Button variant="primary" className="flex-1" disabled={!ok || errors.length > 0} busy={m.isPending} onClick={save}>{editing ? (status === 'draft' ? 'Lưu thay đổi' : 'Lưu và áp dụng ngay') : 'Lưu bản nháp'}</Button>
            <Link to={editing ? `/skills/${id}` : '/skills'}><Button>Huỷ</Button></Link></div>
          {!editing && <p className="text-xs text-ink-3">Sau khi lưu: chạy thử ít nhất 10 lượt trên tin thật, bạn đọc nháp thử rồi mới bật được.</p>}
        </div>
      </div>
    </div>
  )
}
