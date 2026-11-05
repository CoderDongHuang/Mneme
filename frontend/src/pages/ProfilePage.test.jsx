import { beforeEach, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ProfilePage from './ProfilePage'
import { endpoints } from '../api/client'

vi.mock('../api/client', () => ({ endpoints: {
  profile: vi.fn(), authSessions: vi.fn(), updateProfile: vi.fn(),
  requestEmailVerification: vi.fn(), confirmEmailVerification: vi.fn(),
  uploadAvatar: vi.fn(), avatarUrl: () => '/avatar', changePassword: vi.fn(),
} }))
const auth = vi.hoisted(() => ({ session: { userId: 1, username: 'qa' }, updateSession: vi.fn(), logout: vi.fn() }))
vi.mock('../state/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../state/PreferencesContext', () => {
  const preferences = { language: 'zh-CN', timezone: 'UTC', theme: 'system' }
  return { usePreferences: () => ({ preferences, save: vi.fn() }) }
})
const profile = { username: 'qa', nickname: 'QA', email: 'qa@example.test', emailVerified: false }
beforeEach(() => {
  vi.resetAllMocks()
  auth.session = { userId: 1, username: 'qa' }
  endpoints.profile.mockResolvedValue({ ...profile })
  endpoints.authSessions.mockResolvedValue([])
})

test.each([null, {}, { ...profile, nickname: {} }, { ...profile, emailVerified: 'yes' }, { ...profile, username: 'other' }])('invalid or foreign profile data is a recoverable read error: %j', async value => {
  endpoints.profile.mockResolvedValueOnce(value)
  mount()
  expect(await screen.findByRole('alert')).toHaveTextContent('个人资料响应格式不正确')
  expect(screen.queryByLabelText('昵称')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '重试 / Retry' }))
  expect(await screen.findByLabelText('昵称')).toHaveValue('QA')
  expect(endpoints.updateProfile).not.toHaveBeenCalled()
})

