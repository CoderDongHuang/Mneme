import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { vi, test, expect } from 'vitest'
import PrivacyPage from './PrivacyPage'
import { api } from '../api/client'
vi.mock('../api/client', () => ({ api: vi.fn(), endpoints: { operations: vi.fn(async () => []) }, downloadWorkspaceArchive: vi.fn(), downloadWorkspaceExport: vi.fn() }))
test('saves revoked consent and confirms trace deletion', async () => {
  api.mockResolvedValue({ cloud_allowed: true, trace_days: 30, trace_max_days: 30, providers: ['DeepSeek'], sending_scope: ['对话'] })
  render(<MemoryRouter><PrivacyPage /></MemoryRouter>)
  const user = userEvent.setup()
  await user.click(await screen.findByLabelText('允许外部模型处理'))
  await user.click(screen.getByRole('button', { name: '保存策略' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('/privacy', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ cloud_allowed: false, trace_days: 30 }) })))
  expect(screen.getByRole('button', { name: '删除我的 Trace' })).toBeDisabled()
  await user.type(screen.getByLabelText('删除确认'), 'DELETE TRACES')
  await user.click(screen.getByRole('button', { name: '删除我的 Trace' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('/privacy/traces?confirmation=DELETE%20TRACES', { method: 'DELETE' }))
})
