import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import useUploadQueue from './useUploadQueue'
import { endpoints } from '../api/client'
vi.mock('../api/client', () => ({ endpoints: { uploadDocument: vi.fn(), cancelUpload: vi.fn() } }))
beforeEach(() => { vi.resetAllMocks(); localStorage.clear(); endpoints.cancelUpload.mockResolvedValue({ status: 'cancelled' }) })

test('one failed file does not stop the batch, retry only sends that file to its original library', async () => {
  endpoints.uploadDocument.mockResolvedValueOnce({ id: 1 }).mockRejectedValueOnce(new Error('文件损坏')).mockResolvedValueOnce({ id: 3 })
  const onSubmitted = vi.fn()
  const { result } = renderHook(() => useUploadQueue('queue.1', onSubmitted))
  const files = ['a.txt', 'b.txt', 'c.txt'].map(name => new File([name], name))
  await act(async () => result.current.upload(files, 7))
  expect(result.current.queue.map(item => item.status)).toEqual(['submitted', 'failed', 'submitted'])
  expect(onSubmitted.mock.calls).toEqual([[7, { id: 1, fileName: 'a.txt' }], [7, { id: 3, fileName: 'c.txt' }]])
  endpoints.uploadDocument.mockResolvedValue({ id: 2 })
  await act(async () => result.current.retry(result.current.queue[1]))
  expect(endpoints.uploadDocument).toHaveBeenLastCalledWith(7, files[1], { signal: expect.any(AbortSignal), requestId: expect.any(String) })
  expect(endpoints.uploadDocument.mock.calls[1][2].requestId).not.toBe(endpoints.uploadDocument.mock.calls[3][2].requestId)
  expect(endpoints.uploadDocument).toHaveBeenCalledTimes(4)
  expect(result.current.queue.every(item => item.status === 'submitted')).toBe(true)
})

test('duplicate entry or batch is blocked during submission and pending files can be cancelled', async () => {
  let resolve
  endpoints.uploadDocument.mockImplementation(() => new Promise(r => { resolve = r }))
  const { result } = renderHook(() => useUploadQueue('queue.1', vi.fn()))
  const a = new File(['a'], 'a.txt'); const b = new File(['b'], 'b.txt')
  let batch
  act(() => { batch = result.current.upload([a, a, b], 4) })
  await waitFor(() => expect(result.current.queue).toHaveLength(2))
  await act(async () => result.current.upload([a], 5))
  await act(async () => result.current.cancel(result.current.queue[1]))
  await act(async () => { resolve({ id: 1 }); await batch })
  expect(endpoints.uploadDocument).toHaveBeenCalledTimes(1)
  expect(result.current.queue.map(item => item.status)).toEqual(['submitted', 'cancelled'])
})

test('reload preserves unknown submission outcome and keeps queues scoped by user', () => {
  localStorage.setItem('queue.1', JSON.stringify([{ id: 'a', kbId: 1, name: 'secret.txt', status: 'uploading' }]))
  const first = renderHook(() => useUploadQueue('queue.1', vi.fn()))
  expect(first.result.current.queue[0].status).toBe('uncertain')
  const second = renderHook(() => useUploadQueue('queue.2', vi.fn()))
  expect(second.result.current.queue).toEqual([])
})

test('in-flight abort confirms cancellation and continues other files with independent signals', async () => {
  let signal
  endpoints.uploadDocument.mockImplementationOnce((kb, file, options) => new Promise((resolve, reject) => {
    signal = options.signal
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  })).mockResolvedValueOnce({ id: 2 })
  const { result } = renderHook(() => useUploadQueue('queue.1', vi.fn()))
  let batch
  act(() => { batch = result.current.upload([new File(['a'], 'large.txt'), new File(['b'], 'next.txt')], 7) })
  const id = result.current.queue[0].id
  await act(async () => { await result.current.cancel(result.current.queue[0]); await batch })
  expect(signal.aborted).toBe(true)
  expect(endpoints.cancelUpload).toHaveBeenCalledWith(7, id)
  expect(result.current.queue.map(item => item.status)).toEqual(['cancelled', 'submitted'])
  expect(endpoints.uploadDocument.mock.calls[1][2].signal.aborted).toBe(false)
})

