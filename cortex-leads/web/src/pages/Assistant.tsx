import clsx from 'clsx'
import { Bot, Lock, Send } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { explain } from '../api/client'
import { useChat, useProposalVerb, useProposals, useSession } from '../api/hooks'
import type { ChatTurn, Proposal } from '../api/types'
import { Badge, Button, Empty, ErrorBox, Loading, Notice, SidePanel } from '../components/ui'
import { skillTitle } from '../components/skillName'
import { Role } from '../api/enums'

const SUGGESTIONS = ['Kỹ năng nào bị chặn nhiều nhất?', 'Có bao nhiêu khách đang bị bỏ rơi?', 'Nhân viên bỏ bao nhiêu nháp?', 'Kỹ năng nào nên tắt?']
type Line = ChatTurn & { refused?: boolean; verified?: boolean }

function Card({ p }: { p: Proposal }) {
  const verb = useProposalVerb()
  return (
    <article className="flex flex-col gap-2.5 rounded-[10px] border border-line p-3.5">
      <Badge tone={p.kind === 'tune_skill' ? 'ai' : 'bad'} className="self-start">{p.kind === 'tune_skill' ? 'Thẻ chiến lược' : 'Cần chú ý'}</Badge>
      <b className="text-sm">{p.signal}{p.skill ? ` · ${skillTitle(p.skill)}` : ''}</b>
      <p className="text-xs leading-snug text-ink-2">{p.evidence.join(' · ')}</p>
      {p.change && <div className="rounded-lg bg-app p-2.5"><span className="block text-[10px] font-semibold tracking-wider text-ink-3 uppercase">Thay đổi đề xuất</span>
        <b className="text-[13px]">{p.change.field}: {String(p.change.from)} → {String(p.change.to)}</b></div>}
      {p.change && <p className="text-xs text-ink-3">Chỉ tạo bản thử; bản đang chạy giữ nguyên cho tới khi bạn bật.</p>}
      {verb.isError && <Notice tone="bad">{explain(verb.error)}</Notice>}
      <div className="flex gap-2">
        <Button variant={p.danger ? 'dangerSolid' : 'primary'} busy={verb.isPending} onClick={() => verb.mutate({ id: p.id, verb: 'accept' })}>{p.action}</Button>
        <Button busy={verb.isPending} onClick={() => verb.mutate({ id: p.id, verb: 'dismiss' })}>Bỏ qua</Button>
      </div>
    </article>
  )
}

