import { afterEach, expect, test, vi } from 'vitest'
import contract from '../../../contracts/knowledge-base.schema.json'
import cases from '../../../contracts/knowledge-base.cases.json'
import { matchesSchema } from './schemaContract'
import { endpoints } from './client'
import { validBases } from './collectionValidation'

afterEach(() => vi.unstubAllGlobals())

test.each(cases)('shares the Java knowledge base REST case $id', ({ schema, data, valid }) => {
  expect(matchesSchema(contract.$defs[schema], data, contract.$defs)).toBe(valid)
  if (schema === 'KnowledgeBase') expect(validBases([data])).toBe(valid)
  if (schema === 'KnowledgeBaseList') expect(validBases(data)).toBe(valid)
})

test('keeps collection identity and nonblank-name rules alongside the shared schema', () => {
  expect(validBases([{ id: 1, name: '资料库' }, { id: 1, name: '重复' }])).toBe(false)
  expect(validBases([{ id: 1, name: ' \t\n' }])).toBe(false)
})

test.each([
  ['knowledgeBases', [], 'GET', '/knowledge/base/list', 'KnowledgeBaseList', 'bases-list'],
  ['createKnowledgeBase', [{ name: '学习', description: '笔记' }], 'POST', '/knowledge/base', 'KnowledgeBase', 'base-current'],
  ['deleteKnowledgeBase', [9], 'DELETE', '/knowledge/base/9', 'KnowledgeBaseDeletionReceipt', 'deletion-accepted'],
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
  if (method === 'POST') expect(JSON.parse(options.body)).toEqual(args[0])
  expect(fetch).toHaveBeenCalledOnce()
})
