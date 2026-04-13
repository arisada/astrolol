import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Backend URL for the dev-server proxy.  In Docker Compose the BACKEND_URL
// env var is set to the service name; locally it defaults to localhost.
const backendHttp = process.env.BACKEND_URL ?? 'http://localhost:8000'
const backendWs   = backendHttp.replace(/^http/, 'ws')

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    proxy: {
      '/api':      { target: backendHttp, changeOrigin: true },
      '/devices':  { target: backendHttp, changeOrigin: true },
      '/profiles': { target: backendHttp, changeOrigin: true },
      '/imager':   { target: backendHttp, changeOrigin: true },
      '/mount':    { target: backendHttp, changeOrigin: true },
      '/focuser':  { target: backendHttp, changeOrigin: true },
      '/indi':     { target: backendHttp, changeOrigin: true },
      '/settings': { target: backendHttp, changeOrigin: true },
      '/events':   { target: backendHttp, changeOrigin: true },
      '/health':   { target: backendHttp, changeOrigin: true },
      '/ws':       { target: backendWs,   ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
  },
})
