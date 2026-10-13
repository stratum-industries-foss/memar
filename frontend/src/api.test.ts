import { describe, it, expect } from 'vitest'
import { requireOk } from './api'

describe('requireOk', () => {
  it('returns response when ok', async () => {
    const res = new Response('{}', { status: 200 })
    const result = await requireOk(res)
    expect(result).toBe(res)
  })

  it('throws with detail from JSON body', async () => {
    const res = new Response(JSON.stringify({ detail: 'Payment required' }), { status: 402 })
    await expect(requireOk(res)).rejects.toThrow('Payment required')
  })

  it('throws with HTTP status when no detail', async () => {
    const res = new Response('{}', { status: 500 })
    await expect(requireOk(res)).rejects.toThrow('HTTP 500')
  })
})
