import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, test, expect, beforeEach } from 'vitest'
import OperationsPage from './OperationsPage'
import { api } from '../api/client'
vi.mock('../api/client', () => ({ api: vi.fn() }))
beforeEach(() => vi.clearAllMocks())

test('operational measurements use ratio percent, IEC bytes and do not turn missing latency into zero', async () => {
  api.mockImplementation(path => Promise.resolve(path === '/admin/audit' ? [] : {
    health: {}, monitoring: { status: 'available', 'mneme:gateway_availability:rate5m': .995, 'mneme:gateway_latency_p95:rate5m': .1234 },
    capacity: { status: 'available', disk_usable_bytes: 1536, disk_total_bytes: 2048 }, storage: {},
    queue: [{ status: 'completed', total: 1234 }], task_data_status: 'available',
  }))
  render(<OperationsPage />)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('管理员凭证'), 'c'.repeat(32))
  await user.click(screen.getByRole('button', { name: '验证权限' }))
  const slo = within((await screen.findByRole('heading', { name: 'SLO · 5 分钟窗口' })).closest('section'))
  expect(slo.getByText('99.50%')).toBeVisible()
  expect(slo.getByText('0.123')).toBeVisible()
  expect(slo.getAllByText('暂无样本')).toHaveLength(2)
  expect(screen.getByText('25.0%')).toBeVisible()
  expect(screen.getByText(/1.5 KiB 可用 \/ 2 KiB 总量/)).toBeVisible()
  expect(screen.getByRole('cell', { name: '已完成', exact: true })).toBeVisible()
  expect(screen.getByRole('cell', { name: '1,234', exact: true })).toBeVisible()
})
test('requires transient credential and lock removes operational data', async () => {
  api.mockImplementation(path => Promise.resolve(path === '/admin/audit' ? [] : { checked_at: 'now', health: { mysql: 'up', redis: 'up', agent: { status: 'ready' } }, mail: { status: 'not_configured' }, model_keys: { active_version: 'v3', rotation_status: 'required', stored_versions: [{ key_version: 'legacy-v1', total: 2 }] }, storage: {}, capacity: { status: 'unavailable' }, monitoring: { status: 'not_configured' }, rate_limits: { limits: { chat: 60 } }, task_data_status: 'available' }))
  render(<OperationsPage />)
  expect(api).not.toHaveBeenCalled()
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('管理员凭证'), 'a'.repeat(32))
  await user.click(screen.getByRole('button', { name: '验证权限' }))
  expect(await screen.findByText(/未配置监控数据源/)).toBeVisible()
  expect(screen.getByText('邮件服务未配置')).toBeVisible()
  expect(screen.getByText('历史配置需要轮换')).toBeVisible()
  expect(screen.getByText('legacy-v1')).toBeVisible()
  await waitFor(() => expect(api).toHaveBeenCalledWith('/admin/operations', expect.objectContaining({ headers: { 'X-Admin-Token': 'a'.repeat(32) } })))
  await user.click(screen.getByRole('button', { name: '锁定' }))
  expect(screen.queryByText('依赖健康')).not.toBeInTheDocument()
})

function unlock(value = 'd'.repeat(32)) {
  fireEvent.change(screen.getByLabelText('管理员凭证'), { target: { value } })
  fireEvent.click(screen.getByRole('button', { name: '验证权限' }))
}
const auditSection = () => within(screen.getByRole('region', { name: '操作审计' }))
const snapshot = { health: {}, task_data_status: 'unavailable', queue: [{ task_type: 'must-not-show-partial' }] }

test('independent initial failures show no invented empty audit, and audit retries without refreshing snapshot', async () => {
  let auditCalls = 0
  api.mockImplementation(path => path === '/admin/audit'
    ? (++auditCalls === 1 ? Promise.reject(new Error('日志离线')) : Promise.resolve([]))
    : Promise.reject(new Error('运维离线')))
  render(<OperationsPage />); unlock()
  expect(screen.getByText('正在读取运维状态')).toBeVisible()
  expect(auditSection().getByText('正在读取审计记录')).toBeVisible()
  await screen.findByText('运维状态加载失败：运维离线')
  await auditSection().findByText('审计记录加载失败：日志离线')
  expect(screen.queryByText('暂无记录')).not.toBeInTheDocument()
  fireEvent.click(auditSection().getByRole('button', { name: '重试 / Retry' }))
  await auditSection().findByText('暂无记录')
  expect(api.mock.calls.filter(([path]) => path === '/admin/operations')).toHaveLength(1)
})

test('a slow snapshot never blocks successful audit data', async () => {
  let finish
  api.mockImplementation(path => path === '/admin/audit' ? Promise.resolve([{ id: 1, action: '已加载审计' }]) : new Promise(resolve => { finish = resolve }))
  render(<OperationsPage />); unlock()
  await auditSection().findByText('已加载审计')
  expect(screen.getByText('正在读取运维状态')).toBeVisible()
  await act(async () => finish(snapshot))
  expect(screen.queryByText('正在读取运维状态')).not.toBeInTheDocument()
})

