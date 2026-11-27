import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import DocumentVersions from './DocumentVersions'
import { endpoints } from '../../api/client'

vi.mock('../../api/client', () => ({ endpoints: { documentVersions: vi.fn() } }))
const document = { id: 7, fileName: 'qa.txt', status: 'ready', updatedAt: '2026-11-26T00:00:00' }
const versions = [
  { version_number: 2, active: 1, file_name: 'qa.txt', sha256: 'abc123' },
  { version_number: 1, active: 0, created_at: '2026-11-25T00:00:00' },
]
const props = () => ({ document, onClose: vi.fn(), onRestore: vi.fn() })
beforeEach(() => { vi.resetAllMocks(); endpoints.documentVersions.mockResolvedValue(versions) })

test('valid SQL flags disable the active version and permit restoring the old one', async () => {
  const input = props()
  const view = render(<DocumentVersions {...input} />)
  expect(screen.getByRole('region', { name: '文档版本读取' })).toHaveAttribute('aria-busy', 'true')
  expect(await screen.findByRole('button', { name: /v2/ })).toBeDisabled()
  const oldVersion = screen.getByRole('button', { name: /v1 · qa.txt/ })
  expect(oldVersion).toBeEnabled()
  fireEvent.click(oldVersion)
  expect(input.onRestore).toHaveBeenCalledWith(versions[1])
  view.rerender(<DocumentVersions {...input} unavailable />)
  expect(oldVersion).toBeDisabled()
  view.rerender(<DocumentVersions {...input} busy />)
  expect(oldVersion).toBeDisabled()
  expect(screen.getByRole('button', { name: '关闭 / Close' })).toBeDisabled()
})

test('failed refresh preserves the snapshot and blocks restores until a successful GET retry', async () => {
  const input = props()
  const view = render(<DocumentVersions {...input} />)
  await screen.findByRole('button', { name: /v1/ })
  let reject
  endpoints.documentVersions.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
  const updated = { ...document, updatedAt: '2026-11-27T00:00:00' }
  view.rerender(<DocumentVersions {...input} document={updated} />)
  expect(screen.getByRole('button', { name: /v1/ })).toBeDisabled()
  await act(async () => reject(new Error('private backend response')))
  expect(screen.getByRole('alert')).toHaveTextContent('文档版本加载失败，请重试。')
  expect(screen.queryByText('private backend response')).not.toBeInTheDocument()
  expect(screen.getByText('已有版本记录可能不是最新状态。')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /v1/ })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '重试 / Retry' }))
  await waitFor(() => expect(screen.getByRole('button', { name: /v1/ })).toBeEnabled())
  expect(endpoints.documentVersions).toHaveBeenCalledTimes(3)
  expect(input.onRestore).not.toHaveBeenCalled()
})

test('obsolete reads are aborted and late responses cannot replace the current snapshot', async () => {
  let resolve
  endpoints.documentVersions.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const input = props()
  const view = render(<DocumentVersions {...input} />)
  const signal = endpoints.documentVersions.mock.calls[0][1].signal
  view.rerender(<DocumentVersions {...input} document={{ ...document, updatedAt: '2026-11-27T00:00:00' }} />)
  await screen.findByRole('button', { name: /v2/ })
  expect(signal.aborted).toBe(true)
  await act(async () => resolve([{ version_number: 99, active: false }]))
  expect(screen.queryByRole('button', { name: /v99/ })).not.toBeInTheDocument()
  const currentSignal = endpoints.documentVersions.mock.calls[1][1].signal
  view.unmount()
  expect(currentSignal.aborted).toBe(true)
})
