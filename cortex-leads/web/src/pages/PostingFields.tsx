import { Plus, Trash2 } from 'lucide-react'
import type { ClassroomOptions, Criterion, MaterialIn } from '../api/types'
import { Label, type Tone } from '../components/ui'

export const POSTING: Record<string, [string, Tone]> = { draft: ['Chưa tạo trên Classroom', 'warn'], classroom_draft: ['Bản nháp trong Classroom (học sinh chưa thấy)', 'warn'], scheduled: ['Đã hẹn giờ đăng', 'accent'], published: ['Đã đăng cho học sinh', 'ok'], classroom: ['Tạo trên Classroom', 'neutral'], deleted: ['Đã xoá', 'neutral'] }

/** Short forms for a list row, where the long text would push the title out. */
export const POSTING_SHORT: Record<string, string> = { draft: 'Chưa tạo', classroom_draft: 'Nháp trong Classroom', scheduled: 'Hẹn giờ', published: 'Đã đăng', classroom: 'Tạo trên Classroom', deleted: 'Đã xoá' }

/** A radio drawn as a card: the whole box is the target and the chosen one is outlined. */
export function Choice({ name, checked, onChange, disabled, children }: { name: string; checked: boolean; onChange: () => void; disabled?: boolean; children: string }) {
  return (
    <label className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-[13px] ${checked ? 'border-accent bg-accent-soft font-semibold' : 'border-line hover:border-ink-3'} ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}>
      <input type="radio" name={name} checked={checked} onChange={onChange} disabled={disabled} className="accent-accent" />{children}</label>
  )
}

/** Adds what was picked to the attachments already in the form: the same file twice is kept once, and no more than ten in all. */
export const addPicked = (have: MaterialIn[], picked: MaterialIn[]): MaterialIn[] => {
  const ids = new Set(have.map((x) => x.url))
  return [...have, ...picked.filter((x) => !ids.has(x.url))].slice(0, 10)
}
export const field = 'rounded-lg border border-line bg-surface px-2.5 py-2 text-[13px]'
export const slug = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 24) || 'tieu_chi'

