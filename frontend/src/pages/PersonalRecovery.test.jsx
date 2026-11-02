import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'
import PersonalRecovery from './PersonalRecovery'
import { endpoints } from '../api/client'
vi.mock('../api/client', () => ({ endpoints: { previewArchive: vi.fn(), importArchive: vi.fn() } }))
beforeEach(() => vi.clearAllMocks())
const file = new File(['zip'], 'a.zip')
const preview = { compatible: true, mode: 'additive', overwritten: 0, scope: 'all', bytes: 3, version: 1,
  created_at: 'unknown', encrypted: false, sha256: 'a'.repeat(64), counts: { plans: 1 }, missing_files: 0, same_name_libraries: [] }
const mount = () => render(<MemoryRouter><PersonalRecovery /></MemoryRouter>)

test('rejected revalidation removes success and restores selection step', async () => {
  endpoints.previewArchive.mockResolvedValueOnce(preview).mockRejectedValueOnce(new Error('offline'))
  mount(); fireEvent.change(screen.getByLabelText('个人归档 ZIP（最多 50 MiB）'), { target: { files: [file] } })
  fireEvent.click(screen.getByRole('button', { name: '验证清单与文件完整性' }))
  await screen.findByText('清单及现有文件哈希校验通过')
  fireEvent.click(screen.getByRole('button', { name: '验证清单与文件完整性' }))
  await screen.findByText('offline')
  expect(screen.queryByText('清单及现有文件哈希校验通过')).not.toBeInTheDocument()
  expect(screen.getByText('选择归档与范围').closest('li')).toHaveAttribute('aria-current', 'step')
})

test('unconfirmed outcome disables replay, inspection links and explicit reset clear file and confirmation', async () => {
  endpoints.previewArchive.mockResolvedValue(preview); endpoints.importArchive.mockRejectedValue(new Error('offline'))
  mount(); fireEvent.change(screen.getByLabelText('个人归档 ZIP（最多 50 MiB）'), { target: { files: [file] } })
  fireEvent.click(screen.getByRole('button', { name: '验证清单与文件完整性' }))
  fireEvent.click(await screen.findByRole('button', { name: '继续确认' }))
  fireEvent.change(screen.getByLabelText('输入 RESTORE MY DATA 确认新增副本'), { target: { value: 'RESTORE MY DATA' } })
  fireEvent.click(screen.getByRole('button', { name: '执行个人恢复' }))
  await screen.findByText(/个人恢复结果未确认/)
  expect(screen.getByRole('button', { name: '执行个人恢复' })).toBeDisabled()
  expect(screen.getByRole('link', { name: '打开文件并验证内容' })).toHaveAttribute('href', '/knowledge')
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '已核实结果，重新选择归档' })))
  expect(screen.getByLabelText('个人归档 ZIP（最多 50 MiB）')).toHaveValue('')
  expect(screen.getByRole('button', { name: '验证清单与文件完整性' })).toBeDisabled()
  expect(endpoints.importArchive).toHaveBeenCalledTimes(1)
})
