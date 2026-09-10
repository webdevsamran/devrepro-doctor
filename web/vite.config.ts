/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8642' },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    // Vitest's default glob matches `*.spec.ts` anywhere, which swept up the
    // Playwright suites in `e2e/` and failed three files on every run with
    // "Playwright Test did not expect test.describe() to be called here".
    // The two runners share a filename convention and nothing else.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
  },
})