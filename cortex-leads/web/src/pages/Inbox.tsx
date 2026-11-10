import clsx from 'clsx'
import { ArrowLeft, CalendarPlus, Search, Send, Sparkles, UserRound } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { explain, post } from '../api/client'
import { useConversation, useConversations, useInboxAction, useSession } from '../api/hooks'
import type { ConvFilter, ConvItem, Conversation, Draft } from '../api/types'
import { ago, dateTime, dayMonth } from '../components/format'
import { can } from '../components/can'
import { Time } from '../components/Time'
import { CustomerData } from './CustomerData'
import { Avatar, Badge, Button, Empty, ErrorBox, Label, Loading, Menu, Notice, SidePanel, Tabs, type Tone } from '../components/ui'
import { skillTitle } from '../components/skillName'
import { Perm } from '../api/enums'

const BADGES: Record<string, [string, Tone]> = {
  need_human: ['Cần người', 'bad'], waiting: ['Khách đang chờ', 'warn'], silent: ['Khách im', 'neutral'], booked: ['Đã đặt lịch', 'ok'],
}
function badgeOf(code: string): [string, Tone] {
  if (code.startsWith('promised:')) return [`Hẹn ${dayMonth(code.slice(9))}`, 'accent']
  return BADGES[code] ?? [code, 'neutral']
}

function ConversationList({ filter, setFilter, activeId, onOpen }: { filter: ConvFilter; setFilter: (f: ConvFilter) => void; activeId?: string; onOpen: (id: string) => void }) {
  const q = useConversations(filter)
  const c = q.data?.counts
  return (
    <section aria-label="Danh sách hội thoại" className={clsx('flex w-full shrink-0 flex-col border-line bg-surface md:w-85 md:border-r', activeId && 'max-md:hidden')}>
      <div className="flex flex-col gap-3 px-4 pt-4">
        <div className="flex items-center justify-between"><h1 className="text-xl font-bold">Hộp thư</h1><Search className="size-[18px] text-ink-2" aria-hidden /></div>
        <Tabs tight value={filter} onChange={setFilter} tabs={[
          { id: 'need_human', label: 'Cần người', count: c?.need_human }, { id: 'waiting', label: 'Đang chờ', count: c?.waiting },
          { id: 'silent', label: 'Khách im', count: c?.silent }, { id: 'all', label: 'Tất cả' }]} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {q.isPending ? <Loading /> : q.isError ? <ErrorBox onRetry={() => q.refetch()} /> : q.data.items.length === 0 ? (
          <Empty>{filter === 'need_human' ? 'Không có khách nào cần người. Tốt lắm.' : 'Không có hội thoại nào ở mục này.'}</Empty>
        ) : q.data.items.map((it) => <Row key={it.id} it={it} active={it.id === activeId} onOpen={onOpen} />)}
      </div>
    </section>
  )
}

function Row({ it, active, onOpen }: { it: ConvItem; active: boolean; onOpen: (id: string) => void }) {
  return (
    <button onClick={() => onOpen(it.id)} aria-current={active} className={clsx('flex w-full gap-3 border-b border-line px-4 py-3.5 text-left', active ? 'bg-accent-soft' : 'hover:bg-app')}>
      <Avatar name={it.name} active={active} />
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="flex justify-between gap-2"><b className="truncate text-sm">{it.name}</b><Time iso={it.at} as="when" className="shrink-0 text-xs text-ink-3" /></span>
        <span className="line-clamp-2 text-[13px] text-ink-2">{it.snippet}</span>
        {it.badges.length > 0 && <span className="flex flex-wrap gap-1">{it.badges.map((b) => { const [l, t] = badgeOf(b); return <Badge key={b} tone={t}>{l}</Badge> })}</span>}
      </span>
    </button>
  )
}

