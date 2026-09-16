import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, endpoints } from './client'

describe('api client', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    })
  })
  it('unwraps the gateway result envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ code: 200, message: 'success', data: { id: 7 } }),
    }))
    await expect(api('/example')).resolves.toEqual({ id: 7 })
    vi.unstubAllGlobals()
  })

  it('rejects an application-level error envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ code: 400, message: 'bad request' }),
    }))
    await expect(api('/example')).rejects.toMatchObject({ message: 'bad request' })
    vi.unstubAllGlobals()
  })

  it('posts memory restore requests through the workspace API', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ code: 200, data: { restored: true } }),
    }))
    await endpoints.restoreMemory('mem_1', 3)
    expect(fetch).toHaveBeenCalledWith('/api/v1/workspace/memories/mem_1/restore', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ version: 3 }),
    }))
    vi.unstubAllGlobals()
  })
})
