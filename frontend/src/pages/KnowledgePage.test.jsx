import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import KnowledgePage from './KnowledgePage'
import { endpoints } from '../api/client'

vi.mock('../state/AuthContext', () => ({ useAuth: () => ({ session: { userId: 1 } }) }))
vi.mock('../api/client', () => ({ endpoints: {
  knowledgeBases: vi.fn(), documents: vi.fn(), notifications: vi.fn(), createKnowledgeBase: vi.fn(),
  deleteKnowledgeBase: vi.fn(), deleteDocument: vi.fn(), documentVersions: vi.fn(),
}, openNotificationStream: () => ({ close() {} }) }))
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear()
  endpoints.knowledgeBases.mockResolvedValue([{ id: 1, name: '资料 A' }, { id: 2, name: '资料 B' }])
  endpoints.documents.mockResolvedValue([])
  endpoints.notifications.mockResolvedValue([])
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})
test('creation failure preserves the form and allows retry', async () => {
  endpoints.createKnowledgeBase.mockRejectedValueOnce(new Error('创建失败')).mockResolvedValue({ id: 3, name: '我的笔记' })
  render(<KnowledgePage />)
  fireEvent.click(await screen.findByRole('button', { name: '新建资料库' }))
  fireEvent.change(screen.getByPlaceholderText('例如：机器学习基础'), { target: { value: '我的笔记' } })
  fireEvent.click(screen.getByRole('button', { name: '创建资料库' }))
  await waitFor(() => expect(endpoints.createKnowledgeBase).toHaveBeenCalledTimes(1))
  expect(screen.getByPlaceholderText('例如：机器学习基础')).toHaveValue('我的笔记')
  await waitFor(() => expect(screen.getByRole('button', { name: '创建资料库' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '创建资料库' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: '创建资料库' })).not.toBeInTheDocument())
})
test('old library response is ignored after switching', async () => {
  let resolve
  endpoints.documents.mockImplementation(id => id === 1 ? new Promise(r => { resolve = r }) : Promise.resolve([{ id: 22, fileName: 'B.txt', status: 'ready' }]))
  render(<KnowledgePage />)
  await screen.findByRole('option', { name: '资料 B' })
  await waitFor(() => expect(resolve).toBeTypeOf('function'))
  fireEvent.change(screen.getByRole('combobox', { name: '资料库' }), { target: { value: '2' } })
  await screen.findByRole('button', { name: 'B.txt' })
  await act(async () => resolve([{ id: 11, fileName: 'A.txt', status: 'ready' }]))
  expect(screen.queryByText('A.txt')).not.toBeInTheDocument()
})
test('failed library deletion leaves the library available', async () => {
  endpoints.deleteKnowledgeBase.mockRejectedValue(new Error('删除失败'))
  render(<KnowledgePage />)
  await waitFor(() => expect(screen.getByRole('button', { name: '删除资料库' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '删除资料库' }))
  await screen.findByText('删除失败')
  expect(screen.getByRole('option', { name: '资料 A' })).toBeInTheDocument()
})

test('first library failure offers a read retry without claiming no libraries', async () => {
  endpoints.knowledgeBases.mockRejectedValueOnce(new Error('offline'))
  render(<KnowledgePage />)
  const reads = screen.getByRole('region', { name: '资料库读取' })
  await within(reads).findByRole('alert')
  expect(screen.queryByText('建立第一个资料库')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '新建资料库' })).toBeDisabled()
  fireEvent.click(within(reads).getByRole('button', { name: '重试 / Retry' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '导入资料' })).toBeEnabled())
  expect(endpoints.createKnowledgeBase).not.toHaveBeenCalled()
})

test('first document failure does not claim empty and has independent retry', async () => {
  endpoints.documents.mockRejectedValueOnce(new Error('offline'))
  render(<KnowledgePage />)
  const reads = await screen.findByRole('region', { name: '文档读取' })
  await within(reads).findByRole('alert')
  expect(screen.queryByText('这里还没有资料')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '导入资料' })).toBeDisabled()
  fireEvent.click(within(reads).getByRole('button', { name: '重试 / Retry' }))
  await screen.findByText('这里还没有资料')
  expect(endpoints.knowledgeBases).toHaveBeenCalledTimes(1)
})

test('filters distinguish no match from an actually empty library', async () => {
  endpoints.documents.mockResolvedValue([{ id: 7, fileName: 'qa.txt', status: 'ready' }])
  render(<KnowledgePage />)
  await screen.findByRole('button', { name: 'qa.txt' })
  fireEvent.change(screen.getByRole('textbox', { name: '筛选文档' }), { target: { value: 'absent' } })
  expect(screen.getByText('没有符合筛选条件的资料')).toBeVisible()
  expect(screen.queryByText('这里还没有资料')).not.toBeInTheDocument()
})

test.each(['null', '[]', '{"warnings":{}}', '{"warnings":[null]}', '{"warnings":[{"code":{}}]}', '{"parser_version":{}}'])(
  'an invalid nested parse report does not crash the document list: %s', async parseReport => {
    endpoints.documents.mockResolvedValue([{ id: 7, fileName: 'qa.txt', status: 'ready', parseReport }])
    render(<KnowledgePage />)
    expect(await screen.findByRole('button', { name: 'qa.txt' })).toBeInTheDocument()
    expect(screen.getByText('解析报告格式无效，请重新解析')).toBeInTheDocument()
  })
