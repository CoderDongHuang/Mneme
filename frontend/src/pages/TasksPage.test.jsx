import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import TasksPage from './TasksPage'
import { endpoints } from '../api/client'
vi.mock('../api/client', () => ({ endpoints: { tasks: vi.fn(), operations: vi.fn(), cancelTask: vi.fn(), retryTask: vi.fn() }, openNotificationStream: () => ({ close() {} }) }))
beforeEach(() => {
  endpoints.tasks.mockResolvedValue([{ task_id: 't1', task_type: 'document_ingest', file_name: 'test.pdf', status: 'pending', attempt_count: 0, max_attempts: 3 }, { task_id: 't2', task_type: 'document_delete', status: 'pending' }])
  endpoints.operations.mockResolvedValue([])
})
test('only pending ingestion can be cancelled and server errors remain visible', async () => {
  endpoints.cancelTask.mockRejectedValue(new Error('任务已领取'))
  render(<TasksPage />)
  await screen.findByText('test.pdf')
  expect(screen.getAllByRole('button', { name: '取消等待任务' })).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: '取消等待任务' }))
  await waitFor(() => expect(endpoints.cancelTask).toHaveBeenCalledWith('t1'))
  expect(await screen.findByRole('alert')).toHaveTextContent('任务已领取')
})