function DraftCard({ d, conv }: { d: Draft; conv: Conversation }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(d.text)
  const act = useInboxAction((v: { action: string; edited_text?: string }) => post(`/drafts/${d.id}/action`, v))
  const offchannel = d.route === 'offchannel'
  const canSend = conv.window.open && !offchannel && !d.needs_human
  const run = (action: string, edited?: string) => act.mutate({ action, edited_text: edited })
  return (
    <article aria-label="Nháp của AI" className="flex flex-col gap-3 rounded-xl border border-ai bg-ai-soft p-4">
      <div className="flex flex-wrap items-center gap-2 text-[13px] font-semibold text-ai">
        <Sparkles className="size-4 shrink-0" aria-hidden /><span className="min-w-0 flex-1 basis-44">{d.needs_human ? 'AI chuyển cho bạn · gợi ý' : 'Nháp AI · chờ nhân viên duyệt'}</span>
        {d.turn && <Badge tone="warn">Khách đang chờ</Badge>}{d.reason && <Badge tone="ai" className="bg-white">{d.reason}</Badge>}
      </div>
      {editing ? <textarea aria-label="Sửa nháp" value={text} onChange={(e) => setText(e.target.value)} rows={4} className="w-full rounded-lg border border-line bg-white p-2.5 text-sm" />
        : <p className="text-sm leading-relaxed whitespace-pre-wrap">{d.text}</p>}
      {d.claims.length > 0 && <div className="flex flex-wrap items-center gap-1.5 text-xs text-ink-2">Nguồn catalog:{d.claims.map((c, i) => <Badge key={i} tone="ai" className="bg-white">{c.source_id} · {String(c.value)}</Badge>)}</div>}
      {offchannel && <Notice tone="warn">Cửa sổ nhắn đã đóng: nội dung này là gợi ý để bạn gọi điện hoặc nhắn Zalo, không gửi qua kênh được.</Notice>}
      {d.needs_human && <Notice tone="bad">Hệ thống không tự gửi nháp này. Bạn quyết định và tự liên hệ khách.</Notice>}
      {act.isError && <Notice tone="bad">{explain(act.error)}</Notice>}
      {/* the one or two things done every time are buttons; the rarer answers wait in "⋯" */}
      <div className="flex flex-wrap items-center gap-2">
        {canSend ? <>
          <Button variant="primary" busy={act.isPending} onClick={() => run('approved', editing ? text : undefined)}>Duyệt &amp; gửi</Button>
          <Button onClick={() => setEditing((v) => !v)}>{editing ? 'Dùng nháp gốc' : 'Sửa nháp'}</Button>
        </> : <Button variant="primary" busy={act.isPending} onClick={() => run('sent')}>{offchannel ? 'Đã liên hệ' : 'Tôi đã gửi tay'}</Button>}
        <Menu label="Cách xử lý khác" items={[
          ...(canSend ? [{ label: 'Tôi đã gửi tay', onClick: () => run('sent') }] : []),
          { label: 'Tôi tự làm', onClick: () => run('self') }, { label: 'Bỏ nháp này', onClick: () => run('skipped') }]} />
      </div>
    </article>
  )
}

function Composer({ conv }: { conv: Conversation }) {
  const [text, setText] = useState('')
  const send = useInboxAction((t: string) => post(`/conversations/${conv.id}/reply`, { text: t }))
  const submit = () => { const t = text.trim(); if (t) send.mutate(t, { onSuccess: () => setText('') }) }
  const w = conv.window
  return (
    <div className="flex flex-col gap-2 border-t border-line bg-surface px-3 pt-3 pb-4 sm:px-6">
      {send.isError && <Notice tone="bad">{explain(send.error)}</Notice>}
      <div className="flex items-center gap-2.5 rounded-[10px] border border-line px-3.5 py-2.5">
        <textarea aria-label="Nhập tin nhắn trả lời khách" rows={1} value={text} disabled={!w.open} placeholder={w.open ? 'Nhập tin nhắn trả lời khách…' : 'Cửa sổ nhắn đã đóng'}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
          className="max-h-28 min-h-6 min-w-0 flex-1 resize-none bg-transparent text-sm outline-none disabled:text-ink-3" />
        <button aria-label="Gửi" onClick={submit} disabled={!w.open || !text.trim() || send.isPending} className="shrink-0 text-accent disabled:text-ink-3 max-lg:p-1.5"><Send className="size-[18px]" /></button>
      </div>
      <p className="text-xs text-ink-3">{w.open
        ? `${w.basis === 'human_agent' ? 'Quá cửa sổ tự do: chỉ người gõ tay được gửi' : 'Cửa sổ nhắn tự do'}${w.expires_at ? ` · mở đến ${dateTime(w.expires_at)}` : ''} · tin gửi tay không kèm dòng xưng AI`
        : 'Hãy gọi điện hoặc nhắn Zalo cho khách.'}</p>
    </div>
  )
}

