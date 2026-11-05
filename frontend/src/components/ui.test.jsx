import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { FeedbackBlock } from './ui'

test('retrying a read inside a form never submits the enclosing write form', () => {
  const retry = vi.fn(), submit = vi.fn(event => event.preventDefault())
  render(<form onSubmit={submit}><FeedbackBlock error="读取失败" onRetry={retry} /></form>)
  fireEvent.click(screen.getByRole('button', { name: '重试 / Retry' }))
  expect(retry).toHaveBeenCalledTimes(1)
  expect(submit).not.toHaveBeenCalled()
})
