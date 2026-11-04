import { act, render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import DocumentDetail from './DocumentDetail'
import { endpoints } from '../api/client'

vi.mock('../api/client', () => ({
  endpoints: { documentPreview: vi.fn() }, documentFileUrl: id => `/document/${id}`,
}))
const first = { id: 1, fileName: 'first.txt', status: 'ready', chunkCount: 0 }
const view = document => <MemoryRouter><DocumentDetail document={document} onClose={() => {}} /></MemoryRouter>
const preview = content => ({ content, extension: 'txt', parse_report: { chunk_count: 0 } })
beforeEach(() => { vi.resetAllMocks() })

test('filtering out the selected document clears its loaded preview before rendering a null document', async () => {
  endpoints.documentPreview.mockResolvedValue(preview('First document content'))
  const { rerender } = render(view(first))
  await screen.findByText('First document content')
  rerender(view(null))
  expect(screen.getByText('选择文件，查看原文与解析结果')).toBeInTheDocument()
  expect(screen.queryByText('First document content')).not.toBeInTheDocument()
})

test('switching documents hides old content immediately and ignores a late response', async () => {
  let resolveFirst, resolveSecond
  endpoints.documentPreview.mockImplementation(id => new Promise(resolve => {
    if (id === 1) resolveFirst = resolve
    else resolveSecond = resolve
  }))
  const { rerender } = render(view(first))
  rerender(view({ ...first, id: 2, fileName: 'second.txt' }))
  await act(async () => resolveFirst(preview('First document content')))
  expect(screen.queryByText('First document content')).not.toBeInTheDocument()
  await act(async () => resolveSecond(preview('Second document content')))
  expect(screen.getByText('Second document content')).toBeInTheDocument()
  rerender(view({ ...first, id: 2, fileName: 'second.txt', status: 'parsing' }))
  expect(screen.queryByText('Second document content')).not.toBeInTheDocument()
})
