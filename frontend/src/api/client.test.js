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
  it('passes an independent abort signal and receipt id with multipart uploads', async () => {
    const controller = new AbortController()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ code: 200, data: { id: 7 } }) }))
    const file = new File(['sample'], 'sample.txt')
    await endpoints.uploadDocument(3, file, { signal: controller.signal, requestId: 'test-request' })
    const [url, options] = fetch.mock.calls[0]
    expect(url).toBe('/api/v1/knowledge/document/upload')
    expect(options.signal).toBe(controller.signal)
    expect(options.body.get('requestId')).toBe('test-request')
    expect(options.body.get('file').name).toBe('sample.txt')
    expect(options.headers['Content-Type']).toBeUndefined()
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

  it.each(['/auth/login', '/auth/register'])('explains an empty rate-limit response for %s', async (path) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 429,
      headers: new Headers({ 'Retry-After': '23' }),
      json: async () => { throw new SyntaxError('empty body') },
    }))
    await expect(api(path)).rejects.toMatchObject({ status: 429, message: '请求过于频繁，请在 23 秒后重试' })
  })

  it('explains rate limits without a retry header', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 429, headers: new Headers(), json: async () => null,
    }))
    await expect(api('/auth/login')).rejects.toMatchObject({ message: '请求过于频繁，请稍后重试' })
  })

  it('explains a non-JSON gateway outage', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 502, json: async () => { throw new SyntaxError('HTML body') },
    }))
    await expect(api('/auth/login')).rejects.toMatchObject({ status: 502, message: '服务暂时不可用，请稍后重试' })
  })

  it('explains a network outage without exposing the browser fetch error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api('/auth/login')).rejects.toMatchObject({
      status: 0,
      message: '无法连接服务，请确认 Mneme 服务已启动后重试',
    })
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

  it('treats an acknowledged stopped event as terminal and cancels the reader', async () => {
    const reader = {
      read: vi.fn().mockResolvedValueOnce({ value: new TextEncoder().encode('event: stopped\ndata: {"code":"USER_STOPPED"}\n\n'), done: false }),
      cancel: vi.fn(), releaseLock: vi.fn(),
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body: { getReader: () => reader } }))
    await expect(streamChat({}, { onEvent: vi.fn() })).resolves.toEqual({ status: 'stopped' })
    expect(reader.read).toHaveBeenCalledOnce()
    expect(reader.cancel).toHaveBeenCalledOnce()
    expect(reader.releaseLock).toHaveBeenCalledOnce()
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

  it('preserves cancellation for callers instead of showing a connection error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('aborted', 'AbortError')))
    await expect(api('/sessions')).rejects.toMatchObject({ name: 'AbortError' })
  })

  it.each([
    ['event: token\ndata: {"content":"partial"}\n\n', '连接已中断'],
    ['event: error\ndata: {"message":"模型不可用"}\n\n', '模型不可用'],
    ['event: token\ndata: {"content":"partial"}\n\nevent: error\ndata: {"message":"输出失败"}\n\nevent: done\ndata: {"ok":true}\n\n', '输出失败'],
  ])('rejects incomplete or failed streams: %s', async (body, message) => {
    const reader = {
      read: vi.fn().mockResolvedValueOnce({ value: new TextEncoder().encode(body), done: false }).mockResolvedValue({ done: true }),
      cancel: vi.fn(), releaseLock: vi.fn(),
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body: { getReader: () => reader } }))
    await expect(streamChat({}, { onEvent: vi.fn() })).rejects.toThrow(message)
    expect(reader.cancel).toHaveBeenCalledOnce()
    expect(reader.releaseLock).toHaveBeenCalledOnce()
  })

  it('parses CRLF, comments and multiline event data', async () => {
    const reader = {
      read: vi.fn().mockResolvedValueOnce({ value: new TextEncoder().encode(': heartbeat\r\nevent: token\r\ndata: {\r\ndata: "content":"你好"}\r\n\r\nevent: done\r\ndata: {"ok":true}\r\n\r\n'), done: false }),
      cancel: vi.fn(), releaseLock: vi.fn(),
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body: { getReader: () => reader } }))
    const onEvent = vi.fn()
    await streamChat({}, { onEvent })
    expect(onEvent).toHaveBeenCalledWith('token', { content: '你好' })
    expect(onEvent).toHaveBeenCalledWith('done', { ok: true })
  })
})
