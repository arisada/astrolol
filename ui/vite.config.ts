import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
// Backend URL for the dev-server proxy.  In Docker Compose the BACKEND_URL
// env var is set to the service name; locally it defaults to localhost.
const backendHttp = process.env.BACKEND_URL ?? 'http://localhost:8000'
const backendWs   = backendHttp.replace(/^http/, 'ws')

/**
 * Attach an error handler to an http-proxy instance so that when the backend
 * is unreachable (ECONNREFUSED, startup gap, mid-restart) the browser gets a
 * clean response instead of Vite logging "http proxy error" to the console.
 *
 * The third argument from http-proxy is http.ServerResponse for HTTP requests
 * but net.Socket for WebSocket upgrades, so we must guard before calling
 * writeHead (which only exists on ServerResponse).
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function withFallback(proxy: any): void {
  proxy.on('error', (_err: Error, _req: unknown, res: any) => {
    try {
      if (typeof res?.writeHead === 'function') {
        // Regular HTTP request — return a clean 503
        res.writeHead(503, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ detail: 'Backend unavailable' }))
      } else {
        // WebSocket socket — just close it
        res?.end?.()
      }
    } catch { /* ignore secondary errors in the error handler */ }
  })
}

function p(target: string) {
  return { target, changeOrigin: true, configure: withFallback }
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@plugins': path.resolve(__dirname, '../plugins'),
      // Allow plugin pages (outside ui/) to import packages from ui/node_modules
      'lucide-react': path.resolve(__dirname, './node_modules/lucide-react'),
      'react': path.resolve(__dirname, './node_modules/react'),
      'react/jsx-runtime': path.resolve(__dirname, './node_modules/react/jsx-runtime'),
    },
  },
  server: {
    fs: { allow: ['..'] },
    proxy: {
      '/api':      p(backendHttp),
      '/devices':  p(backendHttp),
      '/profiles': p(backendHttp),
      '/imager':   p(backendHttp),
      '/mount':    p(backendHttp),
      '/focuser':      p(backendHttp),
      '/filter_wheel': p(backendHttp),
      '/indi':         p(backendHttp),
      '/settings': p(backendHttp),
      '/events':   p(backendHttp),
      '/health':   p(backendHttp),
      '/plugins':  p(backendHttp),
      '/admin':    p(backendHttp),
      '/ws': { target: backendWs, ws: true, changeOrigin: true, configure: withFallback },
    },
  },
  build: {
    outDir: 'dist',
  },
})