test('refresh failures retain cached data with stale warnings; audit retry is independent', async () => {
  let snapshotCalls = 0, auditCalls = 0
  api.mockImplementation(path => path === '/admin/audit'
    ? (++auditCalls === 2 ? Promise.reject(new Error('日志刷新失败')) : Promise.resolve([{ id: 1, action: 'cached-action' }]))
    : (++snapshotCalls === 1 ? Promise.resolve({ ...snapshot, model_keys: { active_version: 'cached-key' } }) : Promise.reject(new Error('运维刷新失败'))))
  render(<OperationsPage />); unlock()
  await screen.findByText(/cached-key/)
  fireEvent.click(screen.getByRole('button', { name: '刷新运维状态' }))
  await screen.findByText('已有运维数据可能不是最新状态。')
  await auditSection().findByText('已有审计记录可能不是最新状态。')
  expect(screen.getByText(/cached-key/)).toBeVisible()
  expect(auditSection().getByText('cached-action')).toBeVisible()
  fireEvent.click(auditSection().getByRole('button', { name: '重试 / Retry' }))
  await waitFor(() => expect(auditSection().queryByText('已有审计记录可能不是最新状态。')).not.toBeInTheDocument())
  expect(snapshotCalls).toBe(2)
})

test('partial task queries and unavailable monitoring do not masquerade as empty successful results', async () => {
  api.mockImplementation(path => Promise.resolve(path === '/admin/audit' ? [] : snapshot))
  render(<OperationsPage />); unlock()
  await screen.findByRole('heading', { name: '任务队列' })
  const queue = within(screen.getByRole('heading', { name: '任务队列' }).closest('section'))
  expect(queue.getByText('数据不可用，请刷新运维状态重试。')).toBeVisible()
  expect(screen.queryByText('must-not-show-partial')).not.toBeInTheDocument()
  expect(screen.getByText('— / 3')).toBeVisible()
  const alerts = within(screen.getByRole('heading', { name: '告警' }).closest('section'))
  expect(alerts.queryByText('暂无记录')).not.toBeInTheDocument()
  expect(alerts.getAllByText('数据不可用，请刷新运维状态重试。')).toHaveLength(2)
  expect(screen.queryByText('邮件服务未配置')).not.toBeInTheDocument()
})

test('malformed audit response fails explicitly instead of inventing an empty list', async () => {
  api.mockImplementation(path => Promise.resolve(path === '/admin/audit' ? {} : snapshot))
  render(<OperationsPage />); unlock()
  await auditSection().findByText('审计记录加载失败：运维响应格式不正确，请重试。')
  expect(auditSection().queryByText('暂无记录')).not.toBeInTheDocument()
})

test('locking aborts both reads and late results cannot leak into a different credential scope', async () => {
  const pending = []
  api.mockImplementation((path, options) => options.headers['X-Admin-Token'] === 'e'.repeat(32)
    ? Promise.resolve(path === '/admin/audit' ? [] : snapshot)
    : new Promise(resolve => pending.push({ path, signal: options.signal, resolve })))
  render(<OperationsPage />); unlock()
  expect(pending).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: '锁定' }))
  expect(pending.every(item => item.signal.aborted)).toBe(true)
  unlock('e'.repeat(32))
  await auditSection().findByText('暂无记录')
  await act(async () => pending.forEach(item => item.resolve(item.path === '/admin/audit'
    ? [{ id: 1, action: 'secret-old-scope' }]
    : { ...snapshot, model_keys: { active_version: 'secret-old-key' } })))
  expect(screen.queryByText('secret-old-scope')).not.toBeInTheDocument()
  expect(screen.queryByText(/secret-old-key/)).not.toBeInTheDocument()
})

test('audit records paginate without hiding later entries and lock clears them', async () => {
  api.mockImplementation(path => Promise.resolve(path === '/admin/audit'
    ? Array.from({ length: 11 }, (_, i) => ({ id: i + 1, action: `audit-action-${i + 1}` }))
    : { health: {}, monitoring: {}, capacity: {}, storage: {} }))
  const user = userEvent.setup()
  render(<OperationsPage />)
  await user.type(screen.getByLabelText('管理员凭证'), 'b'.repeat(32))
  await user.click(screen.getByRole('button', { name: '验证权限' }))
  const audit = within((await screen.findByRole('heading', { name: '操作审计' })).closest('section'))
  expect(audit.getByText('audit-action-1', { exact: true })).toBeVisible()
  expect(audit.queryByText('audit-action-11', { exact: true })).not.toBeInTheDocument()
  await user.click(audit.getByRole('button', { name: '下一页' }))
  expect(audit.getByText('audit-action-11', { exact: true })).toBeVisible()
  expect(audit.getByRole('button', { name: '下一页' })).toBeDisabled()
  await user.click(audit.getByRole('button', { name: '上一页' }))
  expect(audit.getByText('audit-action-1', { exact: true })).toBeVisible()
  await user.click(screen.getByRole('button', { name: '锁定' }))
  expect(screen.queryByText('audit-action-1', { exact: true })).not.toBeInTheDocument()
})
