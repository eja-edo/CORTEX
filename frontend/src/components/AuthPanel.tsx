import { useState, useCallback } from 'react'
import type { FormEvent, FocusEvent } from 'react'

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

  const handleFocus = useCallback((e: FocusEvent<HTMLInputElement>) => {
    e.target.parentElement?.querySelector('label')?.classList.add('label-active')
  }, [])

  const handleBlur = useCallback((e: FocusEvent<HTMLInputElement>) => {
    e.target.parentElement?.querySelector('label')?.classList.remove('label-active')
  }, [])

  return (
    <div className="auth-page">
      <div className="auth-container">
        <div className="auth-card">
          <div className="auth-card-header">
            <div className="auth-card-icon">C</div>
            <div>
              <div className="auth-card-title">Welcome to Cortex</div>
              <div className="auth-card-sub">Your personal academic planner</div>
            </div>
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

          <div className="auth-form-wrapper">
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
                    onFocus={handleFocus}
                    onBlur={handleBlur}
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
                    onFocus={handleFocus}
                    onBlur={handleBlur}
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
                    onFocus={handleFocus}
                    onBlur={handleBlur}
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
                    onFocus={handleFocus}
                    onBlur={handleBlur}
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
                    onFocus={handleFocus}
                    onBlur={handleBlur}
                  />
                </div>
                <button className="form-submit" type="submit" disabled={isBusy}>
                  {isBusy ? 'Creating account…' : 'Create account'}
                </button>
              </form>
            )}

            <div className="auth-divider">
              <div className="auth-divider-line" />
              <span className="auth-divider-text">Or continue with</span>
              <div className="auth-divider-line" />
            </div>

            <div className="auth-social">
              <button type="button" className="auth-social-btn" aria-label="Continue with Google">
                <svg className="auth-social-icon" viewBox="0 0 24 24">
                  <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
                  <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                  <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05" />
                  <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
                </svg>
              </button>
              <button type="button" className="auth-social-btn" aria-label="Continue with Apple">
                <svg className="auth-social-icon" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M17.05 20.28c-.96.95-2.06 1.81-3.23 1.81-1.12 0-1.48-.68-2.78-.68-1.31 0-1.7.67-2.78.67-1.14 0-2.31-1.11-3.27-2.07-1.98-1.98-3.03-4.88-3.03-7.58 0-4.38 2.76-6.68 5.42-6.68 1.41 0 2.5.91 3.36.91.84 0 2.09-.91 3.51-.91 1.22 0 2.37.5 3.12 1.34-2.82 1.66-2.36 5.6.45 6.84-.71 1.77-1.63 3.52-2.5 4.39zM12.01 4.6c-.02-1.98 1.62-3.7 3.52-3.83.19 1.94-1.74 3.79-3.52 3.83z" />
                </svg>
              </button>
              <button type="button" className="auth-social-btn" aria-label="Continue with Microsoft">
                <svg className="auth-social-icon" viewBox="0 0 23 23">
                  <path d="M0 0h11v11H0z" fill="#f35325" />
                  <path d="M12 0h11v11H12z" fill="#81bc06" />
                  <path d="M0 12h11v11H0z" fill="#05a6f0" />
                  <path d="M12 12h11v11H12z" fill="#ffba08" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      <footer className="auth-footer">
        <div className="auth-footer-inner">
          <div className="auth-footer-brand">
            <span className="auth-footer-logo">Cortex</span>
            <span className="auth-footer-copy">© 2024 Cortex Academic. All rights reserved.</span>
          </div>
          <nav className="auth-footer-links">
            <a href="#" className="auth-footer-link">Forgot password?</a>
            <a href="#" className="auth-footer-link">Help</a>
            <a href="#" className="auth-footer-link">Privacy Policy</a>
            <a href="#" className="auth-footer-link">Terms of Service</a>
          </nav>
        </div>
      </footer>
    </div>
  )
}
