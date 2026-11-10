import { Bot, OctagonAlert } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { explain } from '../api/client'
import { useAiOverview, useKillSwitch, useSendMode } from '../api/hooks'
import type { AiOverview } from '../api/types'
import { SCard, SHead, SRow } from '../components/settingsUi'
import { Badge, Button, ErrorBox, Loading, Notice } from '../components/ui'
import { skillTitle } from '../components/skillName'
import { AiJobs } from './Sandboxes'

type Box = AiOverview['sandboxes'][number]
const SHOWN = 6

/** A long list is cut to the first few with "+ N more", so one sandbox's banned phrases do not push everything else off the screen. */
function Chips({ items, tone, none }: { items: string[]; tone: 'bad' | 'warn'; none: string }) {
  const [all, setAll] = useState(false)
  if (items.length === 0) return <p className="text-xs text-ink-3">{none}</p>
  const shown = all ? items : items.slice(0, SHOWN)
  return (
    <p className="flex flex-wrap gap-1.5">
      {shown.map((x) => <Badge key={x} tone={tone}>{x}</Badge>)}
      {items.length > SHOWN && <button type="button" onClick={() => setAll(!all)} className="rounded-full bg-app px-2.5 py-[3px] text-xs font-medium text-ink-2 hover:text-ink">{all ? 'Thu gọn' : `+ ${items.length - SHOWN} cụm khác`}</button>}
    </p>
  )
}

function SandboxCard({ sb }: { sb: Box }) {
  const mode = useSendMode(sb.id)
  const [ask, setAsk] = useState(false)
  const auto = sb.send_mode === 'auto'
  return (
    <SCard>
      <SHead title={sb.title} right={<><Badge tone={sb.status === 'paused' ? 'bad' : 'ok'}>{sb.status === 'paused' ? 'Đang tạm dừng' : 'Đang chạy'}</Badge>
        <Link to={`/sandboxes/${sb.id}`} className="text-[13px] font-semibold text-accent hover:underline">Chi tiết →</Link></>} />
      <SRow label="Chế độ gửi tin" desc="Quyết định ai bấm gửi cho khách.">
        <div role="radiogroup" aria-label="Chế độ gửi tin" className="inline-flex w-fit gap-0.5 rounded-[10px] bg-app p-[3px]">
          <Button aria-pressed={!auto} variant={auto ? 'ghost' : 'segOn'} busy={mode.isPending} onClick={() => auto && mode.mutate('manual')}>Duyệt tay</Button>
          <Button aria-pressed={auto} variant={auto ? 'segOn' : 'ghost'} busy={mode.isPending} onClick={() => auto || setAsk(true)}>Tự gửi</Button>
        </div>
        {ask && (
          <div role="group" aria-label="Xác nhận bật tự gửi" className="flex flex-col gap-2 rounded-[10px] bg-warn-soft p-4">
            <p className="text-[13px] font-semibold text-warn">Bật tự gửi cho «{sb.title}»?</p>
            <p className="text-xs text-ink-2">Từ giờ, khi khách nhắn, các kỹ năng được phép tự gửi có thể trả lời khách ngay mà không ai duyệt. Bạn tắt lại bất cứ lúc nào ở đây, hoặc bấm Dừng khẩn cấp ở cuối trang.</p>
            <div className="flex gap-2"><Button variant="primary" busy={mode.isPending} onClick={() => mode.mutate('auto', { onSettled: () => setAsk(false) })}>Bật tự gửi</Button><Button onClick={() => setAsk(false)}>Không</Button></div>
          </div>)}
        <p className="text-[13px] text-ink-2">{auto
          ? 'Chỉ các kỹ năng được phép tự gửi mới gửi khi khách vừa nhắn, qua cùng bộ chặn như khi nhân viên bấm gửi (cửa sổ nhắn, khách từ chối, giờ làm việc). Kỹ năng khác vẫn chỉ soạn nháp.'
          : 'Mọi tin gửi cho khách đều chờ nhân viên bấm gửi. AI chỉ soạn nháp.'}</p>
        {mode.isError && <p role="alert" className="text-xs text-bad">{explain(mode.error)}</p>}
      </SRow>
      <SRow label={`Kỹ năng đang chạy (${sb.skills.length})`} desc={<>Quản lý ở trang <Link to="/skills" className="font-semibold text-accent hover:underline">Kỹ năng</Link>.</>}>
        {sb.skills.length === 0 ? <p className="text-xs text-ink-3">Chưa có kỹ năng nào chạy.</p> : sb.skills.map((k) => (
          <p key={k.name} className="flex flex-wrap items-center gap-2 text-[13px]"><b className="font-semibold">{skillTitle(k.name)}</b>
            <Badge tone={k.sends ? 'ai' : 'ok'}>{k.status === 'live' ? 'chạy thật' : 'chạy thử'}{k.sends ? ' · có thể tự gửi' : ''}</Badge></p>))}
      </SRow>
      <SRow label="Giới hạn của AI" desc="Chốt chặn do bạn cấu hình ở kỹ năng.">
        <div className="grid gap-5 sm:grid-cols-2">
          <div className="flex flex-col gap-2"><b className="text-[13px]">Cụm AI không bao giờ được nói</b><Chips items={sb.never_say} tone="bad" none="Chưa có." /></div>
          <div className="flex flex-col gap-2"><b className="text-[13px]">Việc luôn chuyển cho người</b><Chips items={sb.must_handoff} tone="warn" none="Chưa có." /></div>
        </div>
      </SRow>
    </SCard>
  )
}

