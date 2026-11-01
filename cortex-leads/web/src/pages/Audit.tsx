import { Download, ShieldCheck, X } from 'lucide-react'
import { useState } from 'react'
import { explain } from '../api/client'
import { auditQueryString, useAudit, useAuditEvent, useAuditVerify, useSession } from '../api/hooks'
import type { AuditItem, AuditQuery } from '../api/types'
import { DateRange, type Range } from '../components/DateRange'
import { Time } from '../components/Time'
import { full } from '../components/format'
import { Badge, Button, Card, Empty, ErrorBox, Loading, Notice, PageHeader, type Tone } from '../components/ui'

const RESULT: Record<AuditItem['result'], { label: string; tone: Tone }> = {
  success: { label: 'Thành công', tone: 'ok' },
  denied: { label: 'Bị từ chối', tone: 'warn' },
  failed: { label: 'Thất bại', tone: 'bad' },
}
const SIZES = [10, 20, 50, 100]

/** 1 … 4 [5] 6 … 20: the pages around the current one, always the first and the last. */
export function pageList(page: number, pages: number): (number | '…')[] {
  const keep = [...new Set([1, page - 1, page, page + 1, pages])].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b)
  return keep.flatMap((n, i) => (i > 0 && n - keep[i - 1] > 1 ? ['…' as const, n] : [n]))
}

