import path from 'node:path'
import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const rootDir = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(rootDir, 'src'),
    },
  },
  server: {
    // Bind all interfaces so LAN / phone testing works with `npm run dev -- --host`.
    host: true,
    port: 5173,
    proxy: {
      // Prefer relative `/api/...` (leave VITE_API_BASE_URL empty) when the UI
      // is opened from a LAN IP — that avoids CORS entirely because the browser
      // talks only to Vite, which proxies to the backend.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
