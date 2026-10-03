import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import RecoveryPage from './RecoveryPage'
import { api } from '../api/client'
vi.mock('../api/client', () => ({ api: vi.fn() }))
test('requires credential and explicit isolation confirmation before dispatch', async () => {
  api.mockResolvedValue({ runs: [] })
  render(<RecoveryPage />)
  expect(api).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('管理员凭证'), { target: { value: 'a'.repeat(32) } })
  fireEvent.click(screen.getByRole('button', { name: '验证权限' }))
  const button = await screen.findByRole('button', { name: '发起演练' })
  expect(button).toBeDisabled()
  fireEvent.change(screen.getByLabelText('确认语句'), { target: { value: 'ISOLATED DRILL' } })
  fireEvent.click(button)
  await screen.findByText('已提交隔离演练，请等待 GitHub 分配运行编号')
  expect(api).toHaveBeenCalledWith('/admin/recovery', expect.objectContaining({ method: 'POST', body: JSON.stringify({ confirmation: 'ISOLATED DRILL' }) }))
  fireEvent.click(screen.getByRole('button', { name: '锁定' }))
  expect(screen.queryByRole('button', { name: '发起演练' })).not.toBeInTheDocument()
})
