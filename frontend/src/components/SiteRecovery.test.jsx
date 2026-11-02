import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import SiteRecovery from './SiteRecovery'
import { api } from '../api/client'
vi.mock('../api/client', () => ({ api: vi.fn() }))
beforeEach(() => vi.clearAllMocks())
const listing = { jobs: [], archives: [{ name: 'a.tar.gz', bytes: 100 }] }
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }

test('initial failure never shows empty history; stale cached results disable actions and recover', async () => {
  let failure = true
  api.mockImplementation(() => failure ? Promise.reject(new Error('断网')) : Promise.resolve(listing))
  render(<SiteRecovery token={'a'.repeat(32)} />)
  await screen.findByText('整站任务加载失败：断网')
  expect(screen.queryByText('暂无整站操作记录。')).not.toBeInTheDocument()
  failure = false; fireEvent.click(screen.getByRole('button', { name: '重试 / Retry' }))
  await screen.findByText('暂无整站操作记录。')
  failure = true; fireEvent.click(screen.getByRole('button', { name: '刷新任务状态' }))
  await screen.findByText('已有整站数据可能不是最新状态，操作已暂停。')
  expect(screen.getByRole('button', { name: '创建整站备份' })).toBeDisabled()
  expect(screen.getByLabelText('选择整站归档')).toBeDisabled()
  expect(screen.queryByText('暂无整站操作记录。')).not.toBeInTheDocument()
})

test('changing the credential unmounts previews and ignores an aborted late response', async () => {
  const pending = deferred(); let signal
  api.mockImplementation((path, options) => path.endsWith('/preview') ? (signal = options.signal, pending.promise) : Promise.resolve(listing))
  const view = render(<SiteRecovery token={'a'.repeat(32)} />)
  await screen.findByText('暂无整站操作记录。')
  fireEvent.change(screen.getByLabelText('选择整站归档'), { target: { value: 'a.tar.gz' } })
  fireEvent.click(screen.getByRole('button', { name: '验证完整性与兼容性' }))
  expect(screen.getByText('正在校验所选归档')).toBeVisible()
  view.rerender(<SiteRecovery token={'b'.repeat(32)} />)
  await screen.findByText('暂无整站操作记录。')
  expect(signal.aborted).toBe(true)
  await act(async () => pending.resolve({ name: 'a.tar.gz', verified: true, compatible: true, sha256: 'a'.repeat(64), security: {}, metadata: {}, overwrites: [] }))
  expect(screen.queryByText('整站恢复预览')).not.toBeInTheDocument()
  expect(screen.getByLabelText('选择整站归档')).toHaveValue('')
})

test('a confirmation opened before a history failure cannot submit', async () => {
  api.mockResolvedValue(listing)
  render(<SiteRecovery token={'a'.repeat(32)} />)
  await screen.findByText('暂无整站操作记录。')
  fireEvent.click(screen.getByRole('button', { name: '创建整站备份' }))
  const dialog = within(screen.getByRole('dialog'))
  fireEvent.change(dialog.getByRole('textbox'), { target: { value: 'BACKUP SITE' } })
  api.mockRejectedValue(new Error('断网'))
  // Programmatic event represents a scheduled poll while the modal is open.
  fireEvent.click(screen.getByRole('button', { name: '刷新任务状态', hidden: true }))
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2))
  fireEvent.click(dialog.getByRole('button', { name: '创建整站备份' }))
  await dialog.findByText('请先刷新任务状态并完成当前归档校验。')
  expect(api.mock.calls.some(([path]) => path.endsWith('/jobs'))).toBe(false)
})
