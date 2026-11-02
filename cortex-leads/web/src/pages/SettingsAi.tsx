import { Link } from 'react-router-dom'
import { explain } from '../api/client'
import { useAiOverview, useKillSwitch, useSendMode } from '../api/hooks'
import type { AiOverview } from '../api/types'
import { Badge, Button, Card, ErrorBox, Loading, Notice } from '../components/ui'

type Box = AiOverview['sandboxes'][number]

function SandboxCard({ sb }: { sb: Box }) {
  const mode = useSendMode(sb.id)
  const auto = sb.send_mode === 'auto'
  return (
    <Card className="flex flex-col gap-4 p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="min-w-0 flex-1 truncate text-[15px] font-bold">{sb.title}</h2>
        <Badge tone={sb.status === 'paused' ? 'bad' : 'ok'}>{sb.status === 'paused' ? 'Đang tạm dừng' : 'Đang chạy'}</Badge>
        <Link to={`/sandboxes/${sb.id}`} className="text-[13px] font-semibold text-accent underline">Mở sandbox</Link>
      </div>
      <div className="flex flex-col gap-2">
        <b className="text-[13px]">Chế độ gửi tin</b>
        <div role="radiogroup" aria-label="Chế độ gửi tin" className="flex flex-wrap gap-2">
          <Button aria-pressed={!auto} variant={auto ? 'secondary' : 'primary'} busy={mode.isPending} onClick={() => auto && mode.mutate('manual')}>Duyệt tay</Button>
          <Button aria-pressed={auto} variant={auto ? 'primary' : 'secondary'} busy={mode.isPending} onClick={() => auto || mode.mutate('auto')}>Tự gửi</Button>
        </div>
        <p className="text-xs text-ink-2">{auto
          ? 'Chỉ các kỹ năng được phép tự gửi mới gửi khi khách vừa nhắn, qua cùng bộ chặn như khi nhân viên bấm gửi (cửa sổ nhắn, khách từ chối, giờ làm việc). Kỹ năng khác vẫn chỉ soạn nháp.'
          : 'Mọi tin gửi cho khách đều chờ nhân viên bấm gửi. AI chỉ soạn nháp.'}</p>
        {mode.isError && <p role="alert" className="text-xs text-bad">{explain(mode.error)}</p>}
      </div>
      <div className="flex flex-col gap-1.5"><b className="text-[13px]">Kỹ năng đang chạy ({sb.skills.length})</b>
        {sb.skills.length === 0 ? <p className="text-xs text-ink-3">Chưa có kỹ năng nào chạy.</p> : sb.skills.map((k) => (
          <p key={k.name} className="text-[13px]">{k.name} · {k.status === 'live' ? 'chạy thật' : 'chạy thử'}{k.sends ? ' · có thể tự gửi' : ''}</p>))}</div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5"><b className="text-[13px]">Cụm AI không bao giờ được nói</b>
          {sb.never_say.length === 0 ? <p className="text-xs text-ink-3">Chưa có.</p> : <p className="flex flex-wrap gap-1.5">{sb.never_say.map((x) => <Badge key={x} tone="bad">{x}</Badge>)}</p>}</div>
        <div className="flex flex-col gap-1.5"><b className="text-[13px]">Việc luôn chuyển cho người</b>
          {sb.must_handoff.length === 0 ? <p className="text-xs text-ink-3">Chưa có.</p> : <p className="flex flex-wrap gap-1.5">{sb.must_handoff.map((x) => <Badge key={x} tone="warn">{x}</Badge>)}</p>}</div>
      </div>
    </Card>
  )
}

export function SettingsAi() {
  const q = useAiOverview()
  const kill = useKillSwitch()
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const paused = q.data.sandboxes.length > 0 && q.data.sandboxes.every((s) => s.status === 'paused')
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <Card className="flex flex-col gap-2 p-5 text-[13px] text-ink-2">
        <b className="text-[15px] text-ink">AI đứng sau người</b>
        <p>AI soạn nháp; mọi con số trong nháp phải trùng bảng giá, và mọi tin gửi đi đều qua cùng một đường kiểm. Khách luôn được báo đây là AI: <b className="text-ink">{q.data.disclosure}</b>.</p>
        <p>Đổi tên trợ lý ở <Link to="/settings?tab=business" className="font-semibold text-accent underline">Doanh nghiệp</Link>.</p>
      </Card>
      <Card className={`flex flex-wrap items-center gap-3 p-5 ${paused ? 'border-bad' : ''}`}>
        <span className="min-w-0 flex-1"><b className="block text-[15px]">Dừng khẩn cấp</b><span className="text-[13px] text-ink-2">{paused ? 'AI đang dừng ở mọi sandbox. Nhân viên vẫn trả lời bình thường.' : 'Dừng AI ngay ở mọi sandbox. Tin đang chờ gửi bị huỷ; nhân viên vẫn trả lời bình thường.'}</span></span>
        <Button variant={paused ? 'primary' : 'dangerSolid'} busy={kill.isPending} onClick={() => kill.mutate(!paused, { onSuccess: () => q.refetch() })}>{paused ? 'Cho AI chạy lại' : 'Dừng AI'}</Button>
        {kill.isError && <p role="alert" className="w-full text-[13px] text-bad">{explain(kill.error)}</p>}
      </Card>
      {q.data.sandboxes.length === 0 ? <Notice tone="warn">Chưa có sandbox «Chăm sóc khách». Tạo ở trang Sandbox.</Notice> : q.data.sandboxes.map((sb) => <SandboxCard key={sb.id} sb={sb} />)}
    </div>
  )
}
