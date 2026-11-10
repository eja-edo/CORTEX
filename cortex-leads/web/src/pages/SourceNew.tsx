import { Check, Lock } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { explain } from '../api/client'
import { useCreateSource, useDescribeMcp, useSources } from '../api/hooks'
import type { McpTool } from '../api/types'
import { Button, Card, ErrorBox, Loading, Notice, PageHeader } from '../components/ui'

const input = 'rounded-lg border border-line px-3 py-2.5 text-sm font-normal'
const Field = ({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) =>
  <label className="flex flex-col gap-1.5 text-[13px] font-semibold">{label}{children}{hint && <span className="text-xs font-normal text-ink-3">{hint}</span>}</label>
const Step = ({ n, title, children }: { n: number; title: string; children: ReactNode }) =>
  <Card className="flex flex-col gap-3 p-5"><h2 className="flex items-center gap-2 text-[15px] font-bold"><span className="flex size-6 items-center justify-center rounded-full bg-accent-soft text-xs text-accent">{n}</span>{title}</h2>{children}</Card>
const hostOf = (url: string) => { try { return new URL(url).hostname } catch { return '' } }

export function SourceNew() {
  const nav = useNavigate()
  const sources = useSources()
  const create = useCreateSource()
  const describe = useDescribeMcp()
  const [kind, setKind] = useState<'http_readonly' | 'mcp'>('http_readonly')
  const [f, setF] = useState({ name: '', description: '', url: '', host: '', auth_header: '', secret: '' })
  const [tool, setTool] = useState<string | null>(null)
  const [sandbox, setSandbox] = useState<string>('')
  const set = (k: keyof typeof f, v: string) => setF((p) => ({ ...p, [k]: v }))
  if (sources.isPending) return <Loading />
  if (sources.isError) return <ErrorBox onRetry={() => sources.refetch()} />
  const host = f.host || hostOf(f.url)
  const common = { url: f.url.trim(), host, auth_header: f.auth_header || undefined, secret: f.secret || undefined }
  const tools: McpTool[] | undefined = describe.data?.tools
  const attachable = sources.data.attachable
  const ok = /^[a-z0-9][a-z0-9-]{1,39}$/.test(f.name) && f.url.startsWith('https://') && !!host && !!(sandbox || attachable[0]) && (kind === 'http_readonly' ? f.url.includes('{q}') : !!tool)
  const save = () => create.mutate({ kind, name: f.name, description: f.description, ...common, sandbox_id: sandbox || attachable[0].id, ...(kind === 'mcp' ? { tool: tool! } : {}) },
    { onSuccess: () => nav('/tools') })
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-4 sm:p-6 lg:p-8 [&>*]:shrink-0">
      <p className="text-[13px] text-ink-2"><Link to="/tools" className="hover:underline">Công cụ & kết nối</Link> / <b className="text-ink">Thêm nguồn dữ liệu</b></p>
      <PageHeader title="Thêm nguồn dữ liệu" />
      <div className="flex max-w-3xl flex-col gap-4">
        <Step n={1} title="Loại nguồn">
          <div role="radiogroup" aria-label="Loại nguồn" className="flex gap-3">{([['http_readonly', 'Nguồn HTTP', 'Một địa chỉ https, chỉ đọc (GET)'], ['mcp', 'MCP server', 'Máy chủ MCP từ xa, chỉ đọc, chọn đúng một công cụ']] as const).map(([id, t, d]) => (
            <button key={id} role="radio" aria-checked={kind === id} onClick={() => { setKind(id); setTool(null); describe.reset() }} className={`flex-1 rounded-[10px] border p-3.5 text-left ${kind === id ? 'border-2 border-accent bg-accent-soft' : 'border-line'}`}>
              <b className="block text-sm">{t}</b><span className="text-xs text-ink-2">{d}</span></button>))}</div>
        </Step>
        <Step n={2} title="Địa chỉ và khoá">
          <div className="flex flex-col gap-4 sm:flex-row"><Field label="Tên ngắn" hint="Chữ thường, số, gạch ngang"><input className={input} value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="kho-hang" /></Field>
            <Field label="Mô tả"><input className={input} value={f.description} onChange={(e) => set('description', e.target.value)} placeholder="Tồn kho theo mã" /></Field></div>
          <Field label="Địa chỉ (chỉ https)" hint={kind === 'http_readonly' ? 'Đặt {q} ở chỗ câu hỏi sẽ được điền, trong đường dẫn hoặc tham số, không bao giờ trong tên máy chủ.' : undefined}>
            <input className={input} value={f.url} onChange={(e) => set('url', e.target.value)} placeholder={kind === 'mcp' ? 'https://mcp.lms.example/mcp' : 'https://api.shop.example/v1/stock?sku={q}'} /></Field>
          <div className="flex flex-col gap-4 sm:flex-row"><Field label="Máy chủ được phép gọi"><input className={input} value={host} onChange={(e) => set('host', e.target.value)} placeholder="api.shop.example" /></Field>
            <Field label="Tên header chứa khoá" hint="Bỏ trống nếu không cần khoá"><input className={input} value={f.auth_header} onChange={(e) => set('auth_header', e.target.value)} placeholder="Authorization" /></Field></div>
          <Field label="Khoá truy cập (mã hoá, không hiện lại)"><input type="password" autoComplete="off" className={input} value={f.secret} onChange={(e) => set('secret', e.target.value)} placeholder="••••••••••••" /></Field>
        </Step>
        {kind === 'mcp' && (
          <Step n={3} title="Xem định nghĩa server đưa ra">
            <p className="text-xs text-ink-2">Chọn đúng một công cụ. Định nghĩa bạn thấy ở đây sẽ được ghim: server đổi sau này là bị khoá.</p>
            <Button className="self-start" busy={describe.isPending} disabled={!f.url.startsWith('https://') || !host} onClick={() => { setTool(null); describe.mutate(common) }}>Đọc định nghĩa từ máy chủ</Button>
            {describe.isError && <Notice tone="bad">{explain(describe.error)}</Notice>}
            {tools && <div role="radiogroup" aria-label="Công cụ" className="flex flex-col gap-2">{tools.map((t) => (
              <button key={t.name} role="radio" aria-checked={tool === t.name} disabled={!t.read_only} onClick={() => setTool(t.name)}
                className={`flex flex-wrap items-center gap-3 rounded-[10px] border p-3 text-left ${tool === t.name ? 'border-2 border-accent bg-accent-soft' : 'border-line'} ${t.read_only ? '' : 'opacity-60'}`}>
                <span className="min-w-0 flex-1 basis-48"><b className="block text-sm">{t.name}</b><span className="text-xs text-ink-2">{t.description}</span></span>
                {!t.read_only && <span className="flex items-center gap-1 text-xs font-semibold text-bad"><Lock className="size-3.5" aria-hidden />Có ghi, không gắn được</span>}</button>))}</div>}
          </Step>)}
        <Step n={kind === 'mcp' ? 4 : 3} title="Gắn vào việc của AI">
          <div role="radiogroup" aria-label="Việc của AI" className="flex flex-col gap-2">
            {attachable.map((s, i) => <label key={s.id} className="flex flex-wrap items-center gap-x-2 text-[13px]"><input type="radio" name="sandbox" checked={(sandbox || attachable[0].id) === s.id || (!sandbox && i === 0)} onChange={() => setSandbox(s.id)} />{s.title}<span className="text-xs text-ink-3">Không nói chuyện với khách</span></label>)}
            {sources.data.blocked.map((s) => <p key={s.id} className="flex flex-wrap items-center gap-x-2 text-[13px] text-ink-3"><Lock className="size-3.5" aria-hidden />{s.title}<span className="text-xs">Có nói chuyện với khách: không gắn được. Dữ liệu ngoài là thứ không đáng tin.</span></p>)}
            {attachable.length === 0 && <Notice tone="warn">Thiếu việc «Báo cáo cho chủ» của AI. Nhờ người hỗ trợ kỹ thuật thêm.</Notice>}
          </div>
        </Step>
        {create.isError && <Notice tone="bad">{explain(create.error)}</Notice>}
        <div className="flex gap-2"><Button variant="primary" disabled={!ok} busy={create.isPending} onClick={save}><Check className="size-4" aria-hidden />Ghim và thêm nguồn</Button><Link to="/tools"><Button>Huỷ</Button></Link></div>
      </div>
    </div>
  )
}
