import { Brain } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { ApiError, explain } from '../api/client'
import { useLogin, useRecovery, useSession } from '../api/hooks'
import { Button, Card } from '../components/ui'

const input = 'rounded-lg border border-line px-3 py-2.5 text-sm font-normal'

/** A refusal in words that help without helping a guesser: the same line whether the email exists or not. */
export function loginProblem(e: unknown): string {
  if (e instanceof ApiError && e.status === 429) {
    const s = (e.detail as { retry_after_s?: number } | null)?.retry_after_s ?? 0
    return `Quá nhiều lần thử. Hãy đợi ${s > 90 ? `${Math.ceil(s / 60)} phút` : 'ít phút'} rồi thử lại.`
  }
  if (e instanceof ApiError && e.status === 401) return 'Email hoặc mật khẩu không đúng.'
  return explain(e)
}

export function Login() {
  const { data: me } = useSession()
  const login = useLogin()
  const recovery = useRecovery()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  if (me) return <Navigate to="/inbox" replace />
  const submit = (e: FormEvent) => { e.preventDefault(); login.mutate({ email: email.trim(), password }) }
  return (
    <div className="flex h-full items-center justify-center p-6">
      <Card className="w-full max-w-sm p-8">
        <div className="mb-6 flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-lg bg-accent text-white" aria-hidden><Brain className="size-5" /></span>
          <div><h1 className="text-xl font-bold">Cortex</h1><p className="text-xs text-ink-2">Đăng nhập vào trung tâm của bạn</p></div>
        </div>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Email
            <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className={input} placeholder="ten@trungtam.vn" /></label>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Mật khẩu
            <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={input} /></label>
          {login.isError && <p role="alert" className="text-[13px] text-bad">{loginProblem(login.error)}</p>}
          <Button variant="primary" type="submit" busy={login.isPending} disabled={!email.includes('@') || password.length < 1}>Đăng nhập</Button>
          {recovery.data?.enabled
            ? <p className="text-xs"><Link to="/forgot" className="font-semibold text-accent underline">Quên mật khẩu?</Link></p>
            : <p className="text-xs text-ink-3">Quên mật khẩu? Nhờ chủ trung tâm đặt lại cho bạn.</p>}
        </form>
      </Card>
    </div>
  )
}
