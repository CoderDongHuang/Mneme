import { render, screen, waitFor } from '@testing-library/react'
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
  await user.type(screen.getByLabelText('管理员凭证'), 'admin-token')
  await user.click(screen.getByRole('button', { name: '验证权限' }))
  expect(await screen.findByText(/未配置监控数据源/)).toBeVisible()
  await waitFor(() => expect(api).toHaveBeenCalledWith('/admin/operations', { headers: { 'X-Admin-Token': 'admin-token' } }))
  await user.click(screen.getByRole('button', { name: '锁定' }))
  expect(screen.queryByText('依赖健康')).not.toBeInTheDocument()
})
