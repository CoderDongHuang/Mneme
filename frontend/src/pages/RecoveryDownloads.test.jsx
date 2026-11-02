import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'
import RecoveryPage from './RecoveryPage'
import { downloadWorkspaceArchive } from '../api/client'
const auth = vi.hoisted(() => ({ session: { userId: 1 }, isAdmin: false }))
vi.mock('../state/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../api/client', () => ({ downloadWorkspaceArchive: vi.fn() }))
vi.mock('./PersonalRecovery', () => ({ default: () => <div>personal wizard</div> }))
vi.mock('../components/RecoveryDrill', () => ({ default: () => null }))
beforeEach(() => { vi.clearAllMocks(); auth.session = { userId: 1 } })
const view = () => <MemoryRouter><RecoveryPage /></MemoryRouter>
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }

test('download is synchronized and success adds exactly one history row', async () => {
  const pending = deferred(); downloadWorkspaceArchive.mockReturnValueOnce(pending.promise).mockResolvedValue({ bytes: 100 })
  render(view())
  const button = screen.getByRole('button', { name: '下载个人归档' })
  fireEvent.click(button); fireEvent.click(button)
  expect(downloadWorkspaceArchive).toHaveBeenCalledTimes(1)
  await act(async () => pending.resolve({ bytes: 100 }))
  fireEvent.click(screen.getByRole('button', { name: '个人备份', exact: true }))
  expect(screen.getByRole('table')).toHaveTextContent('下载已发起')
  expect(screen.getAllByRole('row')).toHaveLength(2)
})

test('failed download shows its error, adds no history and can be retried', async () => {
  downloadWorkspaceArchive.mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ bytes: 100 })
  render(view())
  fireEvent.click(screen.getByRole('button', { name: '下载个人归档' }))
  await screen.findByText('offline')
  expect(screen.queryByText('下载已发起')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '下载个人归档' }))
  await screen.findByText('下载已发起')
  expect(screen.queryByText('offline')).not.toBeInTheDocument()
})

test('account changes abort downloads, reset history, and ignore late results', async () => {
  const pending = deferred(); downloadWorkspaceArchive.mockReturnValue(pending.promise)
  const rendered = render(view())
  fireEvent.click(screen.getByRole('button', { name: '下载个人归档' }))
  const signal = downloadWorkspaceArchive.mock.calls[0][0].signal
  auth.session = { userId: 2 }; rendered.rerender(view())
  expect(signal.aborted).toBe(true)
  await act(async () => pending.resolve({ bytes: 100 }))
  fireEvent.click(screen.getByRole('button', { name: '个人备份', exact: true }))
  expect(screen.getByText('本次访问尚未创建个人备份')).toBeVisible()
  expect(screen.queryByText('下载已发起')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '下载个人归档' }))
  const next = downloadWorkspaceArchive.mock.calls[1][0].signal
  rendered.unmount(); expect(next.aborted).toBe(true)
})
