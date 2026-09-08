import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    globals: true,
    include: ['src/__tests__/archifyWorkbench.test.ts'],
    exclude: ['**/node_modules/**', '**/e2e/**', '**/dist/**'],
  },
})
