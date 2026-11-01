import { fireEvent, render, screen, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'
import ChatPage from './ChatPage'
import { endpoints, streamChat } from '../api/client'

vi.mock('../api/client', () => ({ endpoints: {
  sessions: vi.fn(), knowledgeBases: vi.fn(), sessionMessages: vi.fn(), createSession: vi.fn(),
  deleteSession: vi.fn(), confirmMemory: vi.fn(), stopChat: vi.fn(),
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

test('queued candidates preserve a completed answer and offer task and memory links without early confirmation', async () => {
  streamChat.mockImplementation(async (_, { onEvent }) => {
    onEvent('token', { content: '已保存的完整回答' })
    onEvent('memory', { pending: [], status: 'queued' })
    onEvent('done', {})
    return { status: 'completed' }
  })
  await open(); send()
  expect(await screen.findByText('已保存的完整回答')).toBeInTheDocument()
  expect(await screen.findByText(/回答已保存，候选记忆正在后台保存/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '查看记忆任务' })).toHaveAttribute('href', '/tasks')
  expect(screen.getByRole('link', { name: '前往学习记忆确认' })).toHaveAttribute('href', '/memory')
  expect(screen.queryByRole('button', { name: '确认记忆' })).not.toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '重试' })).not.toBeInTheDocument()
})

function controlledStream() {
  let handlers, payload
  let resolve, reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  streamChat.mockImplementation((body, options) => {
    payload = body; handlers = options
    options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    return promise
  })
  return {
    start: () => handlers.onEvent('start', { session_id: payload.session_id, request_id: payload.request_id, answer_generation: 2 }),
    done: () => { handlers.onEvent('done', {}); resolve({ status: 'completed' }) },
    stopped: () => { handlers.onEvent('stopped', {}); resolve({ status: 'stopped' }) },
    reject, signal: () => handlers.signal,
  }
}

test('early stop waits for generation handshake and server acknowledgement before aborting', async () => {
  const stream = controlledStream(); const ack = deferred()
  endpoints.stopChat.mockReturnValue(ack.promise)
  await open(); send(); await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: '停止生成' }))
  expect(endpoints.stopChat).not.toHaveBeenCalled()
  await act(async () => stream.start())
  expect(endpoints.stopChat).toHaveBeenCalledWith({ session_id: '3', request_id: expect.any(String), answer_generation: 2 })
  expect(stream.signal().aborted).toBe(false)
  await act(async () => ack.resolve({ status: 'stopped' }))
  expect(stream.signal().aborted).toBe(true)
  expect(await screen.findByText('已停止生成')).toBeInTheDocument()
})

test('failed stop acknowledgement keeps reading and permits another stop attempt', async () => {
  const stream = controlledStream()
  endpoints.stopChat.mockRejectedValueOnce(new Error('网络中断')).mockResolvedValueOnce({ status: 'stopped' })
  await open(); send(); await act(async () => {}); await act(async () => stream.start())
  fireEvent.click(screen.getByRole('button', { name: '停止生成' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('停止未确认')
  expect(stream.signal().aborted).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: '停止生成' }))
  expect(await screen.findByText('已停止生成')).toBeInTheDocument()
  expect(endpoints.stopChat).toHaveBeenCalledTimes(2)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('done winning a stop race cannot be overwritten by a late acknowledgement', async () => {
  const stream = controlledStream(); const ack = deferred()
  endpoints.stopChat.mockReturnValue(ack.promise)
  await open(); send(); await act(async () => {}); await act(async () => stream.start())
  fireEvent.click(screen.getByRole('button', { name: '停止生成' }))
  await act(async () => stream.done())
  await act(async () => ack.resolve({ status: 'stopped' }))
  expect(stream.signal().aborted).toBe(false)
  expect(screen.queryByText('已停止生成')).not.toBeInTheDocument()
})

test('unexpected AbortError is a failed connection rather than a user stop', async () => {
  streamChat.mockRejectedValue(new DOMException('连接中断', 'AbortError'))
  await open(); send()
  expect(await screen.findByRole('alert')).toHaveTextContent('连接中断')
  expect(screen.queryByText('已停止生成')).not.toBeInTheDocument()
})

test('server stopped event has the same confirmed stopped terminal state', async () => {
  const stream = controlledStream()
  await open(); send(); await act(async () => {}); await act(async () => stream.stopped())
  expect(await screen.findByText('已停止生成')).toBeInTheDocument()
  expect(endpoints.stopChat).not.toHaveBeenCalled()
})

test.each([
  ['CLIENT_DISCONNECTED', '连接已中断'], ['MODEL_TIMEOUT', '模型响应超时'],
  ['GROUNDING_FAILED', '引用核验失败'], ['MODEL_ERROR', '模型生成失败'],
])('reloaded %s history retains its failure reason and partial answer', async (errorCode, label) => {
  endpoints.sessionMessages.mockResolvedValue([
    { id: 1, role: 'user', content: '问题' },
    { id: 2, role: 'assistant', content: '部分正文', status: 'failed', errorCode },
  ])
  await open()
  fireEvent.click(screen.getByRole('button', { name: '打开对话：会话 A' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(label)
  expect(screen.getByRole('alert')).toHaveTextContent('已保留部分回答')
  expect(screen.getByText('部分正文')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '重试' })).toBeEnabled()
})
