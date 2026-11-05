import { fireEvent, render, screen, act, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'
import ChatPage from './ChatPage'
import { endpoints, streamChat } from '../api/client'
const auth = vi.hoisted(() => ({ session: null }))
vi.mock('../state/AuthContext', () => ({ useAuth: () => auth }))

vi.mock('../api/client', () => ({ endpoints: {
  sessions: vi.fn(), knowledgeBases: vi.fn(), sessionMessages: vi.fn(), createSession: vi.fn(),
  renameSession: vi.fn(), deleteSession: vi.fn(), confirmMemory: vi.fn(), stopChat: vi.fn(),
}, streamChat: vi.fn() }))
vi.mock('../components/RetrievalFilters', () => ({ default: () => null, emptyFilters: {} }))
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }

test('session reads finish while knowledge bases remain pending', async () => {
  endpoints.knowledgeBases.mockReturnValue(deferred().promise)
  render(<MemoryRouter><ChatPage /></MemoryRouter>)
  expect(await screen.findByRole('button', { name: '打开对话：会话 A' })).toBeEnabled()
  expect(screen.queryByText('还没有历史对话')).not.toBeInTheDocument()
})

test('knowledge bases finish while history remains pending', async () => {
  endpoints.sessions.mockReturnValue(deferred().promise)
  endpoints.knowledgeBases.mockResolvedValue([{ id: 9, name: '独立资料库' }])
  render(<MemoryRouter><ChatPage /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: '全部资料库', exact: true }))
  expect(screen.getByText('独立资料库')).toBeInTheDocument()
  expect(screen.queryByText('请先在资料库页面上传学习资料。')).not.toBeInTheDocument()
})

test('failed history is not empty and retries without reloading knowledge bases', async () => {
  endpoints.sessions.mockRejectedValueOnce(new Error('disconnected'))
  render(<MemoryRouter><ChatPage /></MemoryRouter>)
  const region = await screen.findByRole('region', { name: '会话列表读取' })
  expect(await within(region).findByRole('alert')).toHaveTextContent('会话列表加载失败')
  expect(screen.queryByText('还没有历史对话')).not.toBeInTheDocument()
  fireEvent.click(within(region).getByRole('button', { name: '重试 / Retry' }))
  expect(await screen.findByRole('button', { name: '打开对话：会话 A' })).toBeEnabled()
  expect(endpoints.knowledgeBases).toHaveBeenCalledTimes(1)
})

test('failed knowledge bases preserve the draft and block sending until independent recovery', async () => {
  endpoints.knowledgeBases.mockRejectedValueOnce(new Error('disconnected'))
  await open()
  const region = screen.getByRole('region', { name: '对话资料库读取' })
  expect(await within(region).findByRole('alert')).toHaveTextContent('资料库加载失败')
  const input = screen.getByRole('textbox', { name: '向忆知提问...' })
  fireEvent.change(input, { target: { value: '保留我的问题' } })
  expect(screen.getByRole('button', { name: '发送' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: '暂无资料库' })).not.toBeInTheDocument()
  fireEvent.click(within(region).getByRole('button', { name: '重试 / Retry' }))
  await act(async () => {})
  expect(screen.getByRole('button', { name: '发送' })).toBeEnabled()
  expect(input).toHaveValue('保留我的问题')
  expect(endpoints.sessions).toHaveBeenCalledTimes(1)
  expect(streamChat).not.toHaveBeenCalled()
})

test('filtered history has a distinct no-match state', async () => {
  await open()
  fireEvent.change(screen.getByRole('textbox', { name: '搜索会话' }), { target: { value: 'no-match' } })
  expect(screen.getByText('没有符合筛选条件的对话')).toBeInTheDocument()
  expect(screen.queryByText('还没有历史对话')).not.toBeInTheDocument()
})
beforeEach(() => {
  vi.resetAllMocks()
  auth.session = null
  endpoints.sessions.mockResolvedValue([{ id: 1, title: '会话 A' }, { id: 2, title: '会话 B' }])
  endpoints.knowledgeBases.mockResolvedValue([])
  endpoints.createSession.mockResolvedValue({ id: 3, title: '新对话' })
})
async function open() {
  render(<MemoryRouter><ChatPage /></MemoryRouter>)
  await screen.findByRole('button', { name: '打开对话：会话 A' })
}

