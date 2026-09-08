import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

describe('Archify workbench driver', () => {
  const source = readFileSync(join(process.cwd(), 'public/workbench-driver.js'), 'utf8')

  it('opens input from first diagram step and shows a live progress panel', () => {
    expect(source).toContain('data-node-id')
    expect(source).toContain('openInputPanel')
    expect(source).toContain('hydro-panel')
    expect(source).toContain('hydro-progress')
    expect(source).toContain('hydro-active')
    expect(source).toContain('hydro-llm')
    expect(source).toContain('llm_streaming')
    expect(source).toContain('SiliconFlow 正在输出')
    expect(source).not.toContain('location.hash =')
  })
})