export function SettingsAi() {
  const q = useAiOverview()
  const kill = useKillSwitch()
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const boxes = q.data.sandboxes
  const paused = boxes.length > 0 && boxes.every((s) => s.status === 'paused')
  return (
    <>
      <SCard>
        <div className="flex items-center gap-3.5 px-6 py-[18px]">
          <span className={`grid size-9 shrink-0 place-items-center rounded-full ${paused ? 'bg-bad-soft' : 'bg-ok-soft'}`}><span className={`size-2.5 rounded-full ${paused ? 'bg-bad' : 'bg-ok'}`} aria-hidden /></span>
          <div className="min-w-0"><b className={`block text-base ${paused ? 'text-bad' : 'text-ok'}`}>{paused ? 'AI đang tạm dừng' : 'AI đang chạy'}</b>
            <span className="text-[13px] text-ink-2">AI chỉ soạn nháp. Mọi con số phải trùng bảng giá, và mọi tin gửi đi đều qua cùng một đường kiểm.</span></div>
        </div>
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 bg-ai-soft px-6 py-3 text-[13px] text-ink-2"><Bot className="size-4 shrink-0 text-ai" aria-hidden />Khách luôn được báo đây là AI: <b className="font-semibold text-ai">{q.data.disclosure}</b>
          <span>· đổi tên ở <Link to="/settings?tab=business" className="font-semibold text-accent hover:underline">Doanh nghiệp</Link></span></p>
      </SCard>
      <SCard className={paused ? 'border-bad' : 'border-red-200'}>
        <div className="flex flex-wrap items-center gap-6 px-6 py-[18px]">
          <span className="min-w-0 flex-1 basis-64"><b className="flex items-center gap-2 text-[15px] text-bad"><OctagonAlert className="size-4" aria-hidden />Dừng khẩn cấp</b>
            <span className="mt-1 block text-[13px] text-ink-2">{paused ? 'AI đang dừng ở mọi việc. Nhân viên vẫn trả lời bình thường.' : 'Dừng AI ngay ở mọi việc. Tin đang chờ gửi bị huỷ; nhân viên vẫn trả lời bình thường.'}</span></span>
          <Button variant={paused ? 'primary' : 'dangerSolid'} busy={kill.isPending} onClick={() => kill.mutate(!paused, { onSuccess: () => q.refetch() })}>{paused ? 'Cho AI chạy lại' : 'Dừng AI'}</Button>
          {kill.isError && <p role="alert" className="w-full text-[13px] text-bad">{explain(kill.error)}</p>}
        </div>
      </SCard>
      {boxes.length === 0 ? <Notice tone="warn">Thiếu việc «Chăm sóc khách» của AI. Nhờ người hỗ trợ kỹ thuật thêm.</Notice> : boxes.map((sb) => <SandboxCard key={sb.id} sb={sb} />)}
      <AiJobs />
    </>
  )
}
