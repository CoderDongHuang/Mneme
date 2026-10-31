import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, test, expect } from 'vitest'
import OperationsPage from './OperationsPage'
import { api } from '../api/client'
vi.mock('../api/client', () => ({ api: vi.fn() }))
test('requires transient credential and lock removes operational data', async () => {
  api.mockResolvedValue({ checked_at: 'now', health: { mysql: 'up', redis: 'up', agent: { status: 'ready' } }, storage: {}, capacity: { status: 'unavailable' }, monitoring: { status: 'not_configured' }, rate_limits: { limits: { chat: 60 } }, task_data_status: 'available' })
  render(<OperationsPage />)
  expect(api).not.toHaveBeenCalled()
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('管理员凭证'), 'a'.repeat(32))
  await user.click(screen.getByRole('button', { name: '验证权限' }))
  expect(await screen.findByText(/未配置监控数据源/)).toBeVisible()
  expect(screen.getByText('邮件服务未配置')).toBeVisible()
  await waitFor(() => expect(api).toHaveBeenCalledWith('/admin/operations', expect.objectContaining({ headers: { 'X-Admin-Token': 'a'.repeat(32) } })))
  await user.click(screen.getByRole('button', { name: '锁定' }))
  expect(screen.queryByText('依赖健康')).not.toBeInTheDocument()
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