/** `datetime-local` text (the browser's own time zone) to the UTC instant the server wants; empty is null. */
export const toIso = (local: string) => (local ? new Date(local).toISOString() : null)
/** The reverse, to fill a `datetime-local` box from a UTC instant. */
export const toLocal = (iso: string | null) => {
  if (!iso) return ''
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

export type When = { mode: 'now' | 'draft' | 'schedule'; due: string; scheduled: string }
export const NOW_MODE: When = { mode: 'now', due: '', scheduled: '' }

/** How it goes out and by when it is due: shown to students now, kept as a draft in Classroom, or published by Classroom at a time. */
export function WhenFields({ value, onChange }: { value: When; onChange: (v: When) => void }) {
  const set = (p: Partial<When>) => onChange({ ...value, ...p })
  return (
    <div className="flex flex-col gap-3">
      <Label>Đăng khi nào</Label>
      <div role="radiogroup" aria-label="Đăng khi nào" className="flex flex-col gap-1.5">
        {([['now', 'Đăng ngay cho học sinh'], ['draft', 'Lưu bản nháp trong Classroom (chưa ai thấy)'], ['schedule', 'Hẹn giờ để Classroom tự đăng']] as const).map(([k, text]) => (
          <Choice key={k} name="when" checked={value.mode === k} onChange={() => set({ mode: k })}>{text}</Choice>))}
      </div>
      {value.mode === 'schedule' && <label className="flex flex-col gap-1 text-[13px]">Giờ đăng<input type="datetime-local" aria-label="Giờ đăng" value={value.scheduled} onChange={(e) => set({ scheduled: e.target.value })} className={field} /></label>}
      {value.mode === 'schedule' && !value.scheduled && <p className="-mt-1 text-xs text-bad">Chọn giờ đăng.</p>}
      <label className="flex flex-col gap-1 text-[13px]">Hạn nộp (tuỳ chọn)<input type="datetime-local" aria-label="Hạn nộp" value={value.due} onChange={(e) => set({ due: e.target.value })} className={field} /></label>
    </div>
  )
}
export const whenReady = (w: When) => w.mode !== 'schedule' || Boolean(w.scheduled)
export const whenBody = (w: When) => ({ publish: w.mode !== 'draft', due: toIso(w.due), scheduled: w.mode === 'schedule' ? toIso(w.scheduled) : null })

export type Audience = { topic: string; students: { id: string; name: string }[]; some: boolean }
export const EVERYONE: Audience = { topic: '', students: [], some: false }

/** Which topic the work is filed under (an existing one or a new name) and whether the whole class gets it or only some students. */
export function AudienceFields({ options, value, onChange }: { options?: ClassroomOptions; value: Audience; onChange: (v: Audience) => void }) {
  const set = (p: Partial<Audience>) => onChange({ ...value, ...p })
  const list = options?.students ?? []
  return (
    <div className="flex flex-col gap-3">
      <Label>Chủ đề</Label>
      <input aria-label="Chủ đề trong Classroom" list="classroom-topics" placeholder="Chọn hoặc gõ tên chủ đề mới (tuỳ chọn)" value={value.topic} onChange={(e) => set({ topic: e.target.value })} className={field} />
      <datalist id="classroom-topics">{options?.topics.map((t) => <option key={t.id} value={t.name} />)}</datalist>
      {options?.problems.topics && <p className="text-xs text-ink-3">Chưa lấy được danh sách chủ đề từ Classroom{options.problems.topics === 'PERMISSION_DENIED' ? ' (tài khoản đã nối chưa cấp quyền chủ đề: hãy kết nối lại Google)' : ''}. Vẫn gõ được tên chủ đề.</p>}
      <Label>Giao cho</Label>
      <div role="radiogroup" aria-label="Giao cho" className="flex flex-col gap-1.5">
        <Choice name="audience" checked={!value.some} onChange={() => set({ some: false, students: [] })}>Cả lớp</Choice>
        <Choice name="audience" checked={value.some} onChange={() => set({ some: true })} disabled={list.length === 0}>Chỉ một số học sinh</Choice>
      </div>
      {value.some && <ul aria-label="Chọn học sinh" className="flex max-h-40 flex-col gap-1 overflow-y-auto rounded-lg border border-line p-2 text-[13px]">
        {list.map((s) => {
          const on = value.students.some((x) => x.id === s.id)
          return <li key={s.id}><label className="flex items-center gap-2"><input type="checkbox" checked={on} onChange={() => set({ students: on ? value.students.filter((x) => x.id !== s.id) : [...value.students, s] })} />{s.name || s.id}</label></li>
        })}</ul>}
      {value.some && value.students.length === 0 && <p className="text-xs text-bad">Chọn ít nhất một học sinh, hoặc giao cho cả lớp.</p>}
      {options?.problems.students && <p className="text-xs text-ink-3">Chưa lấy được danh sách học sinh từ Classroom.</p>}
    </div>
  )
}
export const audienceReady = (a: Audience) => !a.some || a.students.length > 0

export type Row = { label: string; points: string; descriptor: string }
export const rowsOf = (c: Criterion[]): Row[] => (c.length ? c.map((x) => ({ label: x.label, points: String(x.points), descriptor: x.descriptor })) : [{ label: '', points: '', descriptor: '' }])
export const criteriaOf = (rows: Row[]): Criterion[] => rows.filter((r) => r.label.trim()).map((r, i) => ({ id: `${slug(r.label)}${i}`, label: r.label.trim(), points: parseFloat(r.points) || 0, descriptor: r.descriptor }))

/** The grading guide's rows. They must add up to the work's points, because that is what the AI grades against. */
export function CriteriaEditor({ rows, setRows, points }: { rows: Row[]; setRows: (r: Row[]) => void; points: string }) {
  const sum = criteriaOf(rows).reduce((a, c) => a + c.points, 0)
  const total = parseFloat(points) || 0
  const ok = Math.abs(sum - total) < 0.01
  return (
    <>
      {rows.map((r, i) => <div key={i} className="flex gap-2">
        <input aria-label={`Tiêu chí ${i + 1}`} placeholder="Tiêu chí" value={r.label} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} className={`${field} min-w-0 flex-1`} />
        <input aria-label={`Điểm tiêu chí ${i + 1}`} placeholder="Điểm" inputMode="decimal" value={r.points} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, points: e.target.value } : x)))} className={`${field} w-16`} />
        <button aria-label={`Bỏ tiêu chí ${i + 1}`} className="text-ink-3 hover:text-bad" onClick={() => setRows(rows.filter((_, j) => j !== i))}><Trash2 className="size-4" /></button></div>)}
      <button className="flex items-center gap-1 self-start text-[13px] font-semibold text-accent" onClick={() => setRows([...rows, { label: '', points: '', descriptor: '' }])}><Plus className="size-4" aria-hidden />Thêm tiêu chí</button>
      <p className={`text-xs ${ok ? 'text-ink-3' : 'text-bad'}`}>Cộng các tiêu chí: {sum} / {total}{!ok && ' (phải bằng tổng điểm)'}</p>
    </>
  )
}