export function Assistant() {
  const { data: me } = useSession()
  const owner = me?.role === Role.OWNER
  const proposals = useProposals(!!owner)
  const chat = useChat()
  const [lines, setLines] = useState<Line[]>([])
  const [panel, setPanel] = useState(false)
  const [text, setText] = useState('')
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { end.current?.scrollIntoView?.({ block: 'end' }) }, [lines.length, chat.isPending])
  if (me && !owner) return <Navigate to="/inbox" replace />

  const ask = (q: string) => {
    const question = q.trim()
    if (!question || chat.isPending) return
    const history: Line[] = [...lines, { role: 'user', content: question }]
    setLines(history)
    setText('')
    chat.mutate(history.slice(-8).map(({ role, content }) => ({ role, content })), {
      onSuccess: (r) => setLines((l) => [...l, { role: 'assistant', content: r.reply, refused: r.refused, verified: r.verified }]),
    })
  }

  return (
    <div className="flex h-full">
      <section aria-label="Trò chuyện với AI tổng" className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-line bg-surface px-4 py-3 sm:px-7 sm:py-4">
          <span className="flex size-10 items-center justify-center rounded-full bg-ai-soft text-ai" aria-hidden><Bot className="size-5" /></span>
          <div className="min-w-0 flex-1 basis-40"><h1 className="text-lg font-bold">AI tổng</h1><p className="text-xs text-ink-2">Giám sát mọi việc của AI · chỉ đề xuất, người quyết định</p></div>
          <Badge tone="ai" className="max-sm:whitespace-normal"><Lock className="mr-1 size-3 shrink-0" aria-hidden />Chỉ đọc số liệu · không đọc nội dung tin nhắn</Badge>
          <Button className="xl:hidden" onClick={() => setPanel(true)}>Đề xuất{!!proposals.data?.items.length && <Badge tone="solid">{proposals.data.items.length}</Badge>}</Button>
        </header>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 py-4 sm:px-7 sm:py-6">
          {lines.length === 0 && <Empty>Hỏi AI tổng về số liệu, kỹ năng hoặc việc của AI. Ví dụ: “Kỹ năng nào bị chặn nhiều nhất?”</Empty>}
          {lines.map((l, i) => l.role === 'user'
            ? <div key={i} className="flex justify-end"><p className="max-w-[85%] rounded-xl bg-accent [overflow-wrap:anywhere] sm:max-w-[60%] px-3.5 py-2.5 text-sm text-white">{l.content}</p></div>
            : (
              <div key={i} className="flex items-start gap-2.5">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-ai-soft text-ai" aria-hidden><Bot className="size-3.5" /></span>
                <div className={clsx('flex max-w-[85%] min-w-0 flex-col gap-2 rounded-xl sm:max-w-[70%] border px-3.5 py-3 text-sm leading-relaxed', l.refused ? 'border-warn-soft bg-warn-soft text-warn' : 'border-line bg-surface')}>
                  <p>{l.refused && <Lock className="mr-1.5 inline size-3.5" aria-hidden />}{l.content}</p>
                  {l.refused && <Link to="/inbox"><Button>Mở trong Hộp thư</Button></Link>}
                  {l.verified === false && <p className="text-xs text-ink-3">Câu này chưa có số liệu để kiểm chứng.</p>}
                </div>
              </div>))}
          {chat.isPending && <Loading label="AI tổng đang xem số liệu…" />}
          {chat.isError && <Notice tone="bad">{explain(chat.error)}</Notice>}
          <div ref={end} />
        </div>
        <div className="flex flex-col gap-2.5 border-t border-line bg-surface px-4 pt-3 pb-4 sm:px-7">
          <div className="flex gap-2 max-sm:overflow-x-auto max-sm:[scrollbar-width:none] sm:flex-wrap">{SUGGESTIONS.map((s) => <button key={s} onClick={() => ask(s)} disabled={chat.isPending} className="shrink-0 rounded-full border border-line px-3 py-1.5 text-xs font-medium whitespace-nowrap text-ink-2 hover:bg-app disabled:opacity-50 sm:whitespace-normal">{s}</button>)}</div>
          <form onSubmit={(e) => { e.preventDefault(); ask(text) }} className="flex items-center gap-2.5 rounded-[10px] border border-line px-3.5 py-2.5">
            <input aria-label="Hỏi AI tổng" value={text} maxLength={600} onChange={(e) => setText(e.target.value)} placeholder="Hỏi AI tổng về số liệu, kỹ năng, việc của AI…" className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
            <button aria-label="Gửi" type="submit" disabled={!text.trim() || chat.isPending} className="text-accent disabled:text-ink-3"><Send className="size-[18px]" /></button>
          </form>
        </div>
      </section>
      <SidePanel label="Đề xuất đang chờ" open={panel} onClose={() => setPanel(false)} className="xl:w-95 xl:shrink-0 xl:overflow-y-auto xl:border-l xl:border-line">
        <div className="flex flex-col gap-4 p-5 max-xl:pt-0">
        <div className="flex items-center justify-between"><h2 className="text-base font-bold">Đề xuất đang chờ</h2>{!!proposals.data?.items.length && <Badge tone="solid">{proposals.data.items.length}</Badge>}</div>
        {proposals.isPending ? <Loading /> : proposals.isError ? <ErrorBox onRetry={() => proposals.refetch()} /> : proposals.data.items.length === 0
          ? <Empty>Không có đề xuất nào đang chờ.</Empty> : proposals.data.items.map((p) => <Card key={p.id} p={p} />)}
        </div>
      </SidePanel>
    </div>
  )
}
