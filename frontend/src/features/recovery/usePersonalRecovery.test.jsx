import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { endpoints } from '../../api/client'
import { usePersonalRecovery } from './usePersonalRecovery'
vi.mock('../../api/client', () => ({ endpoints: { previewArchive: vi.fn(), importArchive: vi.fn() } }))
beforeEach(() => vi.clearAllMocks())
const file = new File(['zip'], 'a.zip'), other = new File(['other'], 'b.zip')
const preview = (selected = file, scope = 'all') => ({ compatible: true, mode: 'additive', overwritten: 0, scope,
  bytes: selected.size, version: 1, created_at: 'unknown', encrypted: false, sha256: 'a'.repeat(64),
  counts: { knowledge_bases: 1 }, missing_files: 0, same_name_libraries: [] })
const restored = { status: 'imported', message: 'restored', workspace: { counts: { knowledge_bases: 1 } }, documents: { restored: 0, skipped: 0 } }
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
const mount = () => { const hook = renderHook(usePersonalRecovery); act(() => hook.result.current.chooseFile(file)); return hook }
async function confirmed(hook) {
  endpoints.previewArchive.mockResolvedValue(preview())
  await act(async () => hook.result.current.verify())
  act(() => hook.result.current.confirm())
  act(() => hook.result.current.setConfirmation('RESTORE MY DATA'))
}

test('revalidation removes old success immediately and failed checks cannot authorize restore', async () => {
  const hook = mount(); await confirmed(hook)
  act(() => hook.result.current.back())
  const pending = deferred(); endpoints.previewArchive.mockReturnValue(pending.promise)
  act(() => { void hook.result.current.verify() })
  expect(hook.result.current.preview).toBeNull(); expect(hook.result.current.step).toBe(1)
  await act(async () => pending.reject(new Error('offline')))
  expect(hook.result.current.error).toBe('offline')
  act(() => hook.result.current.confirm())
  await act(async () => hook.result.current.restore())
  expect(endpoints.importArchive).not.toHaveBeenCalled()
})

test.each([
  {}, { counts: null }, { counts: { plans: {} } }, { same_name_libraries: [{}] }, { scope: 'learning' },
  { compatible: false }, { sha256: 'bad' }, { bytes: 99 },
])('rejects invalid preview render/authorization fields: %j', async invalid => {
  const hook = mount(); endpoints.previewArchive.mockResolvedValue({ ...preview(), ...invalid, ...(Object.keys(invalid).length ? {} : { version: null }) })
  await act(async () => hook.result.current.verify())
  expect(hook.result.current.preview).toBeNull(); expect(hook.result.current.error).toContain('响应格式不正确')
})

test('file and scope changes cancel preview and late responses cannot affect the new selection', async () => {
  const pending = deferred(); let signal
  endpoints.previewArchive.mockImplementation((selected, scope, options) => {
    if (selected === file) { signal = options.signal; return pending.promise }
    return Promise.resolve(preview(selected, scope))
  })
  const hook = mount(); act(() => { void hook.result.current.verify() })
  act(() => hook.result.current.chooseFile(other))
  expect(signal.aborted).toBe(true)
  act(() => hook.result.current.chooseScope('knowledge'))
  await act(async () => hook.result.current.verify())
  await act(async () => pending.resolve(preview()))
  expect(hook.result.current.file).toBe(other)
  expect(hook.result.current.preview.scope).toBe('knowledge')
  expect(hook.result.current.preview.bytes).toBe(other.size)
})

test('restore requires explicit confirmation, uses checked hash, and synchronously prevents duplicate POST', async () => {
  const pending = deferred(), hook = mount(); await confirmed(hook)
  act(() => hook.result.current.setConfirmation('wrong'))
  await act(async () => hook.result.current.restore())
  expect(endpoints.importArchive).not.toHaveBeenCalled()
  act(() => hook.result.current.setConfirmation('RESTORE MY DATA'))
  endpoints.importArchive.mockReturnValue(pending.promise)
  let request
  act(() => { request = hook.result.current.restore(); void hook.result.current.restore(); hook.result.current.chooseFile(other); hook.result.current.reset() })
  expect(endpoints.importArchive).toHaveBeenCalledTimes(1)
  expect(endpoints.importArchive).toHaveBeenCalledWith(file, 'all', 'a'.repeat(64), { signal: expect.any(AbortSignal) })
  await act(async () => { pending.resolve(restored); await request })
  expect(hook.result.current.step).toBe(4)
  expect(hook.result.current.preview).toBeNull()
  expect(hook.result.current.result).toEqual(restored)
})

test.each([null, { ...restored, documents: {} }, { ...restored, workspace: { counts: { plans: {} } } }, new Error('connection lost')])('unknown POST outcome blocks replay and requires explicit inspection: %j', async response => {
  const hook = mount(); await confirmed(hook)
  endpoints.importArchive.mockImplementation(() => response instanceof Error ? Promise.reject(response) : Promise.resolve(response))
  await act(async () => hook.result.current.restore())
  expect(hook.result.current.uncertain).toBe(true)
  expect(hook.result.current.result).toBeNull(); expect(hook.result.current.preview).toBeNull()
  act(() => hook.result.current.setConfirmation('RESTORE MY DATA'))
  await act(async () => { await hook.result.current.restore(); await hook.result.current.verify() })
  expect(endpoints.importArchive).toHaveBeenCalledTimes(1)
  expect(endpoints.previewArchive).toHaveBeenCalledTimes(1)
  act(() => hook.result.current.reset())
  expect(hook.result.current.file).toBeNull(); expect(hook.result.current.uncertain).toBe(false)
  expect(hook.result.current.step).toBe(1)
})

test('unmount cancels preview and import even if the transport returns late', async () => {
  for (const phase of ['preview', 'restore']) {
    const hook = mount(), pending = deferred(); let signal, request
    if (phase === 'restore') await confirmed(hook)
    endpoints[phase === 'preview' ? 'previewArchive' : 'importArchive'].mockImplementation((...args) => {
      signal = args.at(-1).signal; return pending.promise
    })
    act(() => { request = hook.result.current[phase === 'preview' ? 'verify' : 'restore']() })
    hook.unmount(); expect(signal.aborted).toBe(true)
    await act(async () => { pending.resolve(phase === 'preview' ? preview() : restored); await request })
  }
})

test('oversize files fail locally without sending an archive and reset clears the selected file', async () => {
  const hook = mount(), large = new File(['x'], 'large.zip')
  Object.defineProperty(large, 'size', { value: 50 * 1024 * 1024 + 1 })
  act(() => hook.result.current.chooseFile(large))
  await act(async () => hook.result.current.verify())
  expect(endpoints.previewArchive).not.toHaveBeenCalled()
  expect(hook.result.current.error).toContain('50 MiB')
  act(() => hook.result.current.reset())
  expect(hook.result.current.file).toBeNull()
})
