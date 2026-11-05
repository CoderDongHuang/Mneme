import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { endpoints } from '../api/client'
import { AuthProvider, useAuth } from './AuthContext'

function SessionProbe() {
  const auth = useAuth()
  return (
    <div>
      <output data-testid="session">{auth.session?.username || 'anonymous'}</output>
      <output data-testid="role">{auth.isAdmin ? 'admin' : auth.roleLoading ? 'loading' : 'unavailable'}</output>
      <button onClick={() => auth.login({ username: 'lin', password: 'password1' })}>login</button>
      <button onClick={() => auth.updateSession({ nickname: 'Learner' })}>update</button>
    </div>
  )
}

beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
})

describe('AuthProvider', () => {

  it('restores a valid session and persists profile changes', async () => {
    localStorage.setItem('mneme_auth', JSON.stringify({ username: 'lin' }))
    render(<AuthProvider><SessionProbe /></AuthProvider>)
    expect(screen.getByTestId('session')).toHaveTextContent('lin')

    screen.getByRole('button', { name: 'update' }).click()
    await waitFor(() => expect(JSON.parse(localStorage.getItem('mneme_auth'))).toMatchObject({ nickname: 'Learner' }))
  })

  it('recovers from corrupt storage instead of crashing', () => {
    localStorage.setItem('mneme_auth', '{broken')
    render(<AuthProvider><SessionProbe /></AuthProvider>)
    expect(screen.getByTestId('session')).toHaveTextContent('anonymous')
    expect(localStorage.getItem('mneme_auth')).toBeNull()
  })

  it('persists login and clears it after a global unauthorized event', async () => {
    vi.spyOn(endpoints, 'login').mockResolvedValue({ username: 'lin', userId: 3 })
    render(<AuthProvider><SessionProbe /></AuthProvider>)
    screen.getByRole('button', { name: 'login' }).click()
    await screen.findByText('lin')
    expect(JSON.parse(localStorage.getItem('mneme_auth'))).toMatchObject({ userId: 3 })

    act(() => window.dispatchEvent(new Event('mneme:unauthorized')))
    expect(screen.getByTestId('session')).toHaveTextContent('anonymous')
    await waitFor(() => expect(localStorage.getItem('mneme_auth')).toBeNull())
  })
})

it.each([null, {}, { username: 'other', nickname: 'Wrong', email: '', emailVerified: false, role: 'admin', userId: 8 }, { username: 'lin', nickname: {}, email: '', emailVerified: false, role: 'admin', userId: 3 }])('rejects invalid or foreign profile refresh without replacing login: %j', async profile => {
  vi.spyOn(endpoints, 'profile').mockResolvedValue(profile)
  localStorage.setItem('mneme_auth', JSON.stringify({ username: 'lin', userId: 3, nickname: 'Original' }))
  render(<AuthProvider><SessionProbe /></AuthProvider>)
  await waitFor(() => expect(screen.getByTestId('role')).toHaveTextContent('unavailable'))
  expect(screen.getByTestId('session')).toHaveTextContent('lin')
  expect(JSON.parse(localStorage.getItem('mneme_auth'))).toMatchObject({ nickname: 'Original', userId: 3 })
})

it('verified profile refresh accepts legitimate admin role and shared nickname', async () => {
  vi.spyOn(endpoints, 'profile').mockResolvedValue({ username: 'lin', userId: 3, nickname: 'Admin', email: '', emailVerified: false, role: 'admin' })
  localStorage.setItem('mneme_auth', JSON.stringify({ username: 'lin', userId: 3 }))
  render(<AuthProvider><SessionProbe /></AuthProvider>)
  await waitFor(() => expect(screen.getByTestId('role')).toHaveTextContent('admin'))
  expect(JSON.parse(localStorage.getItem('mneme_auth'))).toMatchObject({ nickname: 'Admin' })
})