test('abort after server commit remains submitted and cannot cancel the parsing task', async () => {
  endpoints.uploadDocument.mockImplementation((kb, file, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  endpoints.cancelUpload.mockResolvedValue({ status: 'submitted', document_id: 42, task_id: 'task_42' })
  const onSubmitted = vi.fn()
  const { result } = renderHook(() => useUploadQueue('queue.1', onSubmitted))
  let batch
  act(() => { batch = result.current.upload([new File(['a'], 'committed.txt')], 7) })
  await act(async () => { await result.current.cancel(result.current.queue[0]); await batch })
  expect(result.current.queue[0]).toMatchObject({ status: 'submitted', documentId: 42, taskId: 'task_42' })
  expect(onSubmitted).toHaveBeenCalledWith(7, expect.objectContaining({ id: 42, fileName: 'committed.txt' }))
  await act(async () => result.current.cancel(result.current.queue[0]))
  expect(endpoints.cancelUpload).toHaveBeenCalledTimes(1)
})

test('lost upload and confirmation responses never claim cancellation and can reconcile after reload', async () => {
  endpoints.uploadDocument.mockRejectedValue(new Error('connection lost'))
  endpoints.cancelUpload.mockRejectedValueOnce(new Error('offline'))
  const first = renderHook(() => useUploadQueue('queue.1', vi.fn()))
  await act(async () => first.result.current.upload([new File(['a'], 'unknown.txt')], 7))
  expect(first.result.current.queue[0].status).toBe('uncertain')
  first.unmount()
  const second = renderHook(() => useUploadQueue('queue.1', vi.fn()))
  endpoints.cancelUpload.mockResolvedValue({ status: 'submitted', document_id: 9, task_id: 'task_9' })
  await act(async () => second.result.current.cancel(second.result.current.queue[0]))
  expect(second.result.current.queue[0].status).toBe('submitted')
  expect(endpoints.uploadDocument).toHaveBeenCalledTimes(1)
})

test('unmount leaves in-flight submission intact, cancels waiting entries and persists the receipt', async () => {
  let resolve
  endpoints.uploadDocument.mockImplementation(() => new Promise(r => { resolve = r }))
  const callback = vi.fn()
  const hook = renderHook(() => useUploadQueue('queue.1', callback))
  let batch
  act(() => { batch = hook.result.current.upload([new File(['a'], 'a.txt'), new File(['b'], 'b.txt')], 7) })
  const signal = endpoints.uploadDocument.mock.calls[0][2].signal
  hook.unmount()
  await act(async () => { resolve({ id: 1 }); await batch })
  expect(signal.aborted).toBe(false)
  expect(callback).not.toHaveBeenCalled()
  expect(endpoints.uploadDocument).toHaveBeenCalledTimes(1)
  expect(JSON.parse(localStorage.getItem('queue.1')).map(item => item.status)).toEqual(['submitted', 'cancelled'])
})

test('switching users resets the queue and a late response cannot write into the new user scope', async () => {
  let resolve
  endpoints.uploadDocument.mockImplementationOnce(() => new Promise(r => { resolve = r })).mockResolvedValueOnce({ id: 2 })
  const callback = vi.fn()
  const hook = renderHook(({ user }) => useUploadQueue(`queue.${user}`, callback), { initialProps: { user: 1 } })
  let first
  act(() => { first = hook.result.current.upload([new File(['secret'], 'secret.txt')], 7) })
  hook.rerender({ user: 2 })
  expect(hook.result.current.queue).toEqual([])
  await act(async () => hook.result.current.upload([new File(['new'], 'new.txt')], 8))
  await act(async () => { resolve({ id: 1 }); await first })
  expect(hook.result.current.queue.map(item => item.name)).toEqual(['new.txt'])
  expect(JSON.parse(localStorage.getItem('queue.2')).map(item => item.name)).toEqual(['new.txt'])
  expect(callback).toHaveBeenCalledTimes(1)
  expect(callback).toHaveBeenCalledWith(8, expect.objectContaining({ id: 2 }))
})