test('session deletion isolates only the accepted session and links to durable cleanup status', async () => {
  const pending = deferred()
  endpoints.deleteSession.mockReturnValue(pending.promise)
  await open()
  const remove = screen.getByRole('button', { name: '删除对话：会话 A' })
  fireEvent.click(remove); fireEvent.click(remove)
  expect(remove).toBeDisabled()
  expect(endpoints.deleteSession).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: '打开对话：会话 A' })).toBeInTheDocument()
  await act(async () => pending.resolve({ accepted: true, task_id: 'task_cleanup', status: 'pending' }))
  expect(screen.queryByRole('button', { name: '打开对话：会话 A' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '打开对话：会话 B' })).toBeInTheDocument()
  expect(screen.getByText('会话删除已受理，最终清理结果请在任务中心查看。')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '查看清理任务' })).toHaveAttribute('href', '/tasks')
  expect(screen.queryByText('会话清理已完成。')).not.toBeInTheDocument()
})

test.each([undefined, { deleted: true }, { accepted: true, task_id: 'task_cleanup', status: 'unknown' }])(
  'unverifiable session deletion keeps the list and never silently repeats the mutation (%j)', async receipt => {
    endpoints.deleteSession.mockResolvedValue(receipt)
    await open(); fireEvent.click(screen.getByRole('button', { name: '删除对话：会话 A' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('删除结果未确认')
    expect(screen.getByRole('button', { name: '打开对话：会话 A' })).toBeInTheDocument()
    expect(endpoints.deleteSession).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('link', { name: '查看清理任务' })).not.toBeInTheDocument()
  })
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
  ['INVALID_CHAT_EVENT', '回答流格式异常'],
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


test.each([null, {}, [{ id: 1, title: {} }], [{ id: 1 }, { id: 1 }]])('invalid sessions do not become an empty result (%j)', async value => {
  endpoints.sessions.mockResolvedValueOnce(value)
  render(<MemoryRouter><ChatPage /></MemoryRouter>)
  expect(await within(screen.getByRole('region', { name: '会话列表读取' })).findByRole('alert')).toHaveTextContent('会话列表加载失败')
  expect(screen.queryByText('还没有历史对话')).not.toBeInTheDocument()
})

test.each([null, {}, [{ id: 1, name: {} }], [{ id: 1, name: 'a' }, { id: 1, name: 'b' }]])('invalid libraries block sending (%j)', async value => {
  endpoints.knowledgeBases.mockResolvedValueOnce(value)
  await open()
  expect(await within(screen.getByRole('region', { name: '对话资料库读取' })).findByRole('alert')).toHaveTextContent('资料库加载失败')
  send('不能按错误检索范围发送')
  expect(streamChat).not.toHaveBeenCalled()
})

test('failed refresh keeps history visible but blocks actions until verified recovery', async () => {
  await open()
  endpoints.sessions.mockRejectedValueOnce(new Error('offline'))
  fireEvent.click(screen.getByRole('button', { name: '刷新会话' }))
  const region = screen.getByRole('region', { name: '会话列表读取' })
  expect(await within(region).findByRole('alert')).toHaveTextContent('会话列表加载失败')
  expect(screen.getByRole('button', { name: '打开对话：会话 A' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '删除对话：会话 A' })).toBeDisabled()
  fireEvent.click(within(region).getByRole('button', { name: '重试 / Retry' }))
  await act(async () => {})
  expect(screen.getByRole('button', { name: '删除对话：会话 A' })).toBeEnabled()
})

test('library recovery preserves an explicit empty selection and the draft', async () => {
  endpoints.knowledgeBases.mockResolvedValue([{ id: 9, name: '资料甲' }])
  await open()
  fireEvent.click(screen.getByRole('button', { name: '全部资料库', exact: true }))
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.change(screen.getByRole('textbox', { name: '向忆知提问...' }), { target: { value: '保留草稿' } })
  endpoints.knowledgeBases.mockRejectedValueOnce(new Error('offline'))
  fireEvent.click(screen.getByRole('button', { name: '刷新资料库' }))
  const region = screen.getByRole('region', { name: '对话资料库读取' })
  await within(region).findByRole('alert')
  fireEvent.click(within(region).getByRole('button', { name: '重试 / Retry' }))
  await act(async () => {})
  expect(screen.getByRole('checkbox')).not.toBeChecked()
  expect(screen.getByRole('textbox', { name: '向忆知提问...' })).toHaveValue('保留草稿')
})

test('a late initial session response cannot replace an explicitly chosen new chat', async () => {
  const pending = deferred()
  window.history.replaceState(null, '', '/chat?session=1')
  endpoints.sessions.mockReturnValue(pending.promise)
  render(<MemoryRouter><ChatPage /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '新对话', exact: true }))
  await act(async () => pending.resolve([{ id: 1, title: '迟到会话' }]))
  expect(endpoints.sessionMessages).not.toHaveBeenCalled()
  expect(document.querySelector('.chat-heading')).toHaveTextContent('新的学习对话')
  window.history.replaceState(null, '', '/')
})

