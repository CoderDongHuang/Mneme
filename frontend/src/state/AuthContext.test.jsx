import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { endpoints } from '../api/client'
import { AuthProvider, useAuth } from './AuthContext'

function SessionProbe() {
  const auth = useAuth()
  return (
    <div>
      <output data-testid="session">{auth.session?.username || 'anonymous'}</output>
      <button onClick={() => auth.login({ username: 'lin', password: 'password1' })}>login</button>
      <button onClick={() => auth.updateSession({ nickname: 'Learner' })}>update</button>
    </div>
  )
}

describe('AuthProvider', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

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
