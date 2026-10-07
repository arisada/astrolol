import { defineConfig } from 'vitest/config'
import path from 'path'

// Unit tests for pure UI logic (no DOM). Kept apart from vite.config.ts so the dev proxy and the
// type-checker overlay plugin are not started for test runs.
export default defineConfig({
  resolve: { alias: { '@': path.resolve(__dirname, 'src'), '@plugins': path.resolve(__dirname, '../plugins') } },
  test: { include: ['src/**/*.test.ts', '../plugins/*/ui/**/*.test.ts'] },
})
