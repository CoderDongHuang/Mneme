import { expect, test, vi, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { validChatEvent } from './chatStreamContract'
import { streamChat } from './client'
import { matchesSchema } from './schemaContract'
import contract from '../../../contracts/chat-stream.schema.json'

// Preserve own __proto__ keys exactly as JSON.parse receives them on the wire.
const cases = JSON.parse(readFileSync('../contracts/chat-stream.cases.json', 'utf8'))

afterEach(() => vi.unstubAllGlobals())

test('completion input is bounded and cannot enter browser callbacks', () => {
  const data = { input: { user_id: '7', session_id: '9', delivery_id: 'turn', reference_time: '2026-11-06T00:00:00Z', answer: 'saved', history: Array.from({ length: 41 }, () => ({ role: 'user', content: 'question', timestamp: '2026-11-06T00:00:00Z' })) } }
  expect(matchesSchema(contract.events.completion, data, contract.$defs)).toBe(true)
  expect(validChatEvent('completion', data)).toBe(false)
  data.input.history.push(data.input.history[0])
  expect(matchesSchema(contract.events.completion, data, contract.$defs)).toBe(false)
})

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
