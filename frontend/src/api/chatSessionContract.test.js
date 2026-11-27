import { afterEach, expect, test, vi } from 'vitest'
import contract from '../../../contracts/chat-session.schema.json'
import cases from '../../../contracts/chat-session.cases.json'
import { matchesSchema } from './schemaContract'
import { endpoints } from './client'
import { validSessions } from './collectionValidation'

afterEach(() => vi.unstubAllGlobals())

test.each(cases)('shares the Java session REST case $id', ({ schema, data, valid }) => {
  expect(matchesSchema(contract.$defs[schema], data, contract.$defs)).toBe(valid)
  if (schema === 'ChatSession') expect(validSessions([data])).toBe(valid)
  if (schema === 'ChatSessionList') expect(validSessions(data)).toBe(valid)
})

test.each([
  ['sessions', [], 'GET', '/sessions', 'ChatSessionList', 'sessions-legacy'],
  ['createSession', ['学习'], 'POST', '/sessions', 'ChatSession', 'session-current'],
  ['renameSession', [9, '学习'], 'PATCH', '/sessions/9', 'ChatSession', 'session-current'],
  ['sessionMessages', [9], 'GET', '/sessions/9/messages', 'ChatHistory', 'history-list'],
  ['deleteSession', [9], 'DELETE', '/sessions/9', 'ChatSessionDeletionReceipt', 'deletion-pending'],
])('preserves the %s response and request through the browser entry point', async (name, args, method, path, schema, caseId) => {
  const data = cases.find(item => item.id === caseId).data
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, status: 200, json: async () => ({ code: 200, message: 'success', data }),
  }))
  const result = await endpoints[name](...args)
  expect(result).toEqual(data)
  expect(matchesSchema(contract.$defs[schema], result, contract.$defs)).toBe(true)
  const [url, options] = fetch.mock.calls[0]
  expect(url).toBe(`/api/v1${path}`)
  expect(options.method || 'GET').toBe(method)
  if (['POST', 'PATCH'].includes(method)) expect(JSON.parse(options.body)).toEqual({ title: '学习' })
  expect(fetch).toHaveBeenCalledOnce()
})
