import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import useUploadQueue from './useUploadQueue'
import { endpoints } from '../api/client'
vi.mock('../api/client', () => ({ endpoints: { uploadDocument: vi.fn() } }))
beforeEach(() => { vi.resetAllMocks(); localStorage.clear() })

test('one failed file does not stop the batch, retry only sends that file to its original library', async () => {
  endpoints.uploadDocument.mockResolvedValueOnce({ id: 1 }).mockRejectedValueOnce(new Error('文件损坏')).mockResolvedValueOnce({ id: 3 })
  const onSubmitted = vi.fn()
  const { result } = renderHook(() => useUploadQueue('queue.1', onSubmitted))
  const files = ['a.txt', 'b.txt', 'c.txt'].map(name => new File([name], name))
  await act(async () => result.current.upload(files, 7))
  expect(result.current.queue.map(item => item.status)).toEqual(['submitted', 'failed', 'submitted'])
  expect(onSubmitted.mock.calls).toEqual([[7, { id: 1 }], [7, { id: 3 }]])
  endpoints.uploadDocument.mockResolvedValue({ id: 2 })
  await act(async () => result.current.retry(result.current.queue[1]))
  expect(endpoints.uploadDocument).toHaveBeenLastCalledWith(7, files[1])
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
  act(() => result.current.cancel(result.current.queue[1]))
  await act(async () => { resolve({ id: 1 }); await batch })
  expect(endpoints.uploadDocument).toHaveBeenCalledTimes(1)
  expect(result.current.queue.map(item => item.status)).toEqual(['submitted', 'cancelled'])
})

test('reload marks interrupted work as cancelled and keeps queues scoped by user', () => {
  localStorage.setItem('queue.1', JSON.stringify([{ id: 'a', kbId: 1, name: 'secret.txt', status: 'uploading' }]))
  const first = renderHook(() => useUploadQueue('queue.1', vi.fn()))
  expect(first.result.current.queue[0].status).toBe('cancelled')
  const second = renderHook(() => useUploadQueue('queue.2', vi.fn()))
  expect(second.result.current.queue).toEqual([])
})