function Center({ conv, onProfile }: { conv: Conversation; onProfile: () => void }) {
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { end.current?.scrollIntoView?.({ block: 'end' }) }, [conv.id, conv.messages.length, conv.drafts.length])
  const last = [...conv.messages].reverse().find((m) => m.role === 'customer')
  const waiting = conv.messages.at(-1)?.role === 'customer'
  return (
    <section aria-label="Hội thoại" className="flex min-w-0 flex-1 flex-col bg-app">
      <header className="flex items-center gap-3 border-b border-line bg-surface px-3 py-3 sm:px-6 sm:py-3.5">
        <Link to="/inbox" aria-label="Về danh sách hội thoại" className="grid size-10 shrink-0 place-items-center rounded-lg text-ink-2 hover:bg-app md:hidden"><ArrowLeft className="size-5" aria-hidden /></Link>
        <Avatar name={conv.name} active />
        <div className="min-w-0 flex-1"><h2 className="truncate text-base font-bold">{conv.name}</h2>
          <p className="flex items-center gap-2 text-xs text-ink-2">{conv.channel === 'messenger' ? 'Messenger' : conv.channel}{waiting && last && <Badge tone="warn">Chờ {ago(last.at)}</Badge>}</p></div>
        <Button className="shrink-0 xl:hidden" onClick={onProfile}><UserRound className="size-4" aria-hidden /><span className="max-sm:sr-only">Hồ sơ</span></Button>
      </header>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3 sm:p-6">
        {conv.messages.map((m) => (
          <div key={m.id} className={clsx('flex gap-2', m.role === 'customer' ? 'items-end' : 'flex-row-reverse items-end')}>
            {m.role === 'customer' && <Avatar name={conv.name} size={28} />}
            <div className={clsx('max-w-[85%] min-w-0 rounded-xl border px-3.5 py-2.5 [overflow-wrap:anywhere] sm:max-w-[70%]', m.role === 'customer' ? 'border-line bg-surface' : 'border-accent-soft bg-accent-soft')}>
              <p className="text-sm whitespace-pre-wrap">{m.text}</p><p className="mt-1 text-[11px] text-ink-3">{m.role === 'bot' ? 'Hệ thống · ' : m.role === 'staff' ? 'Nhân viên · ' : ''}<Time iso={m.at} /></p>
            </div>
          </div>
        ))}
        {conv.drafts.map((d) => <DraftCard key={d.id} d={d} conv={conv} />)}
        <div ref={end} />
      </div>
      <Composer conv={conv} />
    </section>
  )
}

const OUTCOMES: [string, string][] = [['booked', 'Đã đặt lịch'], ['won', 'Đã chốt'], ['lost', 'Mất khách'], ['reopen', 'Mở lại']]

