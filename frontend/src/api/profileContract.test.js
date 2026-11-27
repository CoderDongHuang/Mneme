import { afterEach, expect, test, vi } from 'vitest'
import contract from '../../../contracts/profile.schema.json'
import cases from '../../../contracts/profile.cases.json'
import { matchesSchema } from './schemaContract'
import { endpoints } from './client'
import { validAuthSessions, validEmailReceipt, validProfile } from '../features/profile/profileValidation'

afterEach(() => vi.unstubAllGlobals())

test.each(cases)('shares the Java profile REST case $id', ({ schema, data, valid }) => {
  expect(matchesSchema(contract.$defs[schema], data, contract.$defs)).toBe(valid)
  if (schema === 'Profile') expect(validProfile(data)).toBe(valid)
  if (schema === 'AuthSessionList') expect(validAuthSessions(data)).toBe(valid)
  if (schema === 'EmailVerificationReceipt') expect(validEmailReceipt(data)).toBe(valid)
})

test.each([
  ['profile', [], 'GET', '/profile', 'profile-current'],
  ['authSessions', [], 'GET', '/profile/sessions', 'sessions-current'],
  ['updateProfile', [{ nickname: 'Alice', email: 'alice@example.test' }], 'PATCH', '/profile', 'profile-current'],
  ['requestEmailVerification', ['alice@example.test'], 'POST', '/profile/email-verification/request', 'email-receipt'],
  ['confirmEmailVerification', ['abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789'], 'POST', '/profile/email-verification/confirm', 'profile-current'],
  ['revokeAuthSession', ['session-1'], 'DELETE', '/profile/sessions/session-1', 'void-success'],
  ['changePassword', [{ currentPassword: 'old-password', newPassword: 'new-password' }], 'POST', '/profile/password', 'void-success'],
  ['deleteAccount', [], 'DELETE', '/profile/account', 'account-delete'],
])('preserves the %s response and request through the browser entry point', async (name, args, method, path, caseId) => {
  const item = cases.find(value => value.id === caseId)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, status: 200, json: async () => ({ code: 200, message: 'success', data: item.data }),
  }))
  const result = await endpoints[name](...args)
  expect(result).toEqual(item.data)
  expect(matchesSchema(contract.$defs[item.schema], result, contract.$defs)).toBe(item.valid)
  const [url, options] = fetch.mock.calls[0]
  expect(url).toBe(`/api/v1${path}`)
  expect(options.method || 'GET').toBe(method)
  if (name === 'updateProfile') expect(JSON.parse(options.body)).toEqual(args[0])
  if (name === 'requestEmailVerification') expect(JSON.parse(options.body)).toEqual({ email: args[0] })
  if (name === 'confirmEmailVerification') expect(JSON.parse(options.body)).toEqual({ token: args[0] })
  if (name === 'changePassword') expect(JSON.parse(options.body)).toEqual(args[0])
  expect(fetch).toHaveBeenCalledOnce()
})
