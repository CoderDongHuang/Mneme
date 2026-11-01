import { beforeEach, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import ProfileSessions from './ProfileSessions'
import { endpoints } from '../../api/client'

vi.mock('../../api/client', () => ({ endpoints: { authSessions: vi.fn(), revokeAuthSession: vi.fn() } }))
const records = [
  { session_id: 'first', last_seen_at: '2026-10-31T10:00:00Z', remembered: true },
  { session_id: 'second', last_seen_at: '2026-10-31T09:00:00Z', remembered: false },
]
beforeEach(() => vi.resetAllMocks())
function mount() { return render(<ProfileSessions language="zh-CN" timezone="UTC" />) }

test('pending and failed session reads never render a successful empty result; retry can recover', async () => {
  let reject
  endpoints.authSessions.mockReturnValueOnce(new Promise((resolve, fail) => { reject = fail }))
  mount()
  expect(screen.getByRole('status')).toHaveTextContent('正在读取登录会话')
  expect(screen.queryByText('暂无活动会话。')).not.toBeInTheDocument()
  await act(async () => reject(new Error('网络断开')))
  expect(screen.getByRole('alert')).toHaveTextContent('登录会话加载失败：网络断开')
  expect(screen.queryByText('暂无活动会话。')).not.toBeInTheDocument()
  endpoints.authSessions.mockResolvedValueOnce([])
  fireEvent.click(screen.getByRole('button', { name: '重试 / Retry' }))
  expect(await screen.findByText('暂无活动会话。')).toBeVisible()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('successful revocation survives refresh failure without restoring the revoked session or hiding survivors', async () => {
  endpoints.authSessions.mockResolvedValueOnce(records)
  let resolve
  endpoints.revokeAuthSession.mockReturnValueOnce(new Promise(done => { resolve = done }))
  mount()
  const button = (await screen.findAllByRole('button', { name: '撤销会话' }))[0]
  fireEvent.click(button); fireEvent.click(button)
  expect(endpoints.revokeAuthSession).toHaveBeenCalledTimes(1)
  expect(button).toBeDisabled()
  endpoints.authSessions.mockRejectedValueOnce(new Error('刷新失败'))
  await act(async () => resolve({}))
  expect(await screen.findByRole('alert')).toHaveTextContent('刷新失败')
  expect(screen.getByText('会话已撤销')).toBeVisible()
  expect(screen.queryByText('长期登录')).not.toBeInTheDocument()
  expect(screen.getByText('普通登录')).toBeVisible()
  expect(screen.getByText('已有会话记录可能不是最新状态。')).toBeVisible()
  expect(screen.queryByText('暂无活动会话。')).not.toBeInTheDocument()
  endpoints.authSessions.mockResolvedValueOnce([records[1]])
  fireEvent.click(screen.getByRole('button', { name: '重试 / Retry' }))
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  expect(screen.getByRole('button', { name: '撤销会话' })).toBeEnabled()
})

test('failed revocation leaves the session available for a deliberate retry', async () => {
  endpoints.authSessions.mockResolvedValueOnce([records[0]])
  endpoints.revokeAuthSession.mockRejectedValueOnce(new Error('撤销失败'))
  mount()
  fireEvent.click(await screen.findByRole('button', { name: '撤销会话' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('撤销失败')
  expect(screen.getByText('长期登录')).toBeVisible()
  expect(screen.queryByText('会话已撤销')).not.toBeInTheDocument()
  expect(endpoints.authSessions).toHaveBeenCalledTimes(1)
  endpoints.revokeAuthSession.mockResolvedValueOnce({})
  endpoints.authSessions.mockResolvedValueOnce([])
  fireEvent.click(screen.getByRole('button', { name: '撤销会话' }))
  expect(await screen.findByText('暂无活动会话。')).toBeVisible()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('a late response from an unmounted security panel cannot overwrite the new panel', async () => {
  let resolve
  endpoints.authSessions.mockReturnValueOnce(new Promise(done => { resolve = done }))
  const previous = mount()
  previous.unmount()
  endpoints.authSessions.mockResolvedValueOnce([])
  mount()
  expect(await screen.findByText('暂无活动会话。')).toBeVisible()
  await act(async () => resolve(records))
  expect(screen.getByText('暂无活动会话。')).toBeVisible()
  expect(screen.queryByRole('button', { name: '撤销会话' })).not.toBeInTheDocument()
})
