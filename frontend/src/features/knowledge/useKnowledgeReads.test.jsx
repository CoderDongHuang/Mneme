import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import useKnowledgeReads from './useKnowledgeReads'
import { endpoints, openNotificationStream } from '../../api/client'

vi.mock('../../api/client', () => ({
  endpoints: { knowledgeBases: vi.fn(), documents: vi.fn(), notifications: vi.fn() },
  openNotificationStream: vi.fn(() => ({ close: vi.fn() })),
}))
const base = { id: 1, name: 'Library A' }
const document = { id: 7, fileName: 'qa.txt', status: 'ready', chunkCount: 2 }
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
beforeEach(() => {
  vi.resetAllMocks()
  openNotificationStream.mockReturnValue({ close: vi.fn() })
  endpoints.knowledgeBases.mockResolvedValue([base, { id: 2, name: 'Library B' }])
  endpoints.documents.mockResolvedValue([document])
  endpoints.notifications.mockResolvedValue([])
})

test.each([null, {}, [null], [base, base], [{ ...base, name: {} }], [{ ...base, id: '1' }]])(
  'invalid library response does not become an empty success: %j', async value => {
    endpoints.knowledgeBases.mockResolvedValueOnce(value)
    const { result } = renderHook(useKnowledgeReads)
    await waitFor(() => expect(result.current.bases.error).toContain('资料库加载失败'))
    expect(result.current.bases.data).toBeNull()
    expect(endpoints.documents).not.toHaveBeenCalled()
    await act(() => result.current.bases.refresh())
    await waitFor(() => expect(result.current.documents.data).toEqual([document]))
    expect(result.current.bases.error).toBe('')
  })

test.each([null, {}, [document, document], [{ ...document, fileName: null }], [{ ...document, status: [] }],
  [{ ...document, updatedAt: {} }], [{ ...document, parseReport: {} }], [{ ...document, chunkCount: -1 }]])(
  'invalid document fields become recoverable read errors: %j', async value => {
    endpoints.documents.mockResolvedValueOnce(value)
    const { result } = renderHook(useKnowledgeReads)
    await waitFor(() => expect(result.current.documents.error).toContain('文档列表加载失败'))
    expect(result.current.documents.data).toBeNull()
    await act(() => result.current.documents.refresh())
    expect(result.current.documents.data).toEqual([document])
  })

test('read failures retain cached documents, clear on successful retry and do not expose raw errors', async () => {
  const { result } = renderHook(useKnowledgeReads)
  await waitFor(() => expect(result.current.documents.data).toEqual([document]))
  endpoints.documents.mockRejectedValueOnce(new Error('PRIVATE_SERVICE_BODY'))
  await act(() => result.current.documents.refresh())
  expect(result.current.documents.data).toEqual([document])
  expect(result.current.documents.error).toContain('文档列表加载失败')
  expect(result.current.documents.error).not.toContain('PRIVATE')
  const pending = deferred()
  endpoints.documents.mockReturnValueOnce(pending.promise)
  act(() => { void result.current.documents.refresh() })
  expect(result.current.documents.loading).toBe(true)
  expect(result.current.documents.error).not.toBe('')
  await act(async () => pending.resolve([]))
  expect(result.current.documents.data).toEqual([])
  expect(result.current.documents.error).toBe('')
})

test('switching aborts old library requests and immediately hides their cached data', async () => {
  const pending = deferred()
  endpoints.documents.mockImplementation(library => library === 1 ? pending.promise : Promise.resolve([]))
  const { result } = renderHook(useKnowledgeReads)
  await waitFor(() => expect(endpoints.documents).toHaveBeenCalledTimes(1))
  const oldSignal = endpoints.documents.mock.calls[0][1].signal
  act(() => result.current.selectKb(2))
  expect(result.current.documents.data).toBeNull()
  expect(oldSignal.aborted).toBe(true)
  await waitFor(() => expect(result.current.documents.data).toEqual([]))
  await act(async () => pending.resolve([document]))
  expect(result.current.documents.data).toEqual([])
  expect(result.current.activeKbId).toBe(2)
})

