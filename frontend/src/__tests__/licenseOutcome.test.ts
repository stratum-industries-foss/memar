import { describe, it, expect, vi, afterEach } from 'vitest'
import { activateLicense } from '../FirstRunSetup'

const realFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = realFetch })

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('activateLicense outcomes (audit 11)', () => {
  it('a rejected key says the key was not accepted', async () => {
    globalThis.fetch = vi.fn(async () => json(400, { detail: 'bad' })) as any
    const r = await activateLicense('K', 't')
    expect(r.ok).toBe(false)
    expect(r.message).toBe('License key not accepted.')
  })

  it('a network failure does NOT blame the key', async () => {
    globalThis.fetch = vi.fn(async () => { throw new TypeError('Failed to fetch') }) as any
    const r = await activateLicense('K', 't')
    expect(r.ok).toBe(false)
    expect(r.message).toMatch(/Could not reach MEMAR/)
    expect(r.message).not.toMatch(/not accepted/)
  })

  it('a server error (5xx) does NOT blame the key', async () => {
    globalThis.fetch = vi.fn(async () => json(503, { detail: 'down' })) as any
    const r = await activateLicense('K', 't')
    expect(r.message).toMatch(/Could not reach MEMAR/)
    expect(r.message).not.toMatch(/not accepted/)
  })

  it('an accepted key reports the plan', async () => {
    globalThis.fetch = vi.fn(async (url: any) =>
      String(url).includes('/status')
        ? json(200, { tier: 'farm', device_limit: 150 })
        : json(200, { ok: true })) as any
    const r = await activateLicense('K', 't')
    expect(r.ok).toBe(true)
    expect(r.message).toMatch(/Farm plan active/)
  })
})
