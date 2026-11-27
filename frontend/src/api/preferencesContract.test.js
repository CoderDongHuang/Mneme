import { afterEach, expect, test, vi } from 'vitest'
import contract from '../../../contracts/preferences.schema.json'
import cases from '../../../contracts/preferences.cases.json'
import { endpoints } from './client'
import { matchesSchema } from './schemaContract'
import { validPreferences } from '../features/settings/preferencesValidation'

afterEach(() => vi.unstubAllGlobals())

test.each(cases)('shares the Java preference REST case $id', ({ schema, data, valid }) => {
  expect(matchesSchema(contract.$defs[schema], data, contract.$defs)).toBe(valid)
  if (schema === 'Preferences') expect(validPreferences(data)).toBe(valid)
})

test('rejects a timezone unsupported by the browser formatter', () => {
  expect(matchesSchema(contract.$defs.Preferences, {
    language: 'en', timezone: 'Invalid/Timezone', notifications: true, theme: 'system',
  }, contract.$defs)).toBe(true)
  expect(validPreferences({
    language: 'en', timezone: 'Invalid/Timezone', notifications: true, theme: 'system',
  })).toBe(false)
})

test.each([
  ['preferences', [], 'GET', '/settings/preferences'],
  ['savePreferences', [{ language: 'en', timezone: 'Europe/Amsterdam', notifications: false, theme: 'dark' }], 'PUT', '/settings/preferences'],
])('preserves the %s request through the browser entry point', async (name, args, method, path) => {
  const data = { language: 'en', timezone: 'Europe/Amsterdam', notifications: false, theme: 'dark' }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, status: 200, json: async () => ({ code: 200, message: 'success', data }),
  }))

  await expect(endpoints[name](...args)).resolves.toEqual(data)
  const [url, options] = fetch.mock.calls[0]
  expect(url).toBe(`/api/v1${path}`)
  expect(options.method || 'GET').toBe(method)
  if (name === 'savePreferences') expect(JSON.parse(options.body)).toEqual(args[0])
  expect(fetch).toHaveBeenCalledOnce()
})
