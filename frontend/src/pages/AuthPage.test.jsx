import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AuthPage from './AuthPage'

const { auth, requestPasswordReset, confirmPasswordReset } = vi.hoisted(() => ({
  auth: {
    session: null,
    login: vi.fn(),
    register: vi.fn(),
  },
  requestPasswordReset: vi.fn(),
  confirmPasswordReset: vi.fn(),
}))

vi.mock('../state/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../api/client', () => ({
  endpoints: { requestPasswordReset, confirmPasswordReset },
}))

function renderPage() {
  return render(<MemoryRouter><AuthPage /></MemoryRouter>)
}

describe('AuthPage', () => {
  beforeEach(() => {
    auth.session = null
    auth.login.mockReset()
    auth.register.mockReset()
    requestPasswordReset.mockReset()
    confirmPasswordReset.mockReset()
  })

  it('exposes accessible tabs and browser-enforced form boundaries', () => {
    renderPage()
    expect(screen.getByRole('tablist', { name: '账号操作' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '登录' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByLabelText('用户名')).toHaveAttribute('minlength', '3')
    expect(screen.getByLabelText('用户名')).toHaveAttribute('maxlength', '50')
    expect(screen.getByLabelText('密码')).toHaveAttribute('minlength', '8')
    expect(screen.getByRole('button', { name: '显示密码' })).toBeInTheDocument()
  })

  it('shows a login failure and restores the submit control', async () => {
    const user = userEvent.setup()
    auth.login.mockRejectedValue(new Error('账号或密码错误'))
    renderPage()
    await user.type(screen.getByLabelText('用户名'), 'learner')
    await user.type(screen.getByLabelText('密码'), 'password1')
    await user.click(screen.getByRole('button', { name: /进入忆知/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('账号或密码错误')
    expect(screen.getByRole('button', { name: /进入忆知/ })).toBeEnabled()
  })

  it('completes both password-reset stages with live status feedback', async () => {
    const user = userEvent.setup()
    requestPasswordReset.mockResolvedValue({})
    confirmPasswordReset.mockResolvedValue({})
    renderPage()
    await user.click(screen.getByRole('button', { name: '忘记密码' }))
    await user.type(screen.getByLabelText('用户名'), 'learner')
    await user.type(screen.getByLabelText('绑定邮箱'), 'learner@example.test')
    await user.click(screen.getByRole('button', { name: /发送验证码/ }))

    expect(requestPasswordReset).toHaveBeenCalledWith({ username: 'learner', email: 'learner@example.test' })
    expect(await screen.findByRole('status')).toHaveTextContent('验证码已发送')
    await user.type(screen.getByLabelText('邮箱验证码'), 'token-123')
    await user.type(screen.getByLabelText('新密码'), 'new-password')
    await user.click(screen.getByRole('button', { name: /确认重置密码/ }))

    await waitFor(() => expect(confirmPasswordReset).toHaveBeenCalledWith({ token: 'token-123', newPassword: 'new-password' }))
    expect(screen.getByRole('status')).toHaveTextContent('密码已重置')
  })
})
