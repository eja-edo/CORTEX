import { useCallback, useState } from 'react'
import type { TokenPair, User } from '../types'
import { API_BASE_URL, requestJson, setCurrentTokens } from '../services/api'

const PKCE_CLIENT_ID = 'cortex-web'
const PKCE_REDIRECT_URI = window.location.origin + '/auth/callback'

function randomUrlSafeString(byteLength: number): string {
    const bytes = new Uint8Array(byteLength)
    window.crypto.getRandomValues(bytes)
    let output = ''
    for (const byte of bytes) output += String.fromCharCode(byte)
    return btoa(output).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
}

async function createCodeChallenge(verifier: string): Promise<string> {
    const encoder = new TextEncoder()
    const data = encoder.encode(verifier)
    const hashBuffer = await window.crypto.subtle.digest('SHA-256', data)
    const bytes = new Uint8Array(hashBuffer)
    let output = ''
    for (const byte of bytes) output += String.fromCharCode(byte)
    return btoa(output).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
}

export function useAuth() {
    const [tokens, setTokensState] = useState<TokenPair | null>(() => {
        const raw = window.localStorage.getItem('cortex_tokens')
        if (!raw) return null
        try {
            const parsed = JSON.parse(raw) as TokenPair
            if (parsed.accessToken && parsed.refreshToken) {
                setCurrentTokens(parsed)
                return parsed
            }
            return null
        } catch { return null }
    })
    const [user, setUser] = useState<User | null>(null)
    const [isBusy, setIsBusy] = useState(false)
    const [errorMessage, setErrorMessage] = useState('')
    const [statusMessage, setStatusMessage] = useState('')

    const setTokens = useCallback((newTokens: TokenPair | null) => {
        setTokensState(newTokens)
        setCurrentTokens(newTokens)
    }, [])

    const fetchCurrentUser = useCallback(async (activeTokens: TokenPair): Promise<void> => {
        try {
            const profile = await fetch(`${API_BASE_URL}/auth/me`, { headers: { Authorization: `Bearer ${activeTokens.accessToken}` } })
            if (profile.status === 401) {
                // Token expired, try refresh
                const payload = await requestJson<{ access_token: string; refresh_token: string; token_type: string }>(
                    `${API_BASE_URL}/auth/refresh`,
                    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: activeTokens.refreshToken }) },
                )
                const nextTokens = { accessToken: payload.access_token, refreshToken: payload.refresh_token }
                setTokens(nextTokens)
                const retried = await fetch(`${API_BASE_URL}/auth/me`, { headers: { Authorization: `Bearer ${nextTokens.accessToken}` } })
                if (!retried.ok) throw new Error('Cannot load profile')
                setUser((await retried.json()) as User)
                return
            }
            if (!profile.ok) throw new Error('Cannot load profile')
            setUser((await profile.json()) as User)
        } catch {
            setTokens(null)
            setUser(null)
            setErrorMessage('Your session expired. Please login again.')
        }
    }, [setTokens])

    const handleRegister = useCallback(async (name: string, email: string, pass: string): Promise<void> => {
        setErrorMessage(''); setStatusMessage(''); setIsBusy(true)
        try {
            await requestJson<User>(`${API_BASE_URL}/auth/register`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password: pass, full_name: name }),
            })
            setStatusMessage('Account created. You can login now.')
        } catch (error) {
            setErrorMessage(error instanceof Error ? error.message : 'Register failed')
        } finally { setIsBusy(false) }
    }, [])

    const handleLogin = useCallback(async (email: string, pass: string): Promise<void> => {
        setErrorMessage(''); setStatusMessage(''); setIsBusy(true)
        try {
            const codeVerifier = randomUrlSafeString(64).slice(0, 96)
            const codeChallenge = await createCodeChallenge(codeVerifier)
            const authorize = await requestJson<{ code: string }>(`${API_BASE_URL}/auth/authorize`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password: pass, client_id: PKCE_CLIENT_ID, redirect_uri: PKCE_REDIRECT_URI, code_challenge: codeChallenge, code_challenge_method: 'S256', state: randomUrlSafeString(24) }),
            })
            const tokenPair = await requestJson<{ access_token: string; refresh_token: string; token_type: string }>(`${API_BASE_URL}/auth/token`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: authorize.code, code_verifier: codeVerifier, client_id: PKCE_CLIENT_ID, redirect_uri: PKCE_REDIRECT_URI }),
            })
            const newTokens = { accessToken: tokenPair.access_token, refreshToken: tokenPair.refresh_token }
            setTokens(newTokens)
            setStatusMessage('Login successful.')
        } catch (error) {
            setErrorMessage(error instanceof Error ? error.message : 'Login failed')
        } finally { setIsBusy(false) }
    }, [setTokens])

    const handleLogout = useCallback(async (): Promise<void> => {
        if (!tokens) return
        try {
            await requestJson<{ message: string }>(`${API_BASE_URL}/auth/logout`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: tokens.refreshToken }),
            })
        } catch { /* continue */ }
        setTokens(null)
        setUser(null)
        setStatusMessage('You are logged out.')
    }, [tokens, setTokens])

    return {
        tokens,
        user,
        isBusy,
        errorMessage,
        statusMessage,
        setErrorMessage,
        setStatusMessage,
        setTokens,
        setUser,
        fetchCurrentUser,
        handleRegister,
        handleLogin,
        handleLogout,
    }
}
