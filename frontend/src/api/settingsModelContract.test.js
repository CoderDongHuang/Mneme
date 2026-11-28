import { afterEach, expect, test, vi } from 'vitest'
import contract from '../../../contracts/settings-model.schema.json'
import cases from '../../../contracts/settings-model.cases.json'
import { endpoints } from './client'
import { matchesSchema } from './schemaContract'
import { validModelSettings, validModelSettingsUpdate, validPersonalProbe } from '../features/settings/settingsValidation'

afterEach(() => vi.unstubAllGlobals())

test.each(cases)('shares the Java and Python model REST case $id', ({ schema, data, valid }) => {
  expect(matchesSchema(contract.$defs[schema], data, contract.$defs)).toBe(valid)
  if (schema === 'ModelSettings') expect(validModelSettings(data)).toBe(valid)
  if (schema === 'ModelSettingsUpdateRequest') expect(validModelSettingsUpdate(data)).toBe(valid)
  if (schema === 'ModelTestReceipt') expect(validPersonalProbe(data)).toBe(valid)
})

test.each([
  ['modelSettings', [], 'GET', '/settings/models'],
  ['saveModelSettings', [{ provider: 'openai', model: 'gpt-4.1-mini', apiKey: 'synthetic-test-secret', enabled: true, clearKey: false }], 'PUT', '/settings/models'],
  ['testModelSettings', [{ provider: 'openai', model: 'gpt-4.1-mini', apiKey: 'synthetic-test-secret', enabled: true, clearKey: false }], 'POST', '/settings/models/test'],
])('preserves the %s request through the browser entry point', async (name, args, method, path) => {
  const data = name === 'testModelSettings'
    ? { status: 'ok', model: 'gpt-4.1-mini', provider: 'openai', latency_ms: 23 }
    : { provider: 'openai', model: 'gpt-4.1-mini', enabled: true, hasKey: true, keyMask: '••••cret', baseUrl: 'https://api.openai.com/v1' }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, status: 200, json: async () => ({ code: 200, message: 'success', data }),
  }))

  await expect(endpoints[name](...args)).resolves.toEqual(data)
  const [url, options] = fetch.mock.calls[0]
  expect(url).toBe(`/api/v1${path}`)
  expect(options.method || 'GET').toBe(method)
  if (name !== 'modelSettings') expect(JSON.parse(options.body)).toEqual(args[0])
  expect(fetch).toHaveBeenCalledOnce()
})

test('preserves legacy metadata and validates normalized Java request values', () => {
  expect(validModelSettings({ provider: 'deepseek', model: 'deepseek-chat', enabled: false, extension: true })).toBe(true)
  expect(validModelSettings({ provider: 'deepseek', model: 'deepseek-chat', enabled: false, apiKey: 'secret' })).toBe(false)
  expect(validModelSettingsUpdate({ model: '  deepseek-chat  ', apiKey: '  secret  ' })).toBe(true)
  expect(validModelSettingsUpdate({ apiKey: '😀'.repeat(257) })).toBe(false)
  expect(validModelSettingsUpdate({ apiKey: 'invalid\u0001key', clearKey: true })).toBe(true)
  expect(validPersonalProbe({ status: 'ok', provider: 'deepseek', model: 'deepseek-chat', latency_ms: Number.MAX_SAFE_INTEGER + 1 })).toBe(false)
})
