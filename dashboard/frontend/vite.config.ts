import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies /api to the FastAPI backend (see dashboard/README.md).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8765',
    },
  },
})
