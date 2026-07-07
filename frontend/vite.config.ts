import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api/v1/workflows': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/api/v1/executions': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/api/v1/webhooks': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/api/v1/actions': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