test('unmount aborts both independent reads', () => {
  endpoints.sessions.mockReturnValue(deferred().promise)
  endpoints.knowledgeBases.mockReturnValue(deferred().promise)
  const view = render(<MemoryRouter><ChatPage /></MemoryRouter>)
  const sessionsSignal = endpoints.sessions.mock.calls[0][0].signal
  const basesSignal = endpoints.knowledgeBases.mock.calls[0][0].signal
  view.unmount()
  expect(sessionsSignal.aborted).toBe(true)
  expect(basesSignal.aborted).toBe(true)
})

test('a failed history refresh after completion preserves the answer and retries only the read', async () => {
  streamChat.mockImplementation(async (_, { onEvent }) => {
    onEvent('token', { content: '完整回答需要保留' })
    onEvent('done', {})
    return { status: 'completed' }
  })
  await open()
  endpoints.sessions.mockRejectedValueOnce(new Error('offline'))
  send()
  expect(await screen.findByText('完整回答需要保留')).toBeInTheDocument()
  const region = screen.getByRole('region', { name: '会话列表读取' })
  expect(await within(region).findByRole('alert')).toHaveTextContent('会话列表加载失败')
  expect(screen.queryByRole('button', { name: '重试', exact: true })).not.toBeInTheDocument()
  fireEvent.click(within(region).getByRole('button', { name: '重试 / Retry' }))
  await act(async () => {})
  expect(within(region).queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByText('完整回答需要保留')).toBeInTheDocument()
  expect(streamChat).toHaveBeenCalledTimes(1)
  expect(endpoints.createSession).toHaveBeenCalledTimes(1)
})

test('a deletion receipt invalidates an in-flight history snapshot so it cannot restore the deleted session', async () => {
  const receipt = deferred(), snapshot = deferred()
  endpoints.deleteSession.mockReturnValue(receipt.promise)
  await open()
  fireEvent.click(screen.getByRole('button', { name: '删除对话：会话 A' }))
  endpoints.sessions.mockReturnValueOnce(snapshot.promise)
  fireEvent.click(screen.getByRole('button', { name: '刷新会话' }))
  const signal = endpoints.sessions.mock.calls.at(-1)[0].signal
  await act(async () => receipt.resolve({ accepted: true, task_id: 'task_cleanup', status: 'pending' }))
  expect(signal.aborted).toBe(true)
  await act(async () => snapshot.resolve([{ id: 1, title: '会话 A' }, { id: 2, title: '会话 B' }]))
  expect(screen.queryByRole('button', { name: '打开对话：会话 A' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '打开对话：会话 B' })).toBeEnabled()
  expect(endpoints.deleteSession).toHaveBeenCalledTimes(1)
})

test('account changes isolate late reads and deletion receipts from the new account', async () => {
  const receipt = deferred(), oldSessions = deferred(), oldLibraries = deferred()
  auth.session = { userId: 1 }
  endpoints.knowledgeBases.mockResolvedValue([{ id: 9, name: '旧资料库' }])
  endpoints.deleteSession.mockReturnValue(receipt.promise)
  const view = render(<MemoryRouter><ChatPage /></MemoryRouter>)
  await screen.findByRole('button', { name: '打开对话：会话 A' })
  fireEvent.click(screen.getByRole('button', { name: '删除对话：会话 A' }))
  endpoints.sessions.mockReturnValueOnce(oldSessions.promise)
  fireEvent.click(screen.getByRole('button', { name: '刷新会话' }))
  fireEvent.click(screen.getByRole('button', { name: '全部资料库', exact: true }))
  endpoints.knowledgeBases.mockReturnValueOnce(oldLibraries.promise)
  fireEvent.click(screen.getByRole('button', { name: '刷新资料库' }))
  const signals = [endpoints.sessions.mock.calls.at(-1)[0].signal, endpoints.knowledgeBases.mock.calls.at(-1)[0].signal]
  auth.session = { userId: 2 }
  endpoints.sessions.mockResolvedValue([{ id: 20, title: '新账号会话' }])
  endpoints.knowledgeBases.mockResolvedValue([{ id: 30, name: '新账号资料库' }])
  view.rerender(<MemoryRouter><ChatPage /></MemoryRouter>)
  expect(await screen.findByRole('button', { name: '打开对话：新账号会话' })).toBeEnabled()
  expect(signals.every(signal => signal.aborted)).toBe(true)
  await act(async () => {
    receipt.resolve({ accepted: true, task_id: 'task_cleanup', status: 'pending' })
    oldSessions.resolve([{ id: 1, title: '会话 A' }])
    oldLibraries.resolve([{ id: 9, name: '旧资料库' }])
  })
  fireEvent.click(screen.getByRole('button', { name: '全部资料库', exact: true }))
  expect(screen.getByText('新账号资料库')).toBeInTheDocument()
  expect(screen.queryByText('旧资料库')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '打开对话：会话 A' })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: '查看清理任务' })).not.toBeInTheDocument()
})
