import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, createTraceparent, endpoints, openNotificationStream, streamChat } from './client'

describe('api client', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { getRandomValues: (values) => values.fill(7) })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })
  it('creates valid W3C trace context for gateway propagation', () => {
    expect(createTraceparent()).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/)
  })
  it('unwraps the gateway result envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ code: 200, message: 'success', data: { id: 7 } }),
    }))
    await expect(api('/example')).resolves.toEqual({ id: 7 })
    expect(fetch).toHaveBeenCalledWith('/api/v1/example', expect.objectContaining({
      headers: expect.objectContaining({ traceparent: expect.stringMatching(/^00-/) }),
    }))
  })

  it('rejects an application-level error envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ code: 400, message: 'bad request' }),
    }))
    await expect(api('/example')).rejects.toMatchObject({ message: 'bad request' })
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
  })

  it('dispatches unauthorized when the gateway rejects the session', async () => {
    const listener = vi.fn()
    window.addEventListener('mneme:unauthorized', listener)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ message: 'expired' }),
    }))

    await expect(api('/profile')).rejects.toMatchObject({ status: 401, message: 'expired' })
    expect(listener).toHaveBeenCalledOnce()
    window.removeEventListener('mneme:unauthorized', listener)
  })

  it('parses chunked SSE and flushes a final event without a newline', async () => {
    const encoder = new TextEncoder()
    const chunks = [
      'event: token\ndata: {"content":"你',
      '好"}\n\nevent: done\ndata: {"ok":true}',
    ].map((value) => encoder.encode(value))
    let index = 0
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      body: { getReader: () => ({ read: async () => index < chunks.length ? { value: chunks[index++], done: false } : { done: true } }) },
    }))
    const events = []

    await streamChat({ message: 'test' }, { onEvent: (name, data) => events.push([name, data]) })

    expect(events).toEqual([
      ['token', { content: '你好' }],
      ['done', { ok: true }],
    ])
  })

  it('reconnects notification SSE with backoff and stops after close', () => {
    vi.useFakeTimers()
    const sources = []
    class FakeEventSource {
      constructor(url, options) {
        this.url = url
        this.options = options
        this.listeners = {}
        this.close = vi.fn()
        sources.push(this)
      }
      addEventListener(name, listener) { this.listeners[name] = listener }
    }
    const onEvent = vi.fn()
    const controller = openNotificationStream(onEvent, {
      EventSourceClass: FakeEventSource,
      baseDelayMs: 100,
      maxDelayMs: 1_000,
    })

    sources[0].onerror()
    expect(onEvent).toHaveBeenCalledWith(null)
    expect(sources[0].close).toHaveBeenCalledOnce()
    vi.advanceTimersByTime(99)
    expect(sources).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(sources).toHaveLength(2)
    sources[1].listeners.task({ data: '{"task_id":7}' })
    expect(onEvent).toHaveBeenLastCalledWith({ task_id: 7 })
    sources[1].onerror()
    controller.close()
    vi.runAllTimers()
    expect(sources).toHaveLength(2)
  })
})
