// The browser's own zone must never matter: tests run in Los Angeles while the business is in Vietnam (DESIGN §5.13).
process.env.TZ = 'America/Los_Angeles'
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
