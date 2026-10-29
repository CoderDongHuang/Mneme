import { fireEvent, render, screen, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'
import ChatPage from './ChatPage'
import { endpoints, streamChat } from '../api/client'

vi.mock('../api/client', () => ({ endpoints: {
  sessions: vi.fn(), knowledgeBases: vi.fn(), sessionMessages: vi.fn(), createSession: vi.fn(),
  deleteSession: vi.fn(), confirmMemory: vi.fn(),
}, streamChat: vi.fn() }))
vi.mock('../components/RetrievalFilters', () => ({ default: () => null, emptyFilters: {} }))
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
beforeEach(() => {
  vi.resetAllMocks()
  endpoints.sessions.mockResolvedValue([{ id: 1, title: '会话 A' }, { id: 2, title: '会话 B' }])
  endpoints.knowledgeBases.mockResolvedValue([])
  endpoints.createSession.mockResolvedValue({ id: 3, title: '新对话' })
})
async function open() {
  render(<MemoryRouter><ChatPage /></MemoryRouter>)
  await screen.findByRole('button', { name: '打开对话：会话 A' })
}
function send(text = '测试问题') {
  fireEvent.change(screen.getByRole('textbox', { name: '向忆知提问...' }), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
}
test('latest session wins and sending is blocked until its messages arrive', async () => {
  const a = deferred(); const b = deferred()
  endpoints.sessionMessages.mockImplementation(id => id === 1 ? a.promise : b.promise)
  await open()
  fireEvent.click(screen.getByRole('button', { name: '打开对话：会话 A' }))
  fireEvent.click(screen.getByRole('button', { name: '打开对话：会话 B' }))
  fireEvent.change(screen.getByRole('textbox', { name: '向忆知提问...' }), { target: { value: '不能串话' } })
  expect(screen.getByRole('button', { name: '发送' })).toBeDisabled()
  await act(async () => b.resolve([{ id: 20, role: 'assistant', content: 'B 的内容', status: 'completed' }]))
  await screen.findByText('B 的内容')
  await act(async () => a.resolve([{ id: 10, role: 'assistant', content: 'A 的旧响应' }]))
  expect(screen.queryByText('A 的旧响应')).not.toBeInTheDocument()
  expect(document.querySelector('.chat-heading')).toHaveTextContent('会话 B')
})
test.each([false, true])('failed answer has a terminal state and retry (partial=%s)', async partial => {
  streamChat.mockImplementation(async (_, { onEvent }) => {
    if (partial) onEvent('token', { content: '已收到的一部分' })
    throw new Error('模型故障')
  })
  await open(); send()
  expect(await screen.findByRole('button', { name: '重试' })).toBeEnabled()
  expect(screen.getByRole('alert')).toHaveTextContent('模型故障')
  expect(screen.queryByLabelText('正在生成回答')).not.toBeInTheDocument()
  if (partial) expect(screen.getByText('已收到的一部分')).toBeInTheDocument()
})
test('stop works even while session creation is pending', async () => {
  const creation = deferred()
  endpoints.createSession.mockReturnValue(creation.promise)
  await open(); send()
  fireEvent.click(screen.getByRole('button', { name: '停止生成' }))
  await act(async () => creation.resolve({ id: 3, title: '新对话' }))
  await screen.findByRole('button', { name: '重试' })
  expect(streamChat).not.toHaveBeenCalled()
  expect(screen.getByText('已停止生成')).toBeInTheDocument()
})
test('memory failure preserves the item and duplicate clicks send only one request', async () => {
  let reject
  const confirmation = new Promise((_, fail) => { reject = fail })
  endpoints.confirmMemory.mockReturnValue(confirmation)
  streamChat.mockImplementation(async (_, { onEvent }) => onEvent('memory', { pending: [{ temp_id: 'm1', content: '喜欢示例', category: 'preference' }] }))
  await open(); send()
  const button = await screen.findByRole('button', { name: '确认记忆' })
  fireEvent.click(button); fireEvent.click(button)
  expect(endpoints.confirmMemory).toHaveBeenCalledTimes(1)
  await act(async () => reject(new Error('保存失败')))
  expect(screen.getByText('喜欢示例')).toBeInTheDocument()
  expect(button).toBeEnabled()
  expect(screen.getByRole('alert')).toHaveTextContent('保存失败')
})
