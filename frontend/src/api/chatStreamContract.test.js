import { expect, test, vi, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { validChatEvent } from './chatStreamContract'
import { streamChat } from './client'

// Preserve own __proto__ keys exactly as JSON.parse receives them on the wire.
const cases = JSON.parse(readFileSync('../contracts/chat-stream.cases.json', 'utf8'))

afterEach(() => vi.unstubAllGlobals())

test.each(cases)('shared SSE contract: $id', item => {
  expect(validChatEvent(item.event, item.data)).toBe(item.valid)
})

test.each([
  'event: token\ndata: not-json\n\n',
  'event: done\ndata: {"ok":true} {"private":123}\n\n',
  'event: done\ndata: {"ok":true} private\n\n',
  ...cases.filter(item => !item.valid).map(item => `event: ${item.event}\ndata: ${JSON.stringify(item.data)}\n\n`),
])('invalid SSE never reaches callbacks or succeeds: %s', async frame => {
  const reader = {
    read: vi.fn().mockResolvedValueOnce({ value: new TextEncoder().encode(frame + 'event: done\ndata: {"ok":true}\n\n'), done: false }).mockResolvedValue({ done: true }),
    cancel: vi.fn(), releaseLock: vi.fn(),
  }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body: { getReader: () => reader } }))
  const onEvent = vi.fn()
  await expect(streamChat({}, { onEvent })).rejects.toMatchObject({ payload: { code: 'INVALID_CHAT_EVENT' } })
  expect(onEvent).not.toHaveBeenCalled()
  expect(reader.cancel).toHaveBeenCalledOnce()
  expect(reader.releaseLock).toHaveBeenCalledOnce()
})
