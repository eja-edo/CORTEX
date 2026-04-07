import { useState } from 'react'
import type { FormEvent } from 'react'
import { clsx } from 'clsx'

type AuthMode = 'login' | 'register'

interface AuthPanelProps {
  onLogin: (email: string, pass: string) => Promise<void>
  onRegister: (name: string, email: string, pass: string) => Promise<void>
  isBusy: boolean
}

export function AuthPanel({ onLogin, onRegister, isBusy }: AuthPanelProps) {
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [loginEmail, setLoginEmail] = useState<string>('')
  const [loginPassword, setLoginPassword] = useState<string>('')
  const [registerName, setRegisterName] = useState<string>('')
  const [registerEmail, setRegisterEmail] = useState<string>('')
  const [registerPassword, setRegisterPassword] = useState<string>('')

  const handleRegister = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    await onRegister(registerName, registerEmail, registerPassword)
    setAuthMode('login')
    setLoginEmail(registerEmail)
  }

  const handleLogin = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    void onLogin(loginEmail, loginPassword)
  }

  return (
    <section className="panel auth-panel">
      <div className="auth-switcher">
        <button
          type="button"
          className={clsx('tab', authMode === 'login' && 'active')}
          onClick={() => setAuthMode('login')}
        >
          Login
        </button>
        <button
          type="button"
          className={clsx('tab', authMode === 'register' && 'active')}
          onClick={() => setAuthMode('register')}
        >
          Register
        </button>
      </div>

      {authMode === 'login' ? (
        <form className="form-grid" onSubmit={handleLogin}>
          <label>
            Email
            <input
              type="email"
              required
              placeholder="student@university.edu"
              value={loginEmail}
              onChange={(e) => setLoginEmail(e.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              required
              minLength={8}
              placeholder="••••••••"
              value={loginPassword}
              onChange={(e) => setLoginPassword(e.target.value)}
            />
          </label>
          <button className="primary" type="submit" disabled={isBusy}>
            {isBusy ? 'Signing in...' : 'Sign In with PKCE'}
          </button>
        </form>
      ) : (
        <form className="form-grid" onSubmit={handleRegister}>
          <label>
            Full Name
            <input
              type="text"
              placeholder="Alice Smith"
              value={registerName}
              onChange={(e) => setRegisterName(e.target.value)}
            />
          </label>
          <label>
            Email
            <input
              type="email"
              required
              placeholder="student@university.edu"
              value={registerEmail}
              onChange={(e) => setRegisterEmail(e.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              required
              minLength={8}
              placeholder="••••••••"
              value={registerPassword}
              onChange={(e) => setRegisterPassword(e.target.value)}
            />
          </label>
          <button className="primary" type="submit" disabled={isBusy}>
            {isBusy ? 'Creating...' : 'Create Account'}
          </button>
        </form>
      )}
    </section>
  )
}
