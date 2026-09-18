import { describe, expect, it } from 'vitest'
import { TOOL_CATALOG, toolForAction } from '../tools/catalog'

describe('tool catalog', () => {
  it('maps every A01-A10 action to a named execution tool', () => {
    expect(Object.keys(TOOL_CATALOG)).toHaveLength(10)
    expect(new Set(Object.values(TOOL_CATALOG).map((tool) => tool.id)).size).toBe(10)
    expect(toolForAction('A05_OPTIMIZE')?.nameZh).toBe('参数优化工具')
  })
})
