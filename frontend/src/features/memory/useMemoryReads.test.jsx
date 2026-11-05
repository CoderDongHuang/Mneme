import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import useMemoryReads from './useMemoryReads'
import { endpoints } from '../../api/client'

vi.mock('../../api/client', () => ({ endpoints: { managedMemories: vi.fn(), pendingMemories: vi.fn() } }))
const memory = { id: 'm1', content: 'Study with citations', tags: '["reading"]', confidence: 0.8 }
const candidate = { memoryId: 'p1', content: 'Needs confirmation', sessionId: 12 }
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
beforeEach(() => {
  vi.resetAllMocks()
  endpoints.managedMemories.mockResolvedValue({ memories: [memory] })
  endpoints.pendingMemories.mockResolvedValue([candidate])
})

test.each([null, {}, { memories: null }, { memories: {} }, { memories: [null] },
  { memories: [memory, memory] }, { memories: [{ ...memory, content: {} }] },
  { memories: [{ ...memory, tags: '{}' }] }, { memories: [{ ...memory, tags: '[{}]' }] },
  { memories: [{ ...memory, tags: 'broken' }] }, { memories: [{ ...memory, confidence: 4 }] },
  { memories: [{ ...memory, updated_at: {} }] }])('invalid memory data stays unavailable and can retry: %j', async value => {
  endpoints.managedMemories.mockResolvedValueOnce(value)
  const { result } = renderHook(useMemoryReads)
  await waitFor(() => expect(result.current.items.error).toBe(true))
  expect(result.current.items.data).toBeNull()
  expect(result.current.pending.data).toEqual([candidate])
  await act(() => result.current.items.refresh())
  expect(result.current.items.data).toEqual([memory])
  expect(result.current.items.error).toBe(false)
  expect(endpoints.pendingMemories).toHaveBeenCalledTimes(1)
})

test.each([null, {}, [candidate, candidate], [{ ...candidate, topic: {} }],
  [{ ...candidate, confidence: '0.8' }], [{ ...candidate, sessionId: {} }]])('invalid candidates do not become empty success: %j', async value => {
  endpoints.pendingMemories.mockResolvedValueOnce(value)
  const { result } = renderHook(useMemoryReads)
  await waitFor(() => expect(result.current.pending.error).toBe(true))
  expect(result.current.pending.data).toBeNull()
  expect(result.current.items.data).toEqual([memory])
  await act(() => result.current.pending.refresh())
  expect(result.current.pending.data).toEqual([candidate])
  expect(endpoints.managedMemories).toHaveBeenCalledTimes(1)
})

test('one slow read does not block the other; repeated refreshes reuse one in-flight request', async () => {
  const slow = deferred()
  endpoints.managedMemories.mockReturnValueOnce(slow.promise)
  const { result } = renderHook(useMemoryReads)
  await waitFor(() => expect(result.current.pending.data).toEqual([candidate]))
  act(() => { void result.current.items.refresh(); void result.current.items.refresh() })
  expect(endpoints.managedMemories).toHaveBeenCalledTimes(1)
  expect(result.current.items.loading).toBe(true)
  await act(async () => slow.resolve({ memories: [] }))
  expect(result.current.items.data).toEqual([])
})

test('failure retains a snapshot and remains visible during retry until validation succeeds', async () => {
  const { result } = renderHook(useMemoryReads)
  await waitFor(() => expect(result.current.items.data).toEqual([memory]))
  endpoints.managedMemories.mockRejectedValueOnce(new Error('private upstream body'))
  await act(() => result.current.items.refresh())
  expect(result.current.items.data).toEqual([memory])
  expect(result.current.items.error).toBe(true)
  const slow = deferred()
  endpoints.managedMemories.mockReturnValueOnce(slow.promise)
  act(() => { void result.current.items.refresh() })
  expect(result.current.items.error).toBe(true)
  await act(async () => slow.resolve({ memories: [] }))
  expect(result.current.items.error).toBe(false)
  expect(result.current.items.data).toEqual([])
})

test('write invalidation aborts old HTTP reads and prevents a late snapshot from restoring deleted data', async () => {
  const { result } = renderHook(useMemoryReads)
  await waitFor(() => expect(result.current.items.data).toEqual([memory]))
  const slow = deferred()
  endpoints.managedMemories.mockReturnValueOnce(slow.promise)
  act(() => { void result.current.items.refresh() })
  const signal = endpoints.managedMemories.mock.calls.at(-1)[0].signal
  act(() => result.current.items.commit(() => []))
  expect(signal.aborted).toBe(true)
  await act(async () => slow.resolve({ memories: [memory] }))
  expect(result.current.items.data).toEqual([])
  expect(result.current.items.loading).toBe(false)
})

test('unmount aborts both reads and refuses stale retries and commits', async () => {
  const slow = deferred()
  endpoints.managedMemories.mockReturnValueOnce(slow.promise)
  endpoints.pendingMemories.mockReturnValueOnce(slow.promise)
  const { result, unmount } = renderHook(useMemoryReads)
  const old = result.current
  const signals = [endpoints.managedMemories, endpoints.pendingMemories].map(mock => mock.mock.calls[0][0].signal)
  unmount()
  expect(signals.every(signal => signal.aborted)).toBe(true)
  await act(async () => { await old.items.refresh(); old.items.commit(() => [memory]); slow.resolve({ memories: [memory] }) })
  expect(endpoints.managedMemories).toHaveBeenCalledTimes(1)
  expect(result.current.items.data).toBeNull()
})
