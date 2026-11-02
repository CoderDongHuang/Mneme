import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { expect, test, vi, beforeEach } from 'vitest'
import InfrastructureDiagnostics from './InfrastructureDiagnostics'
import { api } from '../../api/client'
vi.mock('../../api/client', () => ({ api: vi.fn() }))
beforeEach(() => vi.clearAllMocks())
const passed = { configuration: 'present', connection: 'passed', operation: 'passed', cleanup: 'passed', code: 'OK', checked_at: '2026-11-03T00:00:00Z' }

test('diagnostics are explicit and duplicate actions share one in-flight request', async () => {
  let finish
  api.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  render(<InfrastructureDiagnostics token="transient-admin-token" />)
  expect(api).not.toHaveBeenCalled()
  const button = screen.getByRole('button', { name: '检查 MySQL' })
  fireEvent.click(button); fireEvent.click(button)
  expect(api).toHaveBeenCalledTimes(1)
  expect(api).toHaveBeenCalledWith('/admin/operations/check/mysql', expect.objectContaining({ method: 'POST', headers: { 'X-Admin-Token': 'transient-admin-token' } }))
  expect(button).toBeDisabled()
  await act(async () => finish(passed))
  expect(within(button.closest('tr')).getAllByText('通过')).toHaveLength(3)
  expect(button).toBeEnabled()
})

test('unknown results clear previous success, never retry and never display raw exceptions', async () => {
  api.mockResolvedValueOnce(passed).mockRejectedValueOnce(new Error('private-password-smtp-recipient'))
  render(<InfrastructureDiagnostics token="secret" />)
  const button = screen.getByRole('button', { name: '检查 Redis' })
  fireEvent.click(button)
  await screen.findByText('业务操作及清理已通过')
  fireEvent.click(button)
  await screen.findByText('未取得诊断结果，操作可能已执行。请确认服务状态后再手动检查。')
  expect(screen.queryByText('业务操作及清理已通过')).not.toBeInTheDocument()
  expect(screen.queryByText(/private-password/)).not.toBeInTheDocument()
  expect(api).toHaveBeenCalledTimes(2)
})

test('locking/unmount aborts requests and rejects late responses', async () => {
  let finish
  api.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const view = render(<InfrastructureDiagnostics token="old" />)
  fireEvent.click(screen.getByRole('button', { name: '发送测试邮件' }))
  const signal = api.mock.calls[0][1].signal
  view.unmount()
  expect(signal.aborted).toBe(true)
  render(<InfrastructureDiagnostics token="new" />)
  await act(async () => finish({ ...passed, code: 'SMTP_ACCEPTED' }))
  expect(screen.queryByText('SMTP 已接收，请在自己的邮箱确认收信')).not.toBeInTheDocument()
  expect(api).toHaveBeenCalledTimes(1)
})

test('malformed payload never invents successful stages', async () => {
  api.mockResolvedValue({ ...passed, operation: 'anything', code: '<password>' })
  render(<InfrastructureDiagnostics token="secret" />)
  fireEvent.click(screen.getByRole('button', { name: '检查 备份密钥' }))
  await screen.findByText('未取得诊断结果，操作可能已执行。请确认服务状态后再手动检查。')
  expect(screen.queryByText('<password>')).not.toBeInTheDocument()
})
