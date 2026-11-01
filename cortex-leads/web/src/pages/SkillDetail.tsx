import { ArchiveRestore, History, Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { explain } from '../api/client'
import { useRevertSkill, useSession, useSkill, useSkillVerb } from '../api/hooks'
import type { SkillDetail as Detail, SkillStatus } from '../api/types'
import { Time } from '../components/Time'
import { Badge, Button, Card, ErrorBox, Label, Loading, Notice, PageHeader, Tabs, type Tone } from '../components/ui'

const STATUS: Record<SkillStatus, [string, Tone]> = { live: ['Đang bật', 'ok'], shadow: ['Đang chạy thử', 'warn'], draft: ['Bản nháp', 'neutral'], retired: ['Đã tắt', 'neutral'] }
const FIELD: Record<string, string> = {
  template: 'Mẫu', description: 'Mô tả', instructions: 'Cách làm', after_hours: 'Hỏi lại sau (giờ)', intent: 'Ý định khách', max_touches: 'Nhắn tối đa',
  never_say: 'Cụm cấm thêm', must_handoff: 'Chuyển người thêm', examples: 'Ví dụ',
}
const show = (v: unknown) => (v == null || v === '' ? '–' : Array.isArray(v) ? (v.length ? v.join(', ') : '–') : String(v))
type Tab = 'content' | 'history' | 'trial'

function Facts({ d }: { d: Detail }) {
  const f = d.form
  const rows: [string, string][] = [['Kích hoạt', d.trigger], ['Nhắn tối đa', `${f?.max_touches ?? '–'} lần mỗi khách`],
    ['Cách nhau tối thiểu', String(d.limits.min_gap ?? '–').replace('h', ' giờ')], ['Hết hạn sau', String(d.limits.expires_after ?? '–').replace('d', ' ngày')]]
  return (
    <>
      <Card className="flex flex-col gap-2 p-5"><Label>Cách làm của doanh nghiệp</Label>
        <p className="rounded-lg bg-app p-3 text-[13px] leading-relaxed">{f?.instructions ?? 'Kỹ năng hệ thống: nội dung do hệ thống quản lý, không sửa ở đây.'}</p>
        {f && <p className="text-xs text-ink-3">Đúng như bạn đã viết, lưu nguyên văn.</p>}</Card>
      <Card className="flex flex-col gap-3 p-5"><Label>Khi nào chạy và giới hạn</Label>
        <dl className="grid grid-cols-2 gap-3 text-[13px]">{rows.map(([k, v]) => <div key={k}><dt className="text-[11px] text-ink-3">{k}</dt><dd className="font-medium">{v}</dd></div>)}</dl></Card>
      <Card className="flex flex-col gap-3 p-5"><Label>Cụm cấm và việc chuyển cho người</Label>
        <p className="text-[13px] text-ink-2">{d.never_say_count} cụm cấm · {d.must_handoff.length} việc chuyển người</p>
        {f && f.never_say.length > 0 && <div><p className="mb-1.5 text-[11px] font-semibold text-ink-3">CỤM CẤM THÊM CỦA BẠN</p><div className="flex flex-wrap gap-1.5">{f.never_say.map((x) => <Badge key={x} tone="bad">{x}</Badge>)}</div></div>}
        <div><p className="mb-1.5 text-[11px] font-semibold text-ink-3">CHUYỂN CHO NGƯỜI</p><div className="flex flex-wrap gap-1.5">{d.must_handoff.map((x) => <Badge key={x}>{x}</Badge>)}</div></div></Card>
    </>
  )
}

function Trial({ d }: { d: Detail }) {
  return (
    <Card className="flex flex-col gap-3 p-5"><Label>Nháp thử gần nhất</Label>
      {d.trial_drafts.length === 0 ? <p className="text-[13px] text-ink-3">Chưa có nháp thử. Kỹ năng cần chạy thử trên tin thật trước khi bật.</p> : d.trial_drafts.map((t, i) => (
        <div key={i} className="flex flex-col gap-1.5 rounded-lg bg-app p-3">{t.asked && <p className="text-xs text-ink-2">Khách: “{t.asked}”</p>}<p className="text-[13px]">{t.text}</p>{t.blocked && <Badge tone="bad">Bị bộ kiểm chặn</Badge>}</div>))}
    </Card>
  )
}

function Changes({ h }: { h: Detail['history'][number] }) {
  return <ul className="mt-1 flex flex-col gap-0.5 text-xs text-ink-2">{h.changes.map((c) => <li key={c.field}>{FIELD[c.field.split('.')[0]] ?? c.field}: <s className="text-ink-3">{show(c.before)}</s> → <b className="text-ink">{show(c.after)}</b></li>)}</ul>
}

function HistoryList({ d, owner }: { d: Detail; owner: boolean }) {
  const revert = useRevertSkill(d.id)
  const [ask, setAsk] = useState<string | null>(null)
  return (
    <Card className="flex flex-col gap-3 p-5"><Label>Lịch sử chỉnh sửa</Label>
      {!owner ? <p className="text-[13px] text-ink-3">Chỉ chủ xem được lịch sử chỉnh sửa.</p> : d.history.length === 0 ? <p className="text-[13px] text-ink-3">Chưa có lần sửa nào.</p> : d.history.map((h) => (
        <div key={h.id} className="flex flex-col gap-1 border-t border-line pt-3 first:border-0 first:pt-0">
          <div className="flex items-center gap-2 text-xs text-ink-3"><Time iso={h.at} as="dateTime" /><span>· {h.actor}</span></div>
          <p className="text-[13px] font-medium">{h.summary}</p>
          {h.changes.length > 0 && <Changes h={h} />}
          {h.restorable && (ask === h.id
            ? <div className="flex items-center gap-2 text-xs"><span>Đưa nội dung về như trước lần sửa này?</span>
              <Button variant="primary" busy={revert.isPending} onClick={() => revert.mutate(h.id, { onSettled: () => setAsk(null) })}>Khôi phục</Button><Button onClick={() => setAsk(null)}>Không</Button></div>
            : <button className="self-start text-xs font-semibold text-accent" onClick={() => setAsk(h.id)}>Khôi phục</button>)}
        </div>))}
      {revert.isError && <Notice tone="bad">{explain(revert.error)}</Notice>}
      <p className="text-xs text-ink-3">Mỗi lần sửa được lưu lại, không tạo phiên bản mới. Khôi phục đưa nội dung về lúc đó và cũng được ghi vào lịch sử.</p>
    </Card>
  )
}

export function SkillDetail() {
  const { id } = useParams()
  const { data: me } = useSession()
  const q = useSkill(id)
  const verb = useSkillVerb()
  const [tab, setTab] = useState<Tab>('content')
  const [confirm, setConfirm] = useState(false)
  if (q.isPending) return <Loading />
  if (q.isError) return <div className="p-8"><ErrorBox onRetry={() => q.refetch()}>Không mở được kỹ năng này.</ErrorBox></div>
  const d = q.data
  const owner = me?.role === 'owner'
  const [label, tone] = STATUS[d.status]
  const go = (v: 'trial' | 'live' | 'off' | 'again' | 'delete' | 'restore') => verb.mutate({ id: d.id, verb: v })
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-8">
      <p className="text-[13px] text-ink-2"><Link to="/skills" className="hover:underline">Kỹ năng</Link> / <b className="text-ink">{d.name}</b></p>
      <PageHeader title={d.name} subtitle={d.description}
        action={<div className="flex items-center gap-2">
          {d.can.edit && <Link to={`/skills/${d.id}/edit`}><Button><Pencil className="size-4" aria-hidden />Sửa</Button></Link>}
          {owner && d.can.off && <Button busy={verb.isPending} onClick={() => go('off')}>Tắt kỹ năng</Button>}
          {owner && d.can.trial && <Button variant="primary" busy={verb.isPending} onClick={() => go('trial')}>Chạy thử</Button>}
          {owner && d.status === 'shadow' && <Button variant="primary" disabled={!d.can.live} busy={verb.isPending} onClick={() => go('live')}>{d.can.live ? 'Bật' : `Bật (cần đủ ${d.min_trial_runs} lượt)`}</Button>}
          {owner && d.can.again && <Button busy={verb.isPending} onClick={() => go('again')}>Bật lại</Button>}
        </div>} />
      <div className="-mt-3 flex items-center gap-2"><Badge tone={d.deleted ? 'bad' : tone}>{d.deleted ? 'Đã xoá' : `${label} · bản ${d.version}`}</Badge>
        {d.source === 'card' && <Badge tone="ai">Từ thẻ chiến lược</Badge>}<span className="text-xs text-ink-3">Tạo <Time iso={d.created_at} as="when" /></span></div>
      {d.deleted && (
        <Notice tone="bad" action={owner && <Button busy={verb.isPending} onClick={() => go('restore')}><ArchiveRestore className="size-4" aria-hidden />Khôi phục</Button>}>
          Kỹ năng đã bị xoá{d.deleted_by ? ` bởi ${d.deleted_by}` : ''}{d.deleted_at && <> lúc <Time iso={d.deleted_at} as="dateTime" /></>}{'. '}Nội dung và lịch sử vẫn còn.</Notice>)}
      {verb.isError && <Notice tone="bad">{explain(verb.error)}</Notice>}
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'content', label: 'Nội dung' }, { id: 'history', label: 'Lịch sử chỉnh sửa', count: d.history.length }, { id: 'trial', label: 'Nháp thử', count: d.trial_drafts.length }]} />
      <div className="flex min-h-0 gap-5">
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          {tab === 'content' && <Facts d={d} />}{tab === 'history' && <HistoryList d={d} owner={!!owner} />}{tab === 'trial' && <Trial d={d} />}
        </div>
        <div className="flex w-90 shrink-0 flex-col gap-4">
          <Card className="flex flex-col gap-3 p-5"><Label>Liên kết</Label>
            <div><p className="text-[11px] text-ink-3">CHẠY TRONG SANDBOX</p><Link to="/sandboxes" className="text-[13px] font-semibold text-accent">{d.sandbox}</Link></div>
            <div><p className="text-[11px] text-ink-3">CÔNG CỤ DÙNG</p>{d.tools.map((t) => <p key={t} className="text-[13px]">✓ {t}</p>)}
              <Link to="/tools" className="text-xs font-semibold text-accent">Xem ma trận quyền</Link></div></Card>
          {owner && d.history.length > 0 && tab !== 'history' && <Card className="flex flex-col gap-2 p-5"><Label>Lần sửa gần nhất</Label><div className="flex items-center gap-2 text-xs text-ink-3"><History className="size-3.5" aria-hidden /><Time iso={d.history[0].at} as="dateTime" /> · {d.history[0].actor}</div><p className="text-[13px]">{d.history[0].summary}</p></Card>}
          {owner && d.can.delete && (
            <Card className="flex flex-col gap-2 border-bad p-5">
              <h2 className="text-[13px] font-bold text-bad">Xoá (khoá) kỹ năng</h2>
              <p className="text-xs text-ink-2">Xoá chỉ khoá và ẩn kỹ năng: ngừng chạy ngay, nội dung và lịch sử vẫn giữ nguyên, bạn khôi phục được bất cứ lúc nào ở tab Đã xoá.</p>
              {confirm ? <div className="flex gap-2"><Button variant="dangerSolid" busy={verb.isPending} className="flex-1" onClick={() => { go('delete'); setConfirm(false) }}>Xoá kỹ năng</Button><Button className="flex-1" onClick={() => setConfirm(false)}>Không</Button></div>
                : <Button variant="danger" onClick={() => setConfirm(true)}><Trash2 className="size-4" aria-hidden />Xoá (khoá) kỹ năng</Button>}
            </Card>)}
        </div>
      </div>
    </div>
  )
}