function Profile({ conv, open, onClose }: { conv: Conversation; open: boolean; onClose: () => void }) {
  const fact = useInboxAction(({ id, verb }: { id: string; verb: 'confirm' | 'reject' }) => post(`/facts/${id}/${verb}`))
  const book = useInboxAction((code: string) => post(`/conversations/${conv.id}/booking`, { slot_code: code }))
  const cancel = useInboxAction((id: string) => post(`/bookings/${id}/cancel`))
  const outcome = useInboxAction((status: string) => post(`/conversations/${conv.id}/outcome`, { status }))
  const err = book.error ?? cancel.error ?? outcome.error ?? fact.error
  const { data: me } = useSession()
  return (
    <SidePanel label="Hồ sơ khách" open={open} onClose={onClose} className="xl:w-80 xl:shrink-0 xl:overflow-y-auto xl:border-l xl:border-line">
      <div className="flex flex-col gap-5 p-5 max-xl:pt-0">
      <div className="flex flex-col gap-2.5"><Label>Khách</Label><b className="text-base">{conv.name}</b>
        {([['Ý định', conv.intent], ['Người quyết định', conv.decision_maker], ['Khách hẹn', conv.promised_date && dayMonth(conv.promised_date)], ['Phụ trách', conv.owner ?? 'Chưa gán']] as const).map(([k, v]) =>
          v ? <div key={k} className="flex justify-between text-[13px]"><span className="text-ink-2">{k}</span><span className="font-medium">{v}</span></div> : null)}
      </div>
      {err && <Notice tone="bad">{explain(err)}</Notice>}
      <div className="flex flex-col gap-2.5"><Label>AI đã ghi nhớ</Label>
        {conv.facts.length === 0 ? <p className="text-[13px] text-ink-3">Chưa có gì.</p> : conv.facts.map((f) => (
          <div key={f.id} className="flex flex-col gap-1 rounded-lg bg-app px-2.5 py-2">
            <div className="flex justify-between text-xs"><span className="text-ink-2">{f.kind}</span>{f.status === 'candidate' ? <Badge tone="warn">Cần xác nhận</Badge> : <span className="text-accent">{f.evidence ? `bằng chứng ×${f.evidence}` : 'nhân viên ghi'}</span>}</div>
            <span className="text-[13px] font-medium">{f.text}</span>
            {f.status === 'candidate' && <div className="flex gap-2 pt-1"><Button onClick={() => fact.mutate({ id: f.id, verb: 'confirm' })}>Xác nhận</Button><Button onClick={() => fact.mutate({ id: f.id, verb: 'reject' })}>Bác</Button></div>}
          </div>))}
      </div>
      <div className="flex flex-col gap-2.5"><Label>Lịch học thử</Label>
        {conv.bookings.map((b) => (
          <div key={b.id} className="flex items-center justify-between gap-2 rounded-[10px] border border-line p-3 text-[13px]">
            <span className="min-w-0"><b><Time iso={b.at} as="dateTime" /></b><br /><span className="text-xs text-ink-2">{b.slot}{b.by_ai ? ' · AI giữ chỗ' : ''}</span></span>
            <Button onClick={() => cancel.mutate(b.id)} busy={cancel.isPending}>Huỷ lịch</Button>
          </div>))}
        {conv.bookings.length === 0 && (conv.open_slots.length === 0 ? <p className="text-[13px] text-ink-3">Hiện không có buổi nào còn chỗ.</p> : (
          <div className="flex flex-col gap-2 rounded-[10px] border border-line p-3">
            <b className="text-[13px]">Chưa đặt lịch</b>
            {conv.open_slots.map((s) => (
              <div key={s.code} className="flex items-center justify-between gap-2 text-xs text-ink-2">
                <span>{s.ngay} {s.gio} · còn {s.con_cho} chỗ</span>
                <Button onClick={() => book.mutate(s.code)} busy={book.isPending}><CalendarPlus className="size-3.5" aria-hidden />Đặt</Button>
              </div>))}
          </div>))}
      </div>
      <div className="flex flex-col gap-2.5"><Label>Kết quả</Label>
        <div className="flex flex-wrap gap-2">{OUTCOMES.map(([k, l]) => <Button key={k} busy={outcome.isPending} onClick={() => outcome.mutate(k)}>{l}</Button>)}</div></div>
      <div className="flex flex-col gap-2.5"><Label>AI đã làm gì</Label>
        {conv.log.length === 0 ? <p className="text-[13px] text-ink-3">Chưa có gì.</p> : conv.log.map((l, i) => (
          <div key={i} className="flex gap-2.5 text-xs"><Time iso={l.at} className="text-ink-3" /><span className="text-ink-2">{l.label}{l.skill ? ` · ${skillTitle(l.skill)}` : ''}</span></div>))}
      </div>
      {can(me, Perm.SETTINGS_MANAGE) && <CustomerData conversationId={conv.id} />}
      </div>
    </SidePanel>
  )
}