test.each(['invalid', 'lost', 'mismatch'])('uncertain profile save preserves draft and only reconciles by GET: %s', async mode => {
  mount()
  fireEvent.change(await screen.findByLabelText('昵称'), { target: { value: '草稿昵称' } })
  if (mode === 'lost') endpoints.updateProfile.mockRejectedValueOnce(new Error('connection lost'))
  else endpoints.updateProfile.mockResolvedValueOnce(mode === 'invalid' ? { ...profile, nickname: {} } : profile)
  fireEvent.click(screen.getByRole('button', { name: '保存资料' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('资料操作结果尚未确认，请先核对服务端资料。')
  expect(screen.getByLabelText('昵称')).toHaveValue('草稿昵称')
  expect(screen.getByRole('button', { name: '保存资料' })).toBeDisabled()
  expect(auth.updateSession).not.toHaveBeenCalled()
  endpoints.profile.mockRejectedValueOnce(new Error('read unavailable'))
  fireEvent.click(screen.getByRole('button', { name: '核对已保存资料' }))
  expect(await screen.findByText('read unavailable')).toBeVisible()
  expect(screen.getByRole('button', { name: '保存资料' })).toBeDisabled()
  endpoints.profile.mockResolvedValueOnce({ ...profile, nickname: '服务端昵称' })
  fireEvent.click(screen.getByRole('button', { name: '核对已保存资料' }))
  expect(await screen.findByText('服务端昵称', { selector: 'dd' })).toBeVisible()
  expect(screen.getByLabelText('昵称')).toHaveValue('草稿昵称')
  fireEvent.click(screen.getByRole('button', { name: '保留草稿，继续编辑' }))
  expect(screen.getByLabelText('昵称')).toHaveValue('草稿昵称')
  expect(screen.getByRole('button', { name: '保存资料' })).toBeEnabled()
  expect(auth.updateSession).toHaveBeenCalledWith(expect.objectContaining({ nickname: '服务端昵称' }))
  expect(endpoints.updateProfile).toHaveBeenCalledTimes(1)
})

test('adopting a verified server snapshot discards the draft without replaying a write', async () => {
  mount()
  fireEvent.change(await screen.findByLabelText('昵称'), { target: { value: '草稿' } })
  endpoints.updateProfile.mockResolvedValueOnce(null)
  fireEvent.click(screen.getByRole('button', { name: '保存资料' }))
  await screen.findByText('资料操作结果尚未确认，请先核对服务端资料。')
  endpoints.profile.mockResolvedValueOnce({ ...profile, nickname: '已保存' })
  fireEvent.click(screen.getByRole('button', { name: '核对已保存资料' }))
  fireEvent.click(await screen.findByRole('button', { name: '采用服务端资料' }))
  expect(screen.getByLabelText('昵称')).toHaveValue('已保存')
  expect(endpoints.updateProfile).toHaveBeenCalledTimes(1)
})

test('late save from the previous account cannot update the new login or form', async () => {
  let release
  endpoints.updateProfile.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
  const view = mount()
  await screen.findByLabelText('昵称')
  fireEvent.click(screen.getByRole('button', { name: '保存资料' }))
  auth.session = { userId: 2, username: 'other' }
  endpoints.profile.mockResolvedValueOnce({ ...profile, username: 'other', nickname: '另一账号' })
  view.rerender(<MemoryRouter><ProfilePage /></MemoryRouter>)
  expect(await screen.findByLabelText('昵称')).toHaveValue('另一账号')
  await act(async () => release({ ...profile, nickname: 'previous' }))
  expect(screen.getByLabelText('昵称')).toHaveValue('另一账号')
  expect(auth.updateSession).not.toHaveBeenCalled()
  expect(screen.queryByText('个人资料已保存')).not.toBeInTheDocument()
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
  expect(endpoints.updateProfile).toHaveBeenCalledWith({ nickname: 'QA', email: 'new@example.test' }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  fireEvent.change(screen.getByLabelText('绑定邮箱'), { target: { value: '' } })
  endpoints.updateProfile.mockResolvedValueOnce({ ...profile, email: null })
  fireEvent.click(screen.getByRole('button', { name: '保存资料' }))
  await waitFor(() => expect(screen.getByLabelText('绑定邮箱')).toHaveValue(''))
  expect(screen.queryByRole('button', { name: '发送邮箱验证码' })).not.toBeInTheDocument()
})

test('delivery failure stays unverified, pending operations cannot double submit, and successful confirmation clears the secret', async () => {
  mount()
  const send = await screen.findByRole('button', { name: '发送邮箱验证码' })
  endpoints.requestEmailVerification.mockRejectedValueOnce(Object.assign(new Error('邮件服务未配置'), { status: 400 }))
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
  endpoints.confirmEmailVerification.mockRejectedValueOnce(Object.assign(new Error('邮箱验证码无效或已过期'), { status: 400 }))
  fireEvent.click(screen.getByRole('button', { name: '验证邮箱', exact: true }))
  expect(await screen.findByText('邮箱验证码无效或已过期')).toBeVisible()
  expect(screen.getByLabelText('邮箱验证码')).toHaveValue('a'.repeat(64))
  endpoints.confirmEmailVerification.mockResolvedValueOnce({ ...profile, emailVerified: true })
  fireEvent.click(screen.getByRole('button', { name: '验证邮箱', exact: true }))
  expect(await screen.findByText('当前邮箱已验证，可用于找回密码。')).toBeVisible()
  expect(screen.queryByLabelText('邮箱验证码')).not.toBeInTheDocument()
})

test('initial profile failure has its own retry and does not load or invent an empty session list', async () => {
  endpoints.profile.mockRejectedValueOnce(new Error('无法连接服务'))
  const view = mount()
  expect(screen.getByRole('status')).toHaveTextContent('正在读取用户资料')
  expect(await screen.findByRole('alert')).toHaveTextContent('无法连接服务')
  expect(screen.queryByText('暂无活动会话。')).not.toBeInTheDocument()
  expect(endpoints.authSessions).not.toHaveBeenCalled()
  let resolve
  endpoints.profile.mockReturnValueOnce(new Promise(done => { resolve = done }))
  fireEvent.click(screen.getByRole('button', { name: '重试 / Retry' }))
  expect(screen.getByRole('status')).toHaveTextContent('正在读取用户资料')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  await act(async () => resolve({ ...profile }))
  expect(await screen.findByLabelText('昵称')).toHaveValue('QA')
  expect(endpoints.profile).toHaveBeenCalledTimes(2)
  view.unmount()
})

test('session outage stays within security and does not discard a profile draft or claim no sessions', async () => {
  endpoints.authSessions.mockRejectedValueOnce(new Error('会话服务不可用'))
  mount()
  fireEvent.change(await screen.findByLabelText('昵称'), { target: { value: '未保存的昵称' } })
  fireEvent.click(screen.getByRole('button', { name: '账户安全', exact: true }))
  expect(await screen.findByRole('alert')).toHaveTextContent('登录会话加载失败：会话服务不可用')
  expect(screen.queryByText('暂无活动会话。')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '基本资料', exact: true }))
  expect(screen.getByLabelText('昵称')).toHaveValue('未保存的昵称')
  expect(endpoints.profile).toHaveBeenCalledTimes(1)
})

test.each([null, {}, { ...profile, userId: 2 }, { ...profile, hasAvatar: 'yes' }])('avatar response must belong to this account and cannot claim success: %j', async value => {
  endpoints.uploadAvatar.mockResolvedValueOnce(value)
  const view = mount()
  await screen.findByLabelText('昵称')
  fireEvent.change(view.container.querySelector('input[type=file]'), { target: { files: [new File(['image'], 'avatar.png', { type: 'image/png' })] } })
  expect(await screen.findByRole('alert')).toHaveTextContent('资料操作结果尚未确认')
  expect(screen.queryByText('头像已更新')).not.toBeInTheDocument()
  expect(auth.updateSession).not.toHaveBeenCalled()
  expect(endpoints.uploadAvatar).toHaveBeenCalledTimes(1)
})

test('valid avatar receipt refreshes both local and shared avatar caches', async () => {
  endpoints.uploadAvatar.mockResolvedValueOnce({ ...profile, hasAvatar: true })
  const view = mount()
  await screen.findByLabelText('昵称')
  fireEvent.change(view.container.querySelector('input[type=file]'), { target: { files: [new File(['image'], 'avatar.png', { type: 'image/png' })] } })
  expect(await screen.findByText('头像已更新')).toBeVisible()
  expect(screen.getByAltText('当前头像').getAttribute('src')).toMatch(/^\/avatar\?v=\d+$/)
  expect(auth.updateSession).toHaveBeenCalledWith(expect.objectContaining({ hasAvatar: true, avatarVersion: expect.any(Number) }))
})

test.each([null, {}, { expiresInSeconds: '900' }, { expiresInSeconds: 900, resendAfterSeconds: 0 }])('invalid email send receipt cannot claim delivery or be automatically retried: %j', async value => {
  endpoints.requestEmailVerification.mockResolvedValueOnce(value)
  mount()
  fireEvent.click(await screen.findByRole('button', { name: '发送邮箱验证码' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('资料操作结果尚未确认')
  expect(screen.queryByText(/验证邮件已提交至邮件服务器/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '发送邮箱验证码' })).toBeDisabled()
  expect(endpoints.requestEmailVerification).toHaveBeenCalledTimes(1)
})

test('unverified confirmation is not accepted, and a late reconciliation cannot contaminate the next account', async () => {
  endpoints.confirmEmailVerification.mockResolvedValueOnce(profile)
  const view = mount()
  fireEvent.change(await screen.findByLabelText('邮箱验证码'), { target: { value: 'a'.repeat(64) } })
  fireEvent.click(screen.getByRole('button', { name: '验证邮箱', exact: true }))
  expect(await screen.findByRole('alert')).toHaveTextContent('资料操作结果尚未确认')
  expect(screen.getByLabelText('邮箱验证码')).toHaveValue('a'.repeat(64))
  let release
  endpoints.profile.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
  fireEvent.click(screen.getByRole('button', { name: '核对已保存资料' }))
  auth.session = { userId: 2, username: 'other' }
  endpoints.profile.mockResolvedValueOnce({ ...profile, username: 'other', nickname: '新账号' })
  view.rerender(<MemoryRouter><ProfilePage /></MemoryRouter>)
  expect(await screen.findByLabelText('昵称')).toHaveValue('新账号')
  await act(async () => release({ ...profile, emailVerified: true }))
  expect(screen.getByLabelText('昵称')).toHaveValue('新账号')
  expect(screen.queryByText('已验证', { selector: 'dd' })).not.toBeInTheDocument()
  expect(auth.updateSession).not.toHaveBeenCalled()
})

test('a password completion from the previous account cannot log out the next account', async () => {
  let release
  endpoints.changePassword.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
  const view = mount()
  await screen.findByLabelText('昵称')
  fireEvent.click(screen.getByRole('button', { name: '账户安全', exact: true }))
  fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'Password1!' } })
  fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'Password2!' } })
  fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'Password2!' } })
  fireEvent.click(screen.getByRole('button', { name: '确认修改', exact: true }))
  auth.session = { userId: 2, username: 'other' }
  endpoints.profile.mockResolvedValueOnce({ ...profile, username: 'other', nickname: '新账号' })
  view.rerender(<MemoryRouter><ProfilePage /></MemoryRouter>)
  expect(await screen.findByLabelText('昵称')).toHaveValue('新账号')
  await act(async () => release(null))
  expect(auth.logout).not.toHaveBeenCalled()
})
