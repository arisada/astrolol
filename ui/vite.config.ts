import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/devices': { target: 'http://localhost:8000', changeOrigin: true },
      '/profiles': { target: 'http://localhost:8000', changeOrigin: true },
      '/imager': { target: 'http://localhost:8000', changeOrigin: true },
      '/mount': { target: 'http://localhost:8000', changeOrigin: true },
      '/focuser': { target: 'http://localhost:8000', changeOrigin: true },
      '/indi': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
  },
})
