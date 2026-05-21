import { useState } from 'react'
import type { FormEvent } from 'react'

type AuthMode = 'login' | 'register'

interface AuthPanelProps {
  onLogin: (email: string, pass: string) => Promise<void>
  onRegister: (name: string, email: string, pass: string) => Promise<void>
  isBusy: boolean
}

export function AuthPanel({ onLogin, onRegister, isBusy }: AuthPanelProps) {
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [loginEmail, setLoginEmail] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [registerName, setRegisterName] = useState('')
  const [registerEmail, setRegisterEmail] = useState('')
  const [registerPassword, setRegisterPassword] = useState('')

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
    <div className="auth-container">
      <div className="auth-card">
        <div className="auth-card-header">
          <div className="auth-card-icon">C</div>
          <div className="auth-card-title">Welcome to Cortex</div>
          <div className="auth-card-sub">Your personal academic planner</div>
        </div>

        <div className="auth-tabs">
          <button
            type="button"
            className={`auth-tab${authMode === 'login' ? ' active' : ''}`}
            onClick={() => setAuthMode('login')}
          >
            Sign in
          </button>
          <button
            type="button"
            className={`auth-tab${authMode === 'register' ? ' active' : ''}`}
            onClick={() => setAuthMode('register')}
          >
            Create account
          </button>
        </div>

        {authMode === 'login' ? (
          <form className="auth-form" onSubmit={handleLogin}>
            <div className="form-field">
              <label className="form-label" htmlFor="login-email">Email</label>
              <input
                id="login-email"
                className="form-input"
                type="email"
                required
                placeholder="you@university.edu"
                value={loginEmail}
                onChange={(e) => setLoginEmail(e.target.value)}
              />
            </div>
            <div className="form-field">
              <label className="form-label" htmlFor="login-password">Password</label>
              <input
                id="login-password"
                className="form-input"
                type="password"
                required
                minLength={8}
                placeholder="••••••••"
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
              />
            </div>
            <button className="form-submit" type="submit" disabled={isBusy}>
              {isBusy ? 'Signing in…' : 'Continue'}
            </button>
          </form>
        ) : (
          <form className="auth-form" onSubmit={handleRegister}>
            <div className="form-field">
              <label className="form-label" htmlFor="reg-name">Full name</label>
              <input
                id="reg-name"
                className="form-input"
                type="text"
                placeholder="Alice Smith"
                value={registerName}
                onChange={(e) => setRegisterName(e.target.value)}
              />
            </div>
            <div className="form-field">
              <label className="form-label" htmlFor="reg-email">Email</label>
              <input
                id="reg-email"
                className="form-input"
                type="email"
                required
                placeholder="you@university.edu"
                value={registerEmail}
                onChange={(e) => setRegisterEmail(e.target.value)}
              />
            </div>
            <div className="form-field">
              <label className="form-label" htmlFor="reg-password">Password</label>
              <input
                id="reg-password"
                className="form-input"
                type="password"
                required
                minLength={8}
                placeholder="Min. 8 characters"
                value={registerPassword}
                onChange={(e) => setRegisterPassword(e.target.value)}
              />
            </div>
            <button className="form-submit" type="submit" disabled={isBusy}>
              {isBusy ? 'Creating account…' : 'Create account'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}