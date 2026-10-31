import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import ParsePreview from './ParsePreview'
import { endpoints } from '../api/client'

vi.mock('../api/client', () => ({ endpoints: { documentTags: vi.fn(), setDocumentTags: vi.fn() } }))
const preview = id => ({ document: { id, chunk_count: 0 }, parse_report: { pages: [] } })
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
beforeEach(() => { vi.resetAllMocks(); localStorage.clear(); endpoints.setDocumentTags.mockResolvedValue([]) })

test('late initial tags cannot overwrite user edits or save empty tags', async () => {
  const load = deferred()
  endpoints.documentTags.mockReturnValue(load.promise)
  render(<ParsePreview preview={preview(1)} />)
  fireEvent.change(screen.getByRole('textbox', { name: '资料标签' }), { target: { value: '课程,重点' } })
  await act(async () => load.resolve([]))
  expect(screen.getByRole('textbox', { name: '资料标签' })).toHaveValue('课程,重点')
  fireEvent.click(screen.getByRole('button', { name: '保存标签' }))
  await waitFor(() => expect(endpoints.setDocumentTags).toHaveBeenCalledWith(1, ['课程', '重点']))
})

test('untouched tags load and switching documents ignores stale requests and resets edited state', async () => {
  const first = deferred(), second = deferred()
  endpoints.documentTags.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
  const { rerender } = render(<ParsePreview preview={preview(1)} />)
  fireEvent.change(screen.getByRole('textbox', { name: '资料标签' }), { target: { value: 'old draft' } })
  rerender(<ParsePreview preview={preview(2)} />)
  expect(screen.getByRole('textbox', { name: '资料标签' })).toHaveValue('')
  await act(async () => second.resolve(['new']))
  await act(async () => first.resolve(['stale']))
  expect(screen.getByRole('textbox', { name: '资料标签' })).toHaveValue('new')
})
