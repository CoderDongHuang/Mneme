import { expect, test } from 'vitest'
import normalizeChatHistory from './normalizeChatHistory'

const message = { id: 11, sessionId: 9, role: 'assistant', content: 'saved answer' }
const source = { document_name: 'old.pdf', chunk_content: 'saved evidence' }

test.each([
  null, {}, [null], [{ ...message, content: {} }], [{ ...message, sessionId: 10 }],
  [{ ...message, errorCode: {} }], [{ ...message, id: 9007199254740992 }],
  [message, message], [{ ...message, role: 'tool' }],
])('rejects malformed history before the page snapshot is replaced %#', history => {
  expect(() => normalizeChatHistory(history, 9)).toThrow('Invalid message history')
})

test.each([
  null, {}, 'private evidence', [null], [{ ...source, chunk_content: {} }],
  [{ ...source, document_name: [] }], [{ ...source, content_sha256: {} }],
  [{ ...source, retrieval_ranks: { lexical: {} } }],
])('rejects parsed citation data that cannot safely render %#', sources => {
  expect(() => normalizeChatHistory([{ ...message, sourcesJson: JSON.stringify(sources) }], 9))
    .toThrow('Invalid history citations')
})

test('retains legacy optional values, citation metadata and opaque citation text', () => {
  const sources = [{ ...source, document_id: null, content_sha256: null, retrieval_ranks: null,
    visual_region: '0.1,0.2,0.8,0.9', original_document_id: 'imported-doc' }]
  const result = normalizeChatHistory([
    { ...message, sources, status: 'legacy_state' },
    { ...message, id: 12, sourcesJson: JSON.stringify(sources), status: null },
    { ...message, id: 13, sourcesJson: 'opaque old citation text' },
  ], 9)
  expect(result.map(item => item.status)).toEqual(['legacy_state', 'complete', 'complete'])
  expect(result[0].sources).toEqual(sources)
  expect(result[1].sources).toEqual(sources)
  expect(result[2].sources).toEqual([])
  expect(normalizeChatHistory([], 9)).toEqual([])
})

test('links retry text in one ordered pass and projects only validated display fields', () => {
  const history = [
    { ...message, id: 1, role: 'user', content: 'first question' },
    { ...message, id: 2, status: 'failed', errorCode: 'MODEL_TIMEOUT', pending: [{}], error: {} },
    { ...message, id: 3, role: 'user', content: 'second question' },
    { ...message, id: 4, status: 'stopped', sourcesJson: JSON.stringify([source]) },
  ]
  const result = normalizeChatHistory(history, 9)
  expect(result[1]).toMatchObject({ requestText: 'first question', status: 'failed', errorCode: 'MODEL_TIMEOUT' })
  expect(result[3]).toMatchObject({ requestText: 'second question', status: 'stopped', sources: [source] })
  expect(result[1]).not.toHaveProperty('pending')
  expect(result[1]).not.toHaveProperty('error')
  expect(history[1].pending).toEqual([{}])
})
