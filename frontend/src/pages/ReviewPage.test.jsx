import { act, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import ReviewPage from './ReviewPage'
import { endpoints } from '../api/client'

vi.mock('../api/client', () => ({ endpoints: { reviews: vi.fn(), plans: vi.fn() } }))
afterEach(() => vi.useRealTimers())

test('an upcoming card becomes reviewable at its due time without reloading or fetching again', async () => {
  vi.useFakeTimers()
  const start = new Date('2026-10-30T09:00:00.500Z')
  vi.setSystemTime(start)
  endpoints.reviews.mockResolvedValue([{ id: 1, prompt: '到期问题', answer: '答案', due_at: '2026-10-30T09:00:01Z', review_count: 0 }])
  endpoints.plans.mockResolvedValue([])
  await act(async () => { render(<MemoryRouter><ReviewPage /></MemoryRouter>) })
  expect(screen.getByRole('heading', { name: '今天的复习已就绪' })).toBeVisible()
  expect(screen.queryByRole('button', { name: '查看答案' })).not.toBeInTheDocument()
  await act(async () => { vi.advanceTimersByTime(1000) })
  expect(screen.getByRole('heading', { name: '到期问题' })).toBeVisible()
  expect(screen.getByRole('button', { name: '查看答案' })).toBeVisible()
  expect(endpoints.reviews).toHaveBeenCalledTimes(1)
})
