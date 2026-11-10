import clsx from 'clsx'
import { Download, FileSpreadsheet, Plus, Search } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { explain } from '../api/client'
import { getCatalogTemplate, useCatalog, useImportCatalog } from '../api/hooks'
import type { CatalogImport, CatalogRow } from '../api/types'
import { dateOnly, dayMonth, num } from '../components/format'
import { SCard, fieldCls } from '../components/settingsUi'
import { Badge, Button, ErrorBox, Loading, Modal, Notice, PageHeader, STACK_CELL, STACK_ROW } from '../components/ui'

const MAX_BYTES = 1_000_000
const money = (p: number | null) => (p == null ? '—' : p === 0 ? 'Miễn phí' : `${num(p)} đ`)

/** Saves the sample as a file. A data address, not a blob: nothing to revoke, and the page keeps no copy. */
async function downloadTemplate() {
  const t = await getCatalogTemplate()
  const a = document.createElement('a')
  a.href = `data:text/csv;charset=utf-8,${encodeURIComponent(`﻿${t.csv}`)}`  // a BOM so Excel reads Vietnamese letters as UTF-8
  a.download = t.filename
  a.click()
}

/** Two steps: the file is checked first (nothing is written), and only then "Lưu" saves what was shown. */
function ImportDialog({ onClose, onSaved }: { onClose: () => void; onSaved: (r: CatalogImport) => void }) {
  const run = useImportCatalog()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<{ name: string; kb: string; text: string; lines: number } | null>(null)
  const [checked, setChecked] = useState<CatalogImport | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const reset = () => { setFile(null); setChecked(null); setProblem(null); run.reset(); if (input.current) input.current.value = '' }
  const choose = async (f: File | undefined) => {
    if (!f) return
    reset()
    if (f.size > MAX_BYTES) { setProblem('Tệp lớn quá (tối đa 1 MB). Hãy tách thành nhiều tệp.'); return }
    const text = await f.text()
    setFile({ name: f.name, kb: (f.size / 1000).toFixed(1).replace('.', ','), text, lines: Math.max(0, text.split('\n').filter((l) => l.trim()).length - 1) })
    run.mutate({ csv: text, dry_run: true }, { onSuccess: setChecked })
  }
  const save = () => file && run.mutate({ csv: file.text, dry_run: false }, { onSuccess: (r) => { onSaved(r); onClose() } })
  return (
    <Modal title="Nhập bảng giá từ CSV" onClose={onClose} wide>
      <p className="-mt-2 text-[13px] text-ink-2">Dòng mới được thêm. Dòng đổi giá, tên, đơn vị hoặc hạn thành phiên bản mới; bản cũ vẫn giữ làm lịch sử.</p>
      <input ref={input} type="file" accept=".csv,text/csv" aria-label="Chọn tệp CSV" className={clsx(file && 'hidden', 'text-[13px]')} onChange={(e) => void choose(e.target.files?.[0])} />
      {file && (
        <div className="flex flex-col items-center gap-1 rounded-[10px] border border-accent bg-accent-soft px-5 py-5">
          <FileSpreadsheet className="size-5 text-accent" aria-hidden /><b className="text-sm">{file.name}</b><span className="text-xs text-ink-2">{file.kb} KB · {file.lines} dòng</span></div>)}
      {problem && <Notice tone="bad">{problem}</Notice>}
      {run.isPending && !checked && <Loading label="Đang kiểm tra tệp…" />}
      {run.isError && <Notice tone="bad">{explain(run.error)}</Notice>}
      {checked && (
        <div className="flex flex-col gap-2.5" aria-label="Kết quả kiểm tra">
          <b className="text-[13px]">Kết quả kiểm tra trước khi lưu</b>
          <div className="flex flex-wrap gap-2">
            <Badge tone="ok">{checked.new} mục mới</Badge><Badge tone="accent">{checked.changed} đổi → phiên bản mới</Badge>
            <Badge>{checked.unchanged} không đổi</Badge><Badge tone={checked.errors.length ? 'bad' : 'neutral'}>{checked.errors.length} dòng lỗi</Badge></div>
          {checked.errors.length > 0 && <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto rounded-lg bg-bad-soft px-3.5 py-2.5 text-[13px] text-bad">{checked.errors.map((e) => <li key={e.line}>{e.message}</li>)}</ul>}
          <p className="text-xs text-ink-3">Dòng lỗi bị bỏ qua, các dòng còn lại vẫn lưu được. Mã phải duy nhất trong tệp.</p>
        </div>)}
      <div className="flex justify-end gap-2.5">
        {file ? <Button onClick={reset}>Chọn tệp khác</Button> : <Button onClick={onClose}>Đóng</Button>}
        {checked && <Button variant="primary" busy={run.isPending} disabled={checked.to_save === 0} onClick={save}>{checked.to_save === 0 ? 'Không có gì để lưu' : `Lưu ${checked.to_save} thay đổi`}</Button>}
      </div>
    </Modal>
  )
}

const stateTone = (s: CatalogRow['state']) => (s === 'expired' ? 'text-bad' : s === 'soon' ? 'text-warn' : 'text-ink')

export function Data() {
  const q = useCatalog()
  const [text, setText] = useState('')
  const [category, setCategory] = useState('')
  const [open, setOpen] = useState(false)
  const [saved, setSaved] = useState<CatalogImport | null>(null)
  const [dl, setDl] = useState<'idle' | 'busy' | 'fail'>('idle')
  const rows = useMemo(() => {
    const t = text.trim().toLowerCase()
    return (q.data?.items ?? []).filter((r) => (!category || r.category === category) && (!t || r.code.toLowerCase().includes(t) || r.name.toLowerCase().includes(t)))
  }, [q.data, text, category])
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const { stats, can_import: canImport, items } = q.data
  const template = <Button onClick={() => { setDl('busy'); downloadTemplate().then(() => setDl('idle'), () => setDl('fail')) }} busy={dl === 'busy'}><Download className="size-4" aria-hidden />Tải mẫu CSV</Button>
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-4 sm:p-6 lg:p-8 [&>*]:shrink-0">
      <PageHeader title="Dữ liệu" subtitle="Bảng giá. Mọi con số AI nói với khách đều lấy từ đây."
        action={<div className="flex gap-2.5">{template}{canImport && <Button variant="primary" onClick={() => setOpen(true)}><Plus className="size-4" aria-hidden />Nhập từ CSV</Button>}</div>} />
      {dl === 'fail' && <Notice tone="bad">Không tải được tệp mẫu. Thử lại sau.</Notice>}
      {saved && <Notice tone="ok" action={<Button onClick={() => setSaved(null)}>Đóng</Button>}>Đã lưu: {saved.new} mục mới, {saved.changed} mục đổi thành phiên bản mới{saved.errors.length ? `, bỏ qua ${saved.errors.length} dòng lỗi` : ''}.</Notice>}
      {items.length > 0 && (
      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4" aria-label="Tổng quan">
          {([[String(stats.active), 'Mục đang dùng', 'text-ink'], [String(stats.soon), 'Sắp hết hạn trong 14 ngày', stats.soon ? 'text-warn' : 'text-ink'],
            [String(stats.expired), 'Đã quá hạn', stats.expired ? 'text-bad' : 'text-ink'], [stats.last_import_at ? dayMonth(stats.last_import_at) : 'Chưa có', 'Lần nhập gần nhất qua màn này', 'text-ink']] as const).map(([v, l, tone]) => (
            <div key={l} className="flex flex-col gap-0.5 rounded-xl border border-line bg-surface px-[18px] py-3.5"><b className={clsx('text-[22px] font-bold', tone)}>{v}</b><span className="text-xs text-ink-2">{l}</span></div>))}
        </div>
      )}
      {items.length === 0 ? (
        <SCard><div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
          <b className="text-[15px]">Chưa có bảng giá nào</b>
          <p className="max-w-md text-[13px] text-ink-2">AI chỉ được nói những con số có trong bảng này. Tải tệp mẫu CSV, điền khoá học và giá, rồi nhập vào.</p>
          {!canImport && <p className="text-xs text-ink-3">Chỉ chủ doanh nghiệp nhập được bảng giá.</p>}
        </div></SCard>
      ) : (<>
        <div className="flex flex-wrap gap-3">
          <label className="relative w-full max-w-sm"><Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
            <input aria-label="Tìm theo mã hoặc tên" placeholder="Tìm theo mã hoặc tên" className={`${fieldCls} !h-9 pl-9`} value={text} onChange={(e) => setText(e.target.value)} /></label>
          <select aria-label="Lọc theo nhóm" className={`${fieldCls} !h-9 !w-auto`} value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Mọi nhóm</option>{q.data.categories.map((c) => <option key={c}>{c}</option>)}</select>
        </div>
        <SCard className="overflow-x-auto">
          <table className="w-full text-[13px] max-md:block">
            <thead className="max-md:hidden"><tr className="border-b border-line bg-gray-50 text-left text-[11px] font-semibold text-ink-3">
              {['MÃ', 'TÊN', 'NHÓM', 'GIÁ', 'HẠN', 'PHIÊN BẢN'].map((h) => <th key={h} scope="col" className="px-5 py-2.5">{h}</th>)}</tr></thead>
            <tbody className="max-md:block">{rows.map((r) => (
              <tr key={r.code} className={`border-b border-line last:border-b-0 ${STACK_ROW}`}>
                <td data-label="Mã" className={`px-5 py-3 font-mono text-xs ${STACK_CELL}`}>{r.code}</td><td data-label="Tên" className={`px-5 py-3 font-semibold max-md:col-span-2 max-md:row-start-1 ${STACK_CELL}`}>{r.name}</td><td data-label="Nhóm" className={`px-5 py-3 ${STACK_CELL}`}>{r.category ?? '—'}</td>
                <td data-label="Giá" className={`px-5 py-3 ${STACK_CELL}`}>{money(r.price)}{r.unit && r.price ? <span className="text-ink-3"> / {r.unit}</span> : null}</td>
                <td data-label="Hạn" className={clsx('px-5 py-3', STACK_CELL, stateTone(r.state))}>{r.valid_until ? dateOnly(r.valid_until) : '—'}{r.state === 'expired' && <span className="ml-1.5 text-xs">(quá hạn)</span>}{r.state === 'soon' && <span className="ml-1.5 text-xs">(sắp hết)</span>}</td>
                <td data-label="Phiên bản" className={`px-5 py-3 text-ink-2 ${STACK_CELL}`}>v{r.version}</td></tr>))}</tbody>
          </table>
          {rows.length === 0 && <p className="px-6 py-8 text-center text-[13px] text-ink-3">Không có mục nào khớp.</p>}
        </SCard>
      </>)}
      {open && <ImportDialog onClose={() => setOpen(false)} onSaved={setSaved} />}
    </div>
  )
}
