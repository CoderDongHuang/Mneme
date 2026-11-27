import { useState } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { endpoints } from '../api/client'
import { PreferencesProvider, usePreferences } from './PreferencesContext'

vi.mock('../api/client', () => ({ endpoints: { preferences: vi.fn(), savePreferences: vi.fn() } }))
vi.mock('./AuthContext', () => ({ useAuth: () => ({ session: { userId: 7 } }) }))
vi.mock('../i18n', () => ({ setLanguage: vi.fn(() => Promise.resolve()), t: value => value }))

const validPreferences = { language: 'en', timezone: 'UTC', notifications: false, theme: 'dark' }

function PreferencesState() {
  const { preferences, error, save } = usePreferences()
  const [writeError, setWriteError] = useState('')
  return <>
    <output aria-label="preferences">{JSON.stringify(preferences)}</output>
    {error && <p role="alert">{error}</p>}
    <button onClick={() => save(validPreferences).catch(failure => setWriteError(failure.message))}>Save</button>
    {writeError && <p data-testid="write-error">{writeError}</p>}
  </>
}

function mount() {
  return render(<PreferencesProvider><PreferencesState /></PreferencesProvider>)
}

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  })
})

afterEach(() => vi.restoreAllMocks())

test('invalid preference reads report a contract error and keep defaults', async () => {
  endpoints.preferences.mockResolvedValueOnce({ ...validPreferences, notifications: 'false' })
  mount()

  expect(await screen.findByRole('alert')).toHaveTextContent('偏好响应格式不正确')
  expect(screen.getByLabelText('preferences')).toHaveTextContent(JSON.stringify({
    language: 'zh-CN', timezone: 'Asia/Shanghai', notifications: true, theme: 'system',
  }))
})

test('invalid successful save receipts do not update preferences', async () => {
  endpoints.preferences.mockResolvedValueOnce(validPreferences)
  endpoints.savePreferences.mockResolvedValueOnce({ ...validPreferences, theme: 'auto' })
  mount()

  await waitFor(() => expect(screen.getByLabelText('preferences')).toHaveTextContent(JSON.stringify(validPreferences)))
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  expect(await screen.findByTestId('write-error')).toHaveTextContent('偏好保存回执格式不正确')
  expect(screen.getByLabelText('preferences')).toHaveTextContent(JSON.stringify(validPreferences))
  expect(endpoints.savePreferences).toHaveBeenCalledOnce()
})
