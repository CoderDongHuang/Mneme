import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { useSiteRecoveryData } from './useSiteRecoveryData'
vi.mock('../../api/client', () => ({ api: vi.fn() }))
beforeEach(() => vi.clearAllMocks())
const empty = { jobs: [], archives: [] }
const archives = [{ name: 'a.tar.gz', bytes: 100 }, { name: 'b.tar.gz', bytes: 200 }]
const listing = { jobs: [], archives }
const job = (status = 'queued') => ({ id: 'task-1', action: 'backup', status, created_at: '2026-11-02T00:00:00Z' })
const preview = name => ({ name, verified: true, compatible: true, sha256: 'a'.repeat(64), security: {}, metadata: {}, overwrites: ['MySQL'] })
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
const mount = () => renderHook(() => useSiteRecoveryData('a'.repeat(32)))
const loaded = hook => waitFor(() => expect(hook.result.current.history.loading).toBe(false))

test('initial failure is distinct from empty and independent retry recovers', async () => {
  const pending = deferred()
  api.mockReturnValueOnce(pending.promise).mockResolvedValue(empty)
  const hook = mount()
  expect(hook.result.current.history).toEqual({ data: null, loading: true, error: '', refresh: expect.any(Function) })
  expect(hook.result.current.blocked).toBeTruthy()
  await act(async () => pending.reject(new Error('离线')))
  expect(hook.result.current.history.data).toBeNull()
  expect(hook.result.current.history.error).toBe('离线')
  await act(async () => hook.result.current.history.refresh())
  expect(hook.result.current.history.data).toEqual(empty)
  expect(hook.result.current.blocked).toBeFalsy()
})

test.each([{}, { jobs: null, archives: [] }, { jobs: [null], archives: [] }, { jobs: [], archives: [null] }, { jobs: [{ ...job(), message: {} }], archives: [] }, { jobs: [{ ...job(), report: { rto_seconds: {} } }], archives: [] }])('rejects malformed render fields: %j', async data => {
  api.mockResolvedValue(data); const hook = mount(); await loaded(hook)
  expect(hook.result.current.history.error).toBe('整站恢复响应格式不正确，请重试。')
  expect(hook.result.current.history.data).toBeNull()
})

test('serial refresh coalesces and stale history blocks submissions including an already-open confirmation', async () => {
  const pending = deferred()
  api.mockResolvedValueOnce(listing).mockReturnValueOnce(pending.promise).mockRejectedValue(new Error('离线'))
  const hook = mount(); await loaded(hook)
  act(() => { void hook.result.current.history.refresh(); void hook.result.current.history.refresh(); void hook.result.current.history.refresh() })
  expect(api).toHaveBeenCalledTimes(2)
  await act(async () => pending.reject(new Error('离线')))
  await waitFor(() => expect(api).toHaveBeenCalledTimes(3))
  await loaded(hook)
  expect(hook.result.current.history.data).toEqual(listing)
  expect(hook.result.current.blocked).toBeTruthy()
  await expect(hook.result.current.submit('backup')).rejects.toThrow('请先刷新任务状态')
  expect(api).toHaveBeenCalledTimes(3)
})

test('archive selection owns preview and late aborted responses cannot replace the new archive', async () => {
  const old = deferred(); let oldSignal
  api.mockImplementation((path, options) => path.endsWith('/preview') ? JSON.parse(options.body).archive === 'a.tar.gz' ? (oldSignal = options.signal, old.promise) : Promise.resolve(preview('b.tar.gz')) : Promise.resolve(listing))
  const hook = mount(); await loaded(hook)
  act(() => hook.result.current.chooseArchive('a.tar.gz'))
  act(() => { void hook.result.current.verifyArchive() })
  expect(hook.result.current.preview.loading).toBe(true)
  act(() => hook.result.current.chooseArchive('b.tar.gz'))
  expect(oldSignal.aborted).toBe(true)
  await act(async () => hook.result.current.verifyArchive())
  await act(async () => old.resolve(preview('a.tar.gz')))
  expect(hook.result.current.preview.data.name).toBe('b.tar.gz')
})

test('failed revalidation clears old success, malformed preview cannot authorize restore', async () => {
  let count = 0
  api.mockImplementation(path => Promise.resolve(path.endsWith('/preview') ? ++count === 1 ? preview('a.tar.gz') : { ...preview('a.tar.gz'), compatible: false } : listing))
  const hook = mount(); await loaded(hook)
  act(() => hook.result.current.chooseArchive('a.tar.gz'))
  await act(async () => hook.result.current.verifyArchive())
  expect(hook.result.current.preview.data).not.toBeNull()
  await act(async () => hook.result.current.verifyArchive())
  expect(hook.result.current.preview.data).toBeNull()
  expect(hook.result.current.preview.error).toBeTruthy()
  await expect(hook.result.current.submit('restore')).rejects.toThrow('请先刷新任务状态')
})