test('slow reads coalesce notifications without concurrent requests or blocking activity', async () => {
  const pending = deferred()
  endpoints.documents.mockReturnValueOnce(pending.promise)
  const { result } = renderHook(useKnowledgeReads)
  await waitFor(() => expect(endpoints.documents).toHaveBeenCalledTimes(1))
  const notify = openNotificationStream.mock.calls[0][0]
  act(() => { notify(); notify(); notify() })
  expect(endpoints.documents).toHaveBeenCalledTimes(1)
  await waitFor(() => expect(result.current.notifications.data).toEqual([]))
  await act(async () => pending.resolve([document]))
  await waitFor(() => expect(endpoints.documents).toHaveBeenCalledTimes(2))
  expect(result.current.documents.data).toEqual([document])
})

test('a local write receipt invalidates older reads and queues a single new GET', async () => {
  const { result } = renderHook(useKnowledgeReads)
  await waitFor(() => expect(result.current.documents.data).toEqual([document]))
  const old = deferred(), next = deferred()
  endpoints.documents.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise)
  act(() => { void result.current.documents.refresh() })
  act(() => result.current.documents.commit(items => items.map(item => ({ ...item, status: 'deleting' }))))
  expect(result.current.documents.data[0].status).toBe('deleting')
  await act(async () => old.resolve([document]))
  expect(result.current.documents.data[0].status).toBe('deleting')
  await act(async () => next.resolve([]))
  expect(result.current.documents.data).toEqual([])
  expect(endpoints.documents).toHaveBeenCalledTimes(3)
})

test('library refresh preserves the selection and task history permits multiple transitions', async () => {
  const event = { task_id: 'task-1', status: 'completed', file_name: 'qa.txt' }
  endpoints.notifications.mockResolvedValue([event, { ...event, status: 'processing' }])
  const { result } = renderHook(useKnowledgeReads)
  await waitFor(() => expect(result.current.documents.data).toEqual([document]))
  act(() => result.current.selectKb(2))
  await act(() => result.current.bases.refresh())
  expect(result.current.activeKbId).toBe(2)
  expect(result.current.notifications.data).toHaveLength(2)
  endpoints.notifications.mockResolvedValueOnce([{ ...event, file_name: {} }])
  await act(() => result.current.notifications.refresh())
  expect(result.current.notifications.error).toContain('最近活动加载失败')
  expect(result.current.documents.error).toBe('')
})

test('a delayed write receipt for the previous library cannot change the new library', async () => {
  const { result } = renderHook(useKnowledgeReads)
  await waitFor(() => expect(result.current.documents.data).toEqual([document]))
  const oldCommit = result.current.documents.commit
  act(() => result.current.selectKb(2))
  await waitFor(() => expect(endpoints.documents).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(result.current.documents.loading).toBe(false))
  act(() => oldCommit(() => []))
  expect(result.current.documents.data).toEqual([document])
  expect(result.current.documents.loading).toBe(false)
  expect(endpoints.documents).toHaveBeenCalledTimes(2)
})

test('unmount aborts all reads, closes notifications and ignores delayed results', async () => {
  const pending = deferred()
  endpoints.documents.mockReturnValue(pending.promise)
  const { result, unmount } = renderHook(useKnowledgeReads)
  await waitFor(() => expect(endpoints.documents).toHaveBeenCalledTimes(1))
  const signals = [endpoints.documents, endpoints.notifications, endpoints.knowledgeBases].map(mock => mock.mock.calls[0].at(-1).signal)
  unmount()
  expect(signals.every(signal => signal.aborted)).toBe(true)
  expect(openNotificationStream.mock.results[0].value.close).toHaveBeenCalledTimes(1)
  await act(async () => pending.resolve([document]))
  expect(result.current.documents.data).toBeNull()
})
