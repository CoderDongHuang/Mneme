import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import AnalyticsPage from './AnalyticsPage'
import { api } from '../api/client'
vi.mock('../api/client', () => ({ api: vi.fn() }))
test('empty evidence stays empty and feedback references a persisted answer', async () => {
  api.mockResolvedValue({ topics: [], daily: [], feedback_summary: [], feedback: [], trace_quality: { status: 'unavailable' }, answers: [{ id: 44, excerpt: '回答摘录' }] })
  render(<AnalyticsPage />)
  expect(await screen.findByText('Trace 数据源不可用')).toBeVisible()
  const user = userEvent.setup()
  await user.selectOptions(screen.getByLabelText('回答'), '44')
  await user.selectOptions(screen.getByLabelText('回答评价'), 'refusal')
  await user.selectOptions(screen.getByLabelText('原因'), 'no_evidence')
  await user.click(screen.getByRole('button', { name: '保存反馈' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('/analytics/feedback', { method: 'PUT', body: JSON.stringify({ message_id: 44, outcome: 'refusal', citation_rating: 'unclear', reason: 'no_evidence', note: '' }) }))
  expect(await screen.findByText('反馈已保存')).toBeVisible()
})