test('archive removed or size changed in history invalidates prior preview', async () => {
  let data = listing
  api.mockImplementation(path => Promise.resolve(path.endsWith('/preview') ? preview('a.tar.gz') : data))
  const hook = mount(); await loaded(hook)
  for (const next of [{ jobs: [], archives: [{ name: 'a.tar.gz', bytes: 999 }] }, empty]) {
    act(() => hook.result.current.chooseArchive('a.tar.gz'))
    await act(async () => hook.result.current.verifyArchive())
    data = next
    await act(async () => hook.result.current.history.refresh())
    expect(hook.result.current.selected).toBe('')
    expect(hook.result.current.preview.data).toBeNull()
  }
})

test('accepted receipt survives failed refresh and prevents duplicates until seen in history', async () => {
  const post = deferred(); let reads = 0
  api.mockImplementation(path => path.endsWith('/jobs') ? post.promise : ++reads === 1 ? Promise.resolve(listing) : Promise.reject(new Error('历史故障')))
  const hook = mount(); await loaded(hook)
  let first, second
  act(() => { first = hook.result.current.submit('backup'); second = hook.result.current.submit('backup') })
  await expect(second).rejects.toThrow('请先刷新任务状态')
  expect(api.mock.calls.filter(([path]) => path.endsWith('/jobs'))).toHaveLength(1)
  await act(async () => { post.resolve(job()); await first })
  await loaded(hook)
  expect(hook.result.current.submission.notice).toContain('整站任务已接受：task-1')
  expect(hook.result.current.submission.error).toBe('')
  expect(hook.result.current.blocked).toBeTruthy()
  api.mockResolvedValue(empty)
  await act(async () => hook.result.current.history.refresh())
  expect(hook.result.current.blocked).toBeTruthy()
  api.mockResolvedValue({ ...empty, jobs: [job('running')] })
  await act(async () => hook.result.current.history.refresh())
  expect(hook.result.current.submission.pendingId).toBe('')
  expect(hook.result.current.blocked).toBeTruthy()
  api.mockResolvedValue({ ...empty, jobs: [job('completed')] })
  await act(async () => hook.result.current.history.refresh())
  expect(hook.result.current.blocked).toBeFalsy()
})

test('ambiguous POST remains unconfirmed, never automatically replays, requires a successful history read', async () => {
  api.mockImplementation(path => path.endsWith('/jobs') ? Promise.reject(new Error('断网')) : Promise.resolve(empty))
  const hook = mount(); await loaded(hook)
  await act(async () => { await expect(hook.result.current.submit('backup')).rejects.toThrow('断网') })
  expect(hook.result.current.submission.error).toContain('整站提交未确认')
  expect(hook.result.current.blocked).toBeTruthy()
  expect(api.mock.calls.filter(([path]) => path.endsWith('/jobs'))).toHaveLength(1)
  await act(async () => hook.result.current.history.refresh())
  expect(hook.result.current.blocked).toBeFalsy()
})

test('restore uses only the current verified archive and accepted response must match the action', async () => {
  let body
  api.mockImplementation((path, options) => {
    if (path.endsWith('/preview')) return Promise.resolve(preview('b.tar.gz'))
    if (path.endsWith('/jobs')) { body = JSON.parse(options.body); return Promise.resolve(job()) }
    return Promise.resolve(listing)
  })
  const hook = mount(); await loaded(hook)
  act(() => hook.result.current.chooseArchive('b.tar.gz'))
  await act(async () => hook.result.current.verifyArchive())
  await act(async () => { await expect(hook.result.current.submit('restore')).rejects.toThrow('整站恢复响应格式不正确') })
  expect(body).toEqual({ action: 'restore', confirmation: 'RESTORE SITE', archive: 'b.tar.gz', sha256: 'a'.repeat(64) })
  expect(hook.result.current.submission.notice).toBe('')
  expect(hook.result.current.submission.uncertain).toBe(true)
})

test('revoked permission aborts preview and clears sensitive cached data', async () => {
  const pending = deferred(); let denied = false, signal
  api.mockImplementation((path, options) => path.endsWith('/preview') ? (signal = options.signal, pending.promise) : denied ? Promise.reject(Object.assign(new Error('无权限'), { status: 403 })) : Promise.resolve(listing))
  const hook = mount(); await loaded(hook)
  act(() => hook.result.current.chooseArchive('a.tar.gz'))
  act(() => { void hook.result.current.verifyArchive() })
  denied = true
  await act(async () => hook.result.current.history.refresh())
  expect(signal.aborted).toBe(true)
  await act(async () => pending.resolve(preview('a.tar.gz')))
  expect(hook.result.current.selected).toBe('')
  expect(hook.result.current.preview.data).toBeNull()
  expect(hook.result.current.history.data).toBeNull()
})

test('unmount aborts history, preview and submission, ignoring late results', async () => {
  const pendingRead = deferred(), pendingPost = deferred(), signals = []; let reads = 0
  api.mockImplementation((path, options) => { signals.push(options.signal); return path.endsWith('/jobs') ? pendingPost.promise : ++reads === 1 ? Promise.resolve(listing) : pendingRead.promise })
  const hook = mount(); await loaded(hook)
  let posted
  act(() => { posted = hook.result.current.submit('backup'); void hook.result.current.history.refresh() })
  hook.unmount()
  expect(signals.every(signal => signal.aborted)).toBe(true)
  await act(async () => { pendingRead.resolve(listing); pendingPost.resolve(job()); await posted })
  expect(api).toHaveBeenCalledTimes(3)
})
