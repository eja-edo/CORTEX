import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The built app is served by FastAPI at /app, so every asset URL is under /app/.
export default defineConfig({
  base: '/app/',
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': 'http://localhost:8200' } },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test/setup.ts'], css: false },
})
