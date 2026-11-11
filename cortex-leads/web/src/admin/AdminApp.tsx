import { LogOut, ShieldCheck, ShieldHalf } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { ApiError } from '../api/client'
import { Button, Card, ErrorBox, Loading } from '../components/ui'
import { adminProblem, useAdminCode, useAdminLogin, useAdminLogout, useAdminSession } from './api'
import { codeInput, input } from './bits'
import { TenantPage } from './TenantPage'
import { Tenants } from './Tenants'


/** Password, then the code. There is no other way in: an admin always has two-step sign-in (it is set up by `cli create-admin`). */
function AdminLogin() {
  const { data: me } = useAdminSession()
  const login = useAdminLogin()
  const send = useAdminCode()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [spare, setSpare] = useState(false)
  const asked = login.isSuccess
  if (me) return <Navigate to="/admin" replace />
  const expired = send.error instanceof ApiError && send.error.code === 'MFA_EXPIRED'
  const back = () => { login.reset(); send.reset(); setCode('') }
  return (
    <div className="flex h-full items-center justify-center p-6">
      <Card className="w-full max-w-sm p-6 sm:p-8">
        <div className="mb-6 flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-lg bg-ink text-white" aria-hidden><ShieldHalf className="size-5" /></span>
          <div><h1 className="text-xl font-bold">Quản trị Cortex</h1><p className="text-xs text-ink-2">{asked ? 'Xác thực 2 lớp' : 'Chỉ dành cho người vận hành máy chủ'}</p></div>
        </div>
        {!asked ? (
          <form className="flex flex-col gap-3" onSubmit={(e: FormEvent) => { e.preventDefault(); login.mutate({ email: email.trim(), password }, { onSuccess: () => setPassword('') }) }}>
            <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Email
              <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className={input} /></label>
            <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Mật khẩu
              <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={input} /></label>
            {login.isError && <p role="alert" className="text-[13px] text-bad">{adminProblem(login.error)}</p>}
            <Button variant="primary" type="submit" busy={login.isPending} disabled={!email.includes('@') || !password}>Tiếp tục</Button>
            <p className="text-xs text-ink-3">Chủ hoặc nhân viên trung tâm? <a href="/app/login" className="font-semibold text-accent underline">Đăng nhập ở đây</a>.</p>
          </form>
        ) : (
          <form className="flex flex-col gap-3" onSubmit={(e: FormEvent) => { e.preventDefault(); send.mutate(code.trim()) }}>
            <div className="flex items-start gap-2.5 rounded-lg bg-accent-soft px-3.5 py-3 text-[13px] text-ink-2">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
              <span>{spare ? 'Nhập một mã dự phòng đã in ra khi tạo tài khoản admin.' : 'Nhập mã 6 số ứng dụng xác thực đang hiện.'}</span>
            </div>
            <label className="flex flex-col gap-1.5 text-[13px] font-semibold">{spare ? 'Mã dự phòng' : 'Mã xác thực'}
              <input autoFocus key={spare ? 'spare' : 'app'} value={code} autoComplete="one-time-code" inputMode={spare ? 'text' : 'numeric'}
                onChange={(e) => setCode(spare ? e.target.value : e.target.value.replace(/\D/g, '').slice(0, 6))}
                className={spare ? `${input} font-mono` : codeInput} placeholder={spare ? 'abcde-12345' : '123456'} /></label>
            {send.isError && <p role="alert" className="text-[13px] text-bad">{adminProblem(send.error)}</p>}
            {expired ? <Button variant="primary" type="button" onClick={back}>Đăng nhập lại</Button>
              : <Button variant="primary" type="submit" busy={send.isPending} disabled={spare ? code.replace(/[-\s]/g, '').length !== 10 : !/^\d{6}$/.test(code)}>Xác nhận</Button>}
            <div className="flex items-center justify-between text-xs">
              <button type="button" onClick={back} className="text-ink-2 hover:text-ink">Quay lại</button>
              <button type="button" onClick={() => { setSpare(!spare); setCode(''); send.reset() }} className="font-semibold text-accent hover:underline">
                {spare ? 'Dùng mã trong ứng dụng' : 'Dùng mã dự phòng'}</button>
            </div>
          </form>
        )}
      </Card>
    </div>
  )
}

function AdminShell() {
  const { data: me, isPending, isError, refetch } = useAdminSession()
  const logout = useAdminLogout()
  if (isPending) return <Loading />
  // a failed background check keeps the last answer (see Authed in App.tsx)
  if (isError && me === undefined) return <ErrorBox onRetry={() => refetch()}>Không kết nối được máy chủ. Trang sẽ tự kết nối lại khi mạng ổn định.</ErrorBox>
  if (!me) return <Navigate to="/admin/login" replace />
  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="flex shrink-0 items-center gap-3 border-b border-line bg-ink px-4 py-3 text-white sm:px-6">
        <Link to="/admin" className="flex min-w-0 items-center gap-2 font-bold"><ShieldHalf className="size-5 shrink-0" aria-hidden /><span className="truncate">Quản trị Cortex</span></Link>
        <span className="ml-auto truncate text-xs text-white/70 max-sm:hidden">{me.email}</span>
        <button type="button" onClick={() => logout.mutate()} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold hover:bg-white/10">
          <LogOut className="size-3.5" aria-hidden />Đăng xuất</button>
      </header>
      {me.recovery_left !== undefined && (
        <p role="status" className="bg-warn-soft px-4 py-2 text-[13px] text-warn sm:px-6">Bạn vừa dùng một mã dự phòng; còn {me.recovery_left} mã. Hết mã thì phải chạy <code>cli reset-admin-mfa</code> trên máy chủ.</p>
      )}
      <main className="min-h-0 flex-1 overflow-y-auto bg-app"><div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 sm:p-6"><Outlet /></div></main>
    </div>
  )
}

/** Mounted at /admin/* by App. Its own sign-in, its own layout: nothing of the console's shell or session. */
export function AdminApp() {
  return (
    <Routes>
      <Route path="login" element={<AdminLogin />} />
      <Route element={<AdminShell />}>
        <Route index element={<Tenants />} />
        <Route path="tenants/:id" element={<TenantPage />} />
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Route>
    </Routes>
  )
}
