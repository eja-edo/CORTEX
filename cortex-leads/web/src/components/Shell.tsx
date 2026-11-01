import clsx from 'clsx'
import { Bot, Boxes, ChartColumn, Database, GraduationCap, Inbox, ListChecks, LogOut, Settings, Sparkles, Brain, ScrollText, UserCog, Wrench } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useKillSwitch, useLogout } from '../api/hooks'
import type { Me } from '../api/types'
import { can } from './can'
import { Badge, Button } from './ui'

const MODE: Record<Me['mode'], string> = { manual: 'Chế độ nháp · nhân viên duyệt', auto: 'Tự gửi khi đủ điều kiện', mixed: 'Mỗi sandbox một chế độ' }

function Item({ to, icon, children, badge }: { to: string; icon: ReactNode; children: ReactNode; badge?: number }) {
  return (
    <NavLink to={to} className={({ isActive }) => clsx('flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm', isActive ? 'bg-accent-soft font-semibold text-accent' : 'font-medium text-ink-2 hover:bg-app')}>
      {icon}<span className="flex-1">{children}</span>{!!badge && <Badge tone="solid">{badge}</Badge>}
    </NavLink>
  )
}
const Soon = ({ icon, children }: { icon: ReactNode; children: ReactNode }) =>
  <span aria-disabled title="Sắp có" className="flex cursor-not-allowed items-center gap-2.5 px-2.5 py-2 text-sm font-medium text-ink-3">{icon}{children}</span>

/** The kill switch: one deliberate confirmation, then every sandbox stops. Owner only; staff only see the state. */
function AiStatus({ me }: { me: Me }) {
  const kill = useKillSwitch()
  const [confirm, setConfirm] = useState(false)
  const paused = me.ai === 'paused'
  if (me.ai === 'none') return <div className="rounded-[10px] bg-app p-3 text-xs text-ink-2">Chưa có sandbox chăm sóc khách.</div>
  return (
    <div className={clsx('flex flex-col gap-2.5 rounded-[10px] p-3', paused ? 'bg-bad-soft' : 'bg-ok-soft')}>
      <div className={clsx('flex items-center gap-2 text-[13px] font-semibold', paused ? 'text-bad' : 'text-ok')}>
        <span className={clsx('size-2 rounded-full', paused ? 'bg-bad' : 'bg-ok')} aria-hidden />{paused ? 'AI đang tạm dừng' : 'AI đang chạy'}
      </div>
      <p className="text-xs text-ink-2">{paused ? 'Nhân viên vẫn trả lời bình thường.' : MODE[me.mode]}</p>
      {me.role === 'owner' && (confirm ? (
        <div className="flex flex-col gap-2" role="group" aria-label="Xác nhận dừng khẩn cấp">
          <p className="text-xs font-semibold text-bad">Dừng toàn bộ AI của doanh nghiệp?</p>
          <div className="flex gap-2">
            <Button variant="dangerSolid" busy={kill.isPending} className="flex-1" onClick={() => kill.mutate(true, { onSettled: () => setConfirm(false) })}>Dừng ngay</Button>
            <Button className="flex-1" onClick={() => setConfirm(false)}>Huỷ</Button>
          </div>
        </div>
      ) : paused ? (
        <Button variant="primary" busy={kill.isPending} onClick={() => kill.mutate(false)}>Bật lại AI</Button>
      ) : (
        <Button variant="danger" onClick={() => setConfirm(true)}>Dừng khẩn cấp</Button>
      ))}
      {kill.isError && <p role="alert" className="text-xs text-bad">Không thực hiện được.</p>}
    </div>
  )
}

export function Shell({ me }: { me: Me }) {
  const logout = useLogout()
  return (
    <div className="flex h-full overflow-hidden">
      <aside className="flex h-full min-h-0 w-58 shrink-0 flex-col gap-3 overflow-hidden border-r border-line bg-surface p-4">
        <nav aria-label="Điều hướng chính" className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
          <div className="flex items-center gap-2.5 px-2 pb-4">
            <span className="flex size-8 items-center justify-center rounded-lg bg-accent text-white" aria-hidden><Brain className="size-[18px]" /></span>
            <div className="min-w-0"><div className="text-base font-bold">Cortex</div><div className="truncate text-[11px] text-ink-3">{me.tenant}</div></div>
          </div>
          <Item to="/inbox" icon={<Inbox className="size-[18px]" />} badge={me.needs_person}>Hộp thư</Item>
          <Soon icon={<ListChecks className="size-[18px]" />}>Việc hôm nay</Soon>
          {can(me, 'lessons.read') && <Item to="/classes" icon={<GraduationCap className="size-[18px]" />}>Lớp học</Item>}
          <Item to="/skills" icon={<Sparkles className="size-[18px]" />}>Kỹ năng</Item>
          <Item to="/sandboxes" icon={<Boxes className="size-[18px]" />}>Sandbox</Item>
          {can(me, 'tools.manage') && <Item to="/tools" icon={<Wrench className="size-[18px]" />}>Công cụ & kết nối</Item>}
          {can(me, 'assistant.use') && <Item to="/assistant" icon={<Bot className="size-[18px]" />}>AI tổng</Item>}
          <Soon icon={<Database className="size-[18px]" />}>Dữ liệu</Soon>
          <Soon icon={<ChartColumn className="size-[18px]" />}>Báo cáo</Soon>
          <Item to="/audit" icon={<ScrollText className="size-[18px]" />}>Nhật ký hoạt động</Item>
          {can(me, 'team.manage') && <Item to="/team" icon={<UserCog className="size-[18px]" />}>Nhân viên & quyền</Item>}
          {can(me, 'sources.manage') ? <Item to="/settings" icon={<Settings className="size-[18px]" />}>Cài đặt</Item> : <Soon icon={<Settings className="size-[18px]" />}>Cài đặt</Soon>}
        </nav>
        <div className="flex shrink-0 flex-col gap-3">
          <AiStatus me={me} />
          <NavLink to="/account" className="flex flex-col px-2 text-xs text-ink-2 hover:text-ink"><b className="truncate text-[13px] text-ink">{me.name}</b><span className="truncate">Tài khoản và mật khẩu</span></NavLink>
          <button onClick={() => logout.mutate()} className="flex items-center gap-2 px-2 text-xs text-ink-2 hover:text-ink">
            <LogOut className="size-3.5" aria-hidden />Đăng xuất · {me.staff_ref ?? me.email}
          </button>
        </div>
      </aside>
      <main className="h-full min-h-0 min-w-0 flex-1 overflow-hidden"><Outlet /></main>
    </div>
  )
}
