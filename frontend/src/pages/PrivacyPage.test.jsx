import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import PrivacyPage from './PrivacyPage'
import { api, endpoints } from '../api/client'

vi.mock('../api/client', () => ({ api: vi.fn(), endpoints: { operations: vi.fn() },
  downloadWorkspaceArchive: vi.fn(), downloadWorkspaceExport: vi.fn() }))
vi.mock('../state/AuthContext', () => ({ useAuth: () => ({ logout: vi.fn() }) }))
const policy = { providers: ['真实供应商'], sending_scope: ['必要上下文'], cloud_allowed: true, trace_days: 7, trace_max_days: 30 }
const log = { operation_id: 'a', operation_type: 'privacy_policy', step: 'saved', status: 'completed', created_at: '2026-11-01T00:00:00Z' }
beforeEach(() => { vi.resetAllMocks(); api.mockResolvedValue({ ...policy }); endpoints.operations.mockResolvedValue([]) })
function mount() { return render(<MemoryRouter><PrivacyPage /></MemoryRouter>) }
function operations() { return screen.getByRole('region', { name: '审计记录' }) }

test('saves revoked consent and confirms trace deletion', async () => {
  api.mockResolvedValue({ cloud_allowed: true, trace_days: 30, trace_max_days: 30, providers: ['DeepSeek'], sending_scope: ['对话'] })
  mount()
  const user = userEvent.setup()
  await user.click(await screen.findByLabelText('允许外部模型处理'))
  await user.click(screen.getByRole('button', { name: '保存策略' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('/privacy', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ cloud_allowed: false, trace_days: 30 }) })))
  expect(screen.getByRole('button', { name: '删除我的 Trace' })).toBeDisabled()
  await user.type(screen.getByLabelText('删除确认'), 'DELETE TRACES')
  await user.click(screen.getByRole('button', { name: '删除我的 Trace' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('/privacy/traces?confirmation=DELETE%20TRACES', { method: 'DELETE' }))
})

test('independent initial outages have retry and never invent an empty history; exports stay available', async () => {
  api.mockRejectedValueOnce(new Error('策略离线'))
  endpoints.operations.mockRejectedValueOnce(new Error('日志离线'))
  mount()
  expect(screen.getByText('正在读取隐私策略')).toBeVisible()
  expect(screen.getByText('正在读取审计记录')).toBeVisible()
  await screen.findByText('隐私策略加载失败：策略离线')
  await within(operations()).findByText('审计记录加载失败：日志离线')
  expect(screen.queryByText('暂无记录')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '导出数据' })).toBeEnabled()
  fireEvent.click(within(operations()).getByRole('button', { name: '重试 / Retry' }))
  await within(operations()).findByText('暂无记录')
  expect(api).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole('button', { name: '重试 / Retry' }))
  await screen.findByLabelText('Trace 保留天数')
  expect(endpoints.operations).toHaveBeenCalledTimes(2)
})

test('history retry preserves unsaved policy and confirmation; a successful write stays successful when history refresh fails', async () => {
  endpoints.operations.mockRejectedValueOnce(new Error('日志离线')).mockResolvedValueOnce([log]).mockRejectedValueOnce(new Error('日志刷新失败'))
  mount()
  const days = await screen.findByLabelText('Trace 保留天数')
  fireEvent.change(days, { target: { value: '14' } })
  fireEvent.change(screen.getByLabelText('删除确认'), { target: { value: '尚未提交的确认' } })
  await within(operations()).findByText('审计记录加载失败：日志离线')
  fireEvent.click(within(operations()).getByRole('button', { name: '重试 / Retry' }))
  await within(operations()).findByText('privacy_policy')
  expect(days).toHaveValue(14)
  expect(screen.getByLabelText('删除确认')).toHaveValue('尚未提交的确认')
  api.mockResolvedValueOnce({ ...policy, trace_days: 14 })
  fireEvent.click(screen.getByRole('button', { name: '保存策略' }))
  await screen.findByText('策略保存完成')
  await within(operations()).findByText('审计记录加载失败：日志刷新失败')
  expect(within(operations()).getByText('已有审计记录可能不是最新状态。')).toBeVisible()
  expect(within(operations()).getByText('privacy_policy')).toBeVisible()
  expect(screen.queryByText('暂无记录')).not.toBeInTheDocument()
  expect(JSON.parse(api.mock.calls[1][1].body)).toEqual({ cloud_allowed: true, trace_days: 14 })
  fireEvent.click(within(operations()).getByRole('button', { name: '重试 / Retry' }))
  await within(operations()).findByText('暂无记录')
  expect(screen.getByText('策略保存完成')).toBeVisible()
  expect(api).toHaveBeenCalledTimes(2)
})

test('failed writes retain drafts and allow retry; double clicks cannot send another write', async () => {
  mount()
  const days = await screen.findByLabelText('Trace 保留天数')
  fireEvent.change(days, { target: { value: '15' } })
  api.mockRejectedValueOnce(new Error('写入失败'))
  const save = screen.getByRole('button', { name: '保存策略' })
  fireEvent.click(save)
  await screen.findByText('写入失败')
  expect(days).toHaveValue(15)
  expect(endpoints.operations).toHaveBeenCalledOnce()
  let release
  api.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
  fireEvent.click(save); fireEvent.click(save)
  expect(save).toBeDisabled()
  expect(days).toBeDisabled()
  expect(api).toHaveBeenCalledTimes(3)
  await act(async () => release({ ...policy, trace_days: 15 }))
  await screen.findByText('策略保存完成')
  expect(save).toBeEnabled()
})

test('trace deletion receipt and cleared confirmation survive a failed audit read', async () => {
  endpoints.operations.mockResolvedValueOnce([log]).mockRejectedValueOnce(new Error('日志离线'))
  mount()
  await screen.findByLabelText('Trace 保留天数')
  fireEvent.change(screen.getByLabelText('删除确认'), { target: { value: 'DELETE TRACES' } })
  fireEvent.click(screen.getByRole('button', { name: '删除我的 Trace' }))
  await screen.findByText('Trace 删除完成')
  await within(operations()).findByText('审计记录加载失败：日志离线')
  expect(screen.getByLabelText('删除确认')).toHaveValue('')
  expect(api).toHaveBeenLastCalledWith('/privacy/traces?confirmation=DELETE%20TRACES', { method: 'DELETE' })
})

test('late policy and history replies after unmount cannot populate a new page', async () => {
  let releasePolicy, releaseLogs
  api.mockReturnValueOnce(new Promise(resolve => { releasePolicy = resolve }))
  endpoints.operations.mockReturnValueOnce(new Promise(resolve => { releaseLogs = resolve }))
  const view = mount(); view.unmount(); mount()
  await screen.findByLabelText('Trace 保留天数')
  await within(operations()).findByText('暂无记录')
  await act(async () => { releasePolicy({ ...policy, trace_days: 29 }); releaseLogs([log]) })
  expect(screen.getByLabelText('Trace 保留天数')).toHaveValue(7)
  expect(within(operations()).queryByText('privacy_policy')).not.toBeInTheDocument()
})
