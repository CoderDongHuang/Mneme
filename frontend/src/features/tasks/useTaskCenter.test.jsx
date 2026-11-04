import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import useTaskCenter from './useTaskCenter'
import { endpoints, openNotificationStream } from '../../api/client'

vi.mock('../../api/client', () => ({
  endpoints: { tasks: vi.fn(), operations: vi.fn(), cancelTask: vi.fn(), retryTask: vi.fn() },
  openNotificationStream: vi.fn(() => ({ close: vi.fn() })),
}))
const task = { task_id: 't1', task_type: 'document_ingest', status: 'failed', file_name: 'qa.txt', attempt_count: 3, max_attempts: 3 }
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
beforeEach(() => {
  vi.clearAllMocks()
  endpoints.tasks.mockResolvedValue([task])
  endpoints.operations.mockResolvedValue([])
  endpoints.retryTask.mockResolvedValue({ task_id: 't1', status: 'retry' })
})

test('a slow task read does not block activity and independent activity retry', async () => {
  const pending = deferred()
  endpoints.tasks.mockReturnValue(pending.promise)
  endpoints.operations.mockRejectedValueOnce(new Error('private path'))
  const { result } = renderHook(useTaskCenter)
  await waitFor(() => expect(result.current.logs.error).toContain('阶段记录加载失败'))
  expect(result.current.tasks.loading).toBe(true)
  await act(() => result.current.logs.refresh())
  expect(result.current.logs.data).toEqual([])
  expect(endpoints.tasks).toHaveBeenCalledTimes(1)
  await act(async () => pending.resolve([task]))
  expect(result.current.tasks.data).toEqual([task])
})

test.each([
  null, {}, [null], [{ ...task, file_name: {} }], [{ ...task, status: [] }],
  [{ ...task, attempt_count: '3' }], [task, task],
])('malformed task responses become a recoverable error, not empty success: %j', async value => {
  endpoints.tasks.mockResolvedValueOnce(value)
  const { result } = renderHook(useTaskCenter)
  await waitFor(() => expect(result.current.tasks.error).toContain('任务列表加载失败'))
  expect(result.current.tasks.data).toBeNull()
  await act(() => result.current.tasks.refresh())
  expect(result.current.tasks.data).toEqual([task])
  expect(result.current.tasks.error).toBe('')
})

test('malformed activity retains last successful snapshot and does not block current task actions', async () => {
  const { result } = renderHook(useTaskCenter)
  await waitFor(() => expect(result.current.logs.data).toEqual([]))
  endpoints.operations.mockResolvedValueOnce([{ operation_id: 't1', status: 'failed', step: {} }])
  await act(() => result.current.logs.refresh())
  expect(result.current.logs.error).toContain('阶段记录加载失败')
  expect(result.current.logs.data).toEqual([])
  await act(() => result.current.act(task, 'retry'))
  expect(endpoints.retryTask).toHaveBeenCalledTimes(1)
})

test('stale task data remains visible but cannot be mutated, including while its retry is pending', async () => {
  const { result } = renderHook(useTaskCenter)
  await waitFor(() => expect(result.current.tasks.data).toEqual([task]))
  endpoints.tasks.mockRejectedValueOnce(new Error('offline'))
  await act(() => result.current.tasks.refresh())
  const pending = deferred()
  endpoints.tasks.mockReturnValueOnce(pending.promise)
  act(() => { void result.current.tasks.refresh() })
  await act(() => result.current.act(task, 'retry'))
  expect(endpoints.retryTask).not.toHaveBeenCalled()
  expect(result.current.tasks.data).toEqual([task])
  expect(result.current.tasks.error).not.toBe('')
  await act(async () => pending.resolve([task]))
  expect(result.current.tasks.error).toBe('')
})

test('write receipt survives failed refresh, duplicate clicks and reads never resend the write', async () => {
  const pending = deferred()
  const { result } = renderHook(useTaskCenter)
  await waitFor(() => expect(result.current.tasks.data).toEqual([task]))
  endpoints.retryTask.mockReturnValueOnce(pending.promise)
  endpoints.tasks.mockRejectedValue(new Error('offline'))
  let submitted
  act(() => { submitted = result.current.act(task, 'retry'); void result.current.act(task, 'retry') })
  expect(endpoints.retryTask).toHaveBeenCalledTimes(1)
  await act(async () => { pending.resolve({ task_id: 't1', status: 'retry' }); await submitted })
  await waitFor(() => expect(result.current.tasks.error).not.toBe(''))
  expect(result.current.notice).toContain('重试已提交')
  expect(result.current.error).toBe('')
  await act(() => result.current.tasks.refresh())
  expect(endpoints.retryTask).toHaveBeenCalledTimes(1)
  expect(result.current.notice).toContain('重试已提交')
})

test('an in-flight pre-mutation read cannot publish an obsolete task after acceptance', async () => {
  const { result } = renderHook(useTaskCenter)
  await waitFor(() => expect(result.current.tasks.data).toEqual([task]))
  const submitted = deferred(), oldRead = deferred(), latest = deferred()
  endpoints.retryTask.mockReturnValueOnce(submitted.promise)
  let action
  act(() => { action = result.current.act(task, 'retry') })
  endpoints.tasks.mockReturnValueOnce(oldRead.promise).mockReturnValueOnce(latest.promise)
  act(() => { void result.current.tasks.refresh() })
  await act(async () => { submitted.resolve({ task_id: 't1', status: 'retry' }); await action })
  await act(async () => oldRead.resolve([{ ...task, status: 'completed' }]))
  expect(result.current.tasks.loading).toBe(true)
  expect(result.current.tasks.data[0].status).toBe('failed')
  await act(async () => latest.resolve([{ ...task, status: 'retry' }]))
  expect(result.current.tasks.data[0].status).toBe('retry')
})

test('invalid acceptance is not presented as success or automatically retried', async () => {
  endpoints.retryTask.mockResolvedValueOnce({ status: 'completed' })
  const { result } = renderHook(useTaskCenter)
  await waitFor(() => expect(result.current.tasks.data).toEqual([task]))
  await act(() => result.current.act(task, 'retry'))
  expect(result.current.notice).toBe('')
  expect(result.current.error).toContain('提交结果未确认')
  expect(endpoints.retryTask).toHaveBeenCalledTimes(1)
})

test('unmount aborts both reads, closes notifications and prevents late write acceptance', async () => {
  const pending = deferred()
  endpoints.retryTask.mockReturnValueOnce(pending.promise)
  const { result, unmount } = renderHook(useTaskCenter)
  await waitFor(() => expect(result.current.tasks.data).toEqual([task]))
  let action
  act(() => { action = result.current.act(task, 'retry') })
  unmount()
  for (const read of [endpoints.tasks, endpoints.operations]) expect(read.mock.calls[0][0].signal.aborted).toBe(true)
  expect(endpoints.retryTask.mock.calls[0][1].signal.aborted).toBe(true)
  expect(openNotificationStream.mock.results[0].value.close).toHaveBeenCalledOnce()
  let id
  await act(async () => { pending.resolve({ task_id: 't1', status: 'retry' }); id = await action })
  expect(id).toBeUndefined()
  expect(endpoints.tasks).toHaveBeenCalledTimes(1)
})
