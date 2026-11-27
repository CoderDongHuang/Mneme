import { expect, test } from 'vitest'
import { validBases, validSessions } from './collectionValidation'

test.each([
  { id: 1, name: '资料库', userId: false },
  { id: 1, name: '资料库', status: {} },
  { id: 1, name: '资料库', chromaCollectionId: [] },
  { id: 1, name: '资料库', updatedAt: {} },
])('rejects a knowledge base whose business fields have drifted %#', base => {
  expect(validBases([base])).toBe(false)
})

test.each([
  { id: 1, userId: false },
  { id: 1, userId: 1.5 },
  { id: 1, userId: 9007199254740992 },
  { id: 1, deletionStatus: 'deleted' },
])('rejects a session whose business fields have drifted %#', session => {
  expect(validSessions([session])).toBe(false)
})

test('preserves legacy optional fields and rejects duplicate session identities', () => {
  const sessions = [{ id: 1 }, { id: 2, title: null, createdAt: null, updatedAt: null }]
  expect(validSessions(sessions)).toBe(true)
  expect(validSessions([sessions[0], sessions[0]])).toBe(false)
  expect(validSessions([null])).toBe(false)
})
