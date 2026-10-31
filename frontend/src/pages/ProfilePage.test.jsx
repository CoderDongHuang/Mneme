import { beforeEach, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ProfilePage from './ProfilePage'
import { endpoints } from '../api/client'

vi.mock('../api/client', () => ({ endpoints: {
  profile: vi.fn(), authSessions: vi.fn(), updateProfile: vi.fn(),
  requestEmailVerification: vi.fn(), confirmEmailVerification: vi.fn(),
} }))
vi.mock('../state/AuthContext', () => ({ useAuth: () => ({ updateSession: vi.fn(), logout: vi.fn() }) }))
vi.mock('../state/PreferencesContext', () => {
  const preferences = { language: 'zh-CN', timezone: 'UTC', theme: 'system' }
  return { usePreferences: () => ({ preferences, save: vi.fn() }) }
})
const profile = { username: 'qa', nickname: 'QA', email: 'qa@example.test', emailVerified: false }
beforeEach(() => {
  vi.clearAllMocks()
  endpoints.profile.mockResolvedValue({ ...profile })
  endpoints.authSessions.mockResolvedValue([])
})
function mount() { return render(<MemoryRouter><ProfilePage /></MemoryRouter>) }

test('email edits must be saved, changing email clears verification, and removal hides verification actions', async () => {
  endpoints.profile.mockResolvedValueOnce({ ...profile, emailVerified: true })
  mount()
  expect(await screen.findByText('当前邮箱已验证，可用于找回密码。')).toBeVisible()
  fireEvent.change(screen.getByLabelText('绑定邮箱'), { target: { value: 'new@example.test' } })
  expect(screen.getByText('邮箱有未保存的修改，请先保存资料。')).toBeVisible()
  expect(screen.queryByRole('button', { name: '发送邮箱验证码' })).not.toBeInTheDocument()
  endpoints.updateProfile.mockResolvedValueOnce({ ...profile, email: 'new@example.test' })
  fireEvent.click(screen.getByRole('button', { name: '保存资料' }))
  expect(await screen.findByRole('button', { name: '发送邮箱验证码' })).toBeEnabled()
  expect(endpoints.updateProfile).toHaveBeenCalledWith({ nickname: 'QA', email: 'new@example.test' })
  fireEvent.change(screen.getByLabelText('绑定邮箱'), { target: { value: '' } })
  endpoints.updateProfile.mockResolvedValueOnce({ ...profile, email: null })
  fireEvent.click(screen.getByRole('button', { name: '保存资料' }))
  await waitFor(() => expect(screen.getByLabelText('绑定邮箱')).toHaveValue(''))
  expect(screen.queryByRole('button', { name: '发送邮箱验证码' })).not.toBeInTheDocument()
})

test('delivery failure stays unverified, pending operations cannot double submit, and successful confirmation clears the secret', async () => {
  mount()
  const send = await screen.findByRole('button', { name: '发送邮箱验证码' })
  endpoints.requestEmailVerification.mockRejectedValueOnce(new Error('邮件服务未配置'))
  fireEvent.click(send)
  expect(await screen.findByText('邮件服务未配置')).toBeVisible()
  expect(screen.getByText('当前邮箱尚未验证，不能用于找回密码。')).toBeVisible()
  let release
  endpoints.requestEmailVerification.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
  fireEvent.click(send); fireEvent.click(send)
  expect(send).toBeDisabled()
  expect(endpoints.requestEmailVerification).toHaveBeenCalledTimes(2)
  await act(async () => release({ expiresInSeconds: 900 }))
  expect(await screen.findByRole('button', { name: '重新发送验证码' })).toBeEnabled()
  const code = screen.getByLabelText('邮箱验证码')
  fireEvent.change(code, { target: { value: 'a'.repeat(64) } })
  endpoints.confirmEmailVerification.mockRejectedValueOnce(new Error('邮箱验证码无效或已过期'))
  fireEvent.click(screen.getByRole('button', { name: '验证邮箱', exact: true }))
  expect(await screen.findByText('邮箱验证码无效或已过期')).toBeVisible()
  expect(screen.getByLabelText('邮箱验证码')).toHaveValue('a'.repeat(64))
  endpoints.confirmEmailVerification.mockResolvedValueOnce({ ...profile, emailVerified: true })
  fireEvent.click(screen.getByRole('button', { name: '验证邮箱', exact: true }))
  expect(await screen.findByText('当前邮箱已验证，可用于找回密码。')).toBeVisible()
  expect(screen.queryByLabelText('邮箱验证码')).not.toBeInTheDocument()
})