export function Pager({ page, pages, total, size, onPage, onSize }: { page: number; pages: number; total: number; size: number; onPage: (p: number) => void; onSize: (s: number) => void }) {
  const from = total ? (page - 1) * size + 1 : 0
  const to = Math.min(page * size, total)
  const btn = 'flex h-8 min-w-8 items-center justify-center rounded-lg border border-line px-2 text-[13px] disabled:cursor-not-allowed disabled:text-ink-3'
  return (
    <nav aria-label="Phân trang" className="flex items-center justify-between gap-4 border-t border-line px-4 py-3 text-[13px] text-ink-2">
      <span>Hiển thị {from}–{to} / {total} dòng</span>
      <div className="flex items-center gap-1.5">
        <button className={btn} disabled={page <= 1} onClick={() => onPage(page - 1)}>Trước</button>
        {pageList(page, pages).map((n, i) => n === '…'
          ? <span key={`g${i}`} aria-hidden className="px-1 text-ink-3">…</span>
          : <button key={n} className={`${btn} ${n === page ? 'border-accent bg-accent-soft font-semibold text-accent' : ''}`} aria-current={n === page ? 'page' : undefined} aria-label={`Trang ${n}`} onClick={() => onPage(n)}>{n}</button>)}
        <button className={btn} disabled={page >= pages} onClick={() => onPage(page + 1)}>Sau</button>
      </div>
      <label className="flex items-center gap-2">Số dòng mỗi trang
        <select value={size} onChange={(e) => onSize(Number(e.target.value))} className="h-8 rounded-lg border border-line bg-surface px-2">
          {SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>
    </nav>
  )
}

function Detail({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: e, isPending, isError } = useAuditEvent(id)
  const row = (k: string, v: string | null | undefined) => v ? <div key={k}><dt className="text-[11px] text-ink-3">{k}</dt><dd className="break-all font-medium">{v}</dd></div> : null
  return (
    <aside aria-label="Chi tiết sự kiện" className="fixed inset-y-0 right-0 z-10 flex w-[420px] flex-col gap-4 overflow-y-auto border-l border-line bg-surface p-5 shadow-xl">
      <div className="flex items-start gap-2">
        <h2 className="flex-1 text-base font-bold">{e?.summary ?? 'Chi tiết'}</h2>
        <button aria-label="Đóng" onClick={onClose} className="text-ink-3 hover:text-ink"><X className="size-4" /></button>
      </div>
      {isPending && <Loading />}
      {isError && <ErrorBox>Không mở được sự kiện này.</ErrorBox>}
      {e && <>
        <dl className="grid grid-cols-2 gap-3 text-[13px]">
          {row('Thời điểm', full(e.at))}{row('Người thực hiện', `${e.actor} (${e.role})`)}{row('Hành động', e.action)}{row('Kết quả', RESULT[e.result].label)}
          {row('Đối tượng', e.object ? `${e.object.type}${e.object.label ? ` · ${e.object.label}` : ''}` : null)}
          {row('Địa chỉ IP', e.ip)}{row('Trình duyệt', e.user_agent)}{row('Mã yêu cầu', e.request_id)}{row('Phiên', e.session_id)}
        </dl>
        <div>
          <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Dữ liệu đính kèm (metadata)</h3>
          {Object.keys(e.metadata).length
            ? <pre className="max-h-96 overflow-auto rounded-lg bg-app p-3 text-xs leading-relaxed">{JSON.stringify(e.metadata, null, 2)}</pre>
            : <p className="text-[13px] text-ink-3">Sự kiện này không có dữ liệu đính kèm.</p>}
        </div>
        <p className="break-all text-[11px] text-ink-3">Dấu vân tay chuỗi: {e.hash}</p>
      </>}
    </aside>
  )
}

export function Audit() {
  const { data: me } = useSession()
  const owner = me?.role === 'owner'
  const [q, setQ] = useState<AuditQuery>({ page: 1, page_size: 20 })
  const [range, setRange] = useState<Range>({})
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const { data, isPending, isError, refetch } = useAudit(q)
  const verify = useAuditVerify()
  const set = (patch: Partial<AuditQuery>) => setQ((p) => ({ ...p, page: 1, ...patch }))
  const field = 'h-9 rounded-lg border border-line bg-surface px-2.5 text-[13px]'
  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-6">
      <PageHeader title="Nhật ký hoạt động" subtitle={owner ? 'Ai làm gì, lúc nào, từ đâu. Không ghi nội dung tin nhắn hay khoá truy cập.' : 'Các việc bạn đã làm trong hệ thống.'}
        action={owner ? <div className="flex gap-2">
          <Button busy={verify.isPending} onClick={() => verify.mutate()}><ShieldCheck className="size-4" aria-hidden />Kiểm tra toàn vẹn</Button>
          <a href={`/api/v1/audit/export?${auditQueryString({ ...q, page: undefined, page_size: undefined })}`} className="inline-flex h-9 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-[13px] font-semibold"><Download className="size-4" aria-hidden />Xuất CSV</a>
        </div> : undefined} />
      {verify.data && (verify.data.ok
        ? <Notice tone="ok">Nhật ký nguyên vẹn: {verify.data.checked} dòng liên kết đúng.</Notice>
        : <Notice tone="bad">Phát hiện dòng bị sửa hoặc mất, bắt đầu từ lúc {verify.data.first_bad ? full(verify.data.first_bad) : '?'}.</Notice>)}
      {verify.isError && <Notice tone="bad">{explain(verify.error)}</Notice>}
      <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); set({ q: search.trim() || undefined }) }}>
        <DateRange value={range} onChange={(r) => { setRange(r); set({ date_from: r.from, date_to: r.to }) }} />
        {owner && <label className="flex flex-col gap-1 text-[11px] text-ink-3">Người thực hiện
          <select className={field} value={q.actor ?? ''} onChange={(e) => set({ actor: e.target.value || undefined })}><option value="">Tất cả</option>{data?.actors.map((a) => <option key={a}>{a}</option>)}</select></label>}
        <label className="flex flex-col gap-1 text-[11px] text-ink-3">Nhóm
          <select className={field} value={q.category ?? ''} onChange={(e) => set({ category: e.target.value || undefined })}><option value="">Tất cả</option>{Object.entries(data?.categories ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="flex flex-col gap-1 text-[11px] text-ink-3">Kết quả
          <select className={field} value={q.result ?? ''} onChange={(e) => set({ result: e.target.value || undefined })}><option value="">Tất cả</option>{Object.entries(RESULT).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></label>
        <label className="flex flex-1 flex-col gap-1 text-[11px] text-ink-3">Tìm
          <input className={`${field} min-w-48`} placeholder="Tóm tắt, IP, mã yêu cầu…" value={search} onChange={(e) => setSearch(e.target.value)} /></label>
        <Button type="submit">Tìm</Button>
      </form>
      <Card className="overflow-hidden">
        {isPending ? <Loading /> : isError ? <ErrorBox onRetry={() => refetch()}>Không tải được nhật ký.</ErrorBox> : !data.items.length ? <Empty>Không có sự kiện nào khớp bộ lọc.</Empty> : (
          <table className="w-full text-left text-[13px]">
            <thead className="border-b border-line text-[11px] uppercase tracking-wide text-ink-3">
              <tr><th className="px-4 py-2.5 font-semibold">Thời điểm</th><th className="px-2 py-2.5 font-semibold">Người thực hiện</th><th className="px-2 py-2.5 font-semibold">Việc đã làm</th><th className="px-2 py-2.5 font-semibold">Kết quả</th><th className="px-2 py-2.5 font-semibold">IP</th></tr>
            </thead>
            <tbody>
              {data.items.map((e) => (
                <tr key={e.id} tabIndex={0} onClick={() => setOpen(e.id)} onKeyDown={(k) => k.key === 'Enter' && setOpen(e.id)} className="cursor-pointer border-b border-line last:border-0 hover:bg-app">
                  <td className="whitespace-nowrap px-4 py-2.5"><Time iso={e.at} as="dateTime" /></td>
                  <td className="px-2 py-2.5 font-medium">{e.actor}</td>
                  <td className="px-2 py-2.5">{e.summary}{e.has_metadata && <Badge className="ml-2">metadata</Badge>}</td>
                  <td className="px-2 py-2.5"><Badge tone={RESULT[e.result].tone}>{RESULT[e.result].label}</Badge></td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-ink-2">{e.ip ?? '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data && <Pager page={data.page} pages={data.pages} total={data.total} size={data.page_size} onPage={(page) => setQ((p) => ({ ...p, page }))} onSize={(page_size) => setQ((p) => ({ ...p, page: 1, page_size }))} />}
      </Card>
      {open && <Detail id={open} onClose={() => setOpen(null)} />}
    </div>
  )
}
