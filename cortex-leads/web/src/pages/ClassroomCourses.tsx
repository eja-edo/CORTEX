import { useState } from 'react'
import { Link } from 'react-router-dom'
import { explain } from '../api/client'
import { useAddClassroom, useGoogle, useGoogleCourses } from '../api/hooks'
import { Badge, Button, Card, Loading } from '../components/ui'

const input = 'rounded-lg border border-line bg-surface px-3 py-2 text-sm font-normal'

/** Which Classroom courses the grader reads: pick a connected Google account, then connect its courses. The account itself is set up in Cài đặt. */
export function ClassroomCourses() {
  const g = useGoogle()
  const add = useAddClassroom()
  const accounts = (g.data?.items ?? []).filter((a) => a.status === 'active' && a.can.classroom)
  const [picked, setPicked] = useState('')
  const account = picked || accounts[0]?.id || ''
  const courses = useGoogleCourses(account, !!account)
  const sandbox = g.data?.sandboxes.find((s) => s.purpose === 'classroom_grader')
  if (g.isPending) return <Loading />
  return (
    <Card className="flex flex-col gap-3 p-5">
      <div><h2 className="text-[15px] font-bold">Nối khoá học Classroom</h2>
        <p className="text-[13px] text-ink-2">Chọn khoá học để AI đọc bài nộp và đề xuất điểm. Tài khoản Google được kết nối ở <Link to="/settings" className="font-semibold text-accent underline">Cài đặt</Link>.</p></div>
      {!accounts.length ? <p className="text-[13px] text-ink-3">Chưa có tài khoản Google nào cấp quyền chấm bài Classroom. Kết nối ở Cài đặt rồi quay lại.</p>
        : !sandbox ? <p className="text-[13px] text-ink-3">Chưa có sandbox Chấm bài để nối khoá học vào.</p> : (
          <>
            {accounts.length > 1 && <select aria-label="Tài khoản Google" className={input} value={account} onChange={(e) => setPicked(e.target.value)}>{accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</select>}
            {courses.isPending ? <Loading label="Đang lấy danh sách lớp…" /> : courses.isError ? <p role="alert" className="text-[13px] text-bad">{explain(courses.error)}</p>
              : courses.data.items.length === 0 ? <p className="text-[13px] text-ink-3">Tài khoản này chưa có lớp nào đang hoạt động trên Classroom.</p>
                : courses.data.items.map((c) => (
                  <div key={c.id} className="flex items-center gap-3 border-t border-line pt-3 text-[13px]"><span className="min-w-0 flex-1 truncate">{c.name}{c.section && <span className="text-ink-3"> · {c.section}</span>}</span>
                    {c.connected ? <Badge tone="ok">Đã nối</Badge>
                      : <Button busy={add.isPending && add.variables?.course_id === c.id} onClick={() => add.mutate({ sandbox_id: sandbox.id, account_id: account, course_id: c.id, label: c.name })}>Nối khoá học này</Button>}</div>))}
            {add.isError && <p role="alert" className="text-[13px] text-bad">{explain(add.error)}</p>}
          </>)}
    </Card>
  )
}
