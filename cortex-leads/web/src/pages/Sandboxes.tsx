import { Boxes } from 'lucide-react'
import { Link } from 'react-router-dom'
import { explain } from '../api/client'
import { useSandboxVerb, useSandboxes } from '../api/hooks'
import type { SandboxItem } from '../api/types'
import { compact } from '../components/format'
import { Badge, Button, Card, ErrorBox, Loading, Meter, Notice } from '../components/ui'

const MODES: Record<SandboxItem['send_mode'], string> = { manual: 'Chế độ nháp', auto: 'Tự gửi khi đủ điều kiện' }

function SandboxCard({ sb, owner }: { sb: SandboxItem; owner: boolean }) {
  const verb = useSandboxVerb()
  const paused = sb.status === 'paused'
  return (
    <Card className="flex flex-col gap-4 p-5">
      <div className="flex flex-wrap items-center gap-2.5">
        <span className="flex size-9 items-center justify-center rounded-lg bg-accent-soft text-accent" aria-hidden><Boxes className="size-[18px]" /></span>
        <div className="min-w-0 flex-1 basis-40"><h3 className="truncate text-base font-bold">{sb.title}</h3><p className="truncate text-xs text-ink-2">{sb.about}</p></div>
        <Badge tone={paused ? 'bad' : 'ok'}>{paused ? 'Đang tạm dừng' : 'Đang chạy'}</Badge>
        <Badge>{sb.customer_facing ? MODES[sb.send_mode] : sb.purpose === 'owner_digest' ? 'Chỉ đọc số liệu' : 'Không nhắn khách'}</Badge>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row sm:gap-6">
        <Meter label="Lượt chạy hôm nay" value={sb.usage.runs} total={sb.budget.runs_per_day} />
        <Meter label="Token hôm nay" value={sb.usage.tokens} total={sb.budget.tokens_per_day} tone="ai" />
      </div>
      <dl className="flex flex-wrap gap-x-8 gap-y-3 text-[13px]">
        <div><dt className="text-[11px] text-ink-3">Kỹ năng đang bật</dt><dd className="font-medium">{sb.skills.live}{sb.skills.shadow ? ` (${sb.skills.shadow} đang thử)` : ''}</dd></div>
        {sb.customer_facing
          ? <div><dt className="text-[11px] text-ink-3">Kênh nối</dt><dd className="font-medium">{sb.channels.length ? sb.channels.map((c) => `${c.kind === 'messenger' ? 'Messenger' : c.kind}${c.sends ? '' : ' (chỉ nhận)'}`).join(', ') : 'Chưa nối kênh khách'}</dd></div>
          : sb.flow && <div><dt className="text-[11px] text-ink-3">Luồng</dt><dd className="font-medium">{sb.flow}</dd></div>}
        <div><dt className="text-[11px] text-ink-3">Token tối đa mỗi ngày</dt><dd className="font-medium">{sb.budget.tokens_per_day ? compact(sb.budget.tokens_per_day) : '–'}</dd></div>
      </dl>
      {verb.isError && <Notice tone="bad">{explain(verb.error)}</Notice>}
      {owner && <div className="flex flex-wrap gap-2">
        <Link to={`/sandboxes/${sb.id}`}><Button>Xem chi tiết</Button></Link>
        {paused ? <Button variant="primary" busy={verb.isPending} onClick={() => verb.mutate({ id: sb.id, verb: 'resume' })}>Bật lại</Button>
          : <Button variant="danger" busy={verb.isPending} onClick={() => verb.mutate({ id: sb.id, verb: 'pause' })}>Tạm dừng</Button>}
      </div>}
    </Card>
  )
}

/** What the AI does for the business, one card per job. Every job a business can have exists from its first day, so there is nothing to
 * create here: the owner pauses a job, watches its budget, and opens it to see its tools. Lives in Cài đặt → AI. */
export function AiJobs() {
  const q = useSandboxes()
  return (
    <section aria-label="Việc của AI" className="flex flex-col gap-3">
      <div><h2 className="text-base font-bold">Việc của AI</h2><p className="mt-0.5 text-[13px] text-ink-2">Mỗi việc dùng kỹ năng, công cụ và ngân sách riêng. Đổi cách AI làm ở trang Kỹ năng.</p></div>
      {q.isPending ? <Loading /> : q.isError ? <ErrorBox onRetry={() => q.refetch()} /> : q.data.items.map((sb) => <SandboxCard key={sb.id} sb={sb} owner />)}
    </section>
  )
}