function Detail({ id }: { id: string }) {
  const q = useConversation(id)
  const [profile, setProfile] = useState(false)
  if (q.isPending) return <div className="flex-1"><Loading /></div>
  if (q.isError) return <div className="flex-1"><ErrorBox onRetry={() => q.refetch()}>Không mở được hội thoại này.</ErrorBox></div>
  return <><Center conv={q.data} onProfile={() => setProfile(true)} /><Profile conv={q.data} open={profile} onClose={() => setProfile(false)} /></>
}

function Welcome({ counts, name, paused, settings }: { counts?: Record<ConvFilter, number>; name: string; paused: boolean; settings: boolean }) {
  const stat = (n: number | undefined, label: string, tone: string) => (
    <div className="flex flex-col gap-1 rounded-xl border border-line bg-surface px-5 py-4">
      <b className={clsx('text-2xl', tone)}>{n ?? '–'}</b><span className="text-[13px] text-ink-2">{label}</span>
    </div>
  )
  return (
    <div className="flex min-w-0 flex-1 flex-col items-center justify-center gap-6 overflow-y-auto p-8 max-md:hidden">
      <div className="text-center"><h2 className="text-xl font-bold">Chào {name}</h2>
        <p className="mt-1 max-w-md text-[13px] text-ink-2">{counts && counts.need_human + counts.waiting + counts.silent === 0
          ? 'Hiện không có khách nào đang chờ. Khi có khách nhắn hoặc AI cần bạn quyết, hội thoại sẽ hiện ở bên trái.'
          : 'Đây là tình hình hộp thư. Chọn một mục ở bên trái để bắt đầu.'}</p></div>
      <div className="flex flex-wrap justify-center gap-3">{stat(counts?.need_human, 'Cần bạn quyết', 'text-bad')}{stat(counts?.waiting, 'Khách đang chờ', 'text-warn')}{stat(counts?.silent, 'Khách im, chưa ai nhắn lại', 'text-ink')}</div>
      {paused && <Notice tone="bad">AI đang tạm dừng: khách nhắn sẽ không có nháp cho tới khi bạn bật lại.</Notice>}
      <div className="flex gap-4 text-[13px]"><Link to="/skills" className="text-accent hover:underline">Xem kỹ năng của AI</Link>{settings && <Link to="/settings?tab=ai" className="text-accent hover:underline">Cài đặt AI</Link>}</div>
    </div>
  )
}

export function Inbox() {
  const { id } = useParams()
  const nav = useNavigate()
  const { data: me } = useSession()
  const [filter, setFilter] = useState<ConvFilter>('need_human')
  const list = useConversations(filter)
  // Open the first customer of a list instead of an empty pane: on arrival with no conversation chosen, and when the tab
  // changes. A conversation reached by its own link is never replaced.
  const pick = useRef(!id)
  useEffect(() => {
    if (!pick.current || !list.data) return
    pick.current = false
    const first = list.data.items[0]
    // On a phone the list is the page: opening a customer here would hide it.
    if (first && !window.matchMedia?.('(max-width: 767.98px)').matches) nav(`/inbox/${first.id}`, { replace: true })
  }, [list.data, nav])
  const changeTab = (f: ConvFilter) => { pick.current = true; setFilter(f) }
  return (
    <div className="flex h-full">
      <ConversationList filter={filter} setFilter={changeTab} activeId={id} onOpen={(i) => nav(`/inbox/${i}`)} />
      {id ? <Detail key={id} id={id} /> : (
        <Welcome counts={list.data?.counts} name={me?.name.split(' ').slice(-1)[0] ?? 'bạn'} paused={me?.ai === 'paused'} settings={can(me, Perm.SETTINGS_MANAGE)} />)}
    </div>
  )
}
