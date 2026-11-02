import { CheckCircle2, Circle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useOnboarding } from '../api/hooks'
import { Badge, Card, ErrorBox, Loading, Notice, PageHeader } from '../components/ui'

export function Onboarding() {
  const q = useOnboarding()
  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto p-8">
      <PageHeader title="Bắt đầu" subtitle="Bốn bước từ doanh nghiệp trống tới nháp đầu tiên. Mỗi bước tự đánh dấu khi việc đó thật sự đã có." />
      {q.isPending ? <Loading /> : q.isError ? <ErrorBox onRetry={() => q.refetch()} /> : <>
        {q.data.complete && <Notice tone="ok">Đã đủ bốn bước. Hộp thư sẽ có nháp cho khách cần người.</Notice>}
        <ol className="flex max-w-3xl flex-col gap-3">
          {q.data.steps.map((s, i) => (
            <li key={s.id}><Card className="flex items-start gap-4 p-5">
              {s.done ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-ok" aria-label="Đã xong" /> : <Circle className="mt-0.5 size-5 shrink-0 text-ink-3" aria-label="Chưa xong" />}
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <b className="text-[15px]">{i + 1}. {s.title}</b>
                <p className="text-[13px] text-ink-2">{s.hint}</p>
              </div>
              {s.done ? <Badge tone="ok">Xong{s.count > 1 ? ` · ${s.count}` : ''}</Badge> : s.href && <Link to={s.href} className="shrink-0 text-[13px] font-semibold text-accent underline">Làm bước này</Link>}
            </Card></li>))}
        </ol>
        <p className="text-xs text-ink-3">Bước 2 chưa có màn riêng; ghi trong gợi ý ở trên.</p></>}
    </div>
  )
}
