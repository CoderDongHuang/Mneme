import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'
import QuizPage from './QuizPage'
import { endpoints } from '../api/client'

vi.mock('../api/client', () => ({ endpoints: {
  quizzes: vi.fn(), knowledgeBases: vi.fn(), quizDraft: vi.fn(), saveQuizDraft: vi.fn(),
  quizAttempts: vi.fn(), submitQuiz: vi.fn(), generateQuiz: vi.fn(), reportQuestion: vi.fn(),
} }))
const quizzes = [1, 2].map(id => ({ id, title: `测验 ${id}`, questions_json: JSON.stringify([{ prompt: `题目 ${id}`, type: 'short' }]) }))
const attempt = { id: 11, score: 80, raw_score: 80, answers_json: '["旧答案"]', feedback_json: '[]', created_at: '2026-11-01T00:00:00Z' }
function deferred() { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
function mount() { return render(<MemoryRouter><QuizPage /></MemoryRouter>) }
function history() { return screen.getByRole('region', { name: '作答记录' }) }
async function choose(id = 1) {
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(`^测验 ${id}`) }))
  await screen.findByRole('textbox', { name: '你的答案' })
}
beforeEach(() => {
  vi.resetAllMocks()
  endpoints.quizzes.mockResolvedValue(quizzes)
  endpoints.knowledgeBases.mockResolvedValue([{ id: 7, name: '真实资料库' }])
  endpoints.quizDraft.mockResolvedValue({ answers_json: '[]', current_question: 0 })
  endpoints.saveQuizDraft.mockResolvedValue({})
  endpoints.quizAttempts.mockResolvedValue([])
  endpoints.submitQuiz.mockResolvedValue({ score: 100, raw_score: 100, feedback: [] })
})

test('initial list and base failures have separate retries and never pretend to be empty', async () => {
  endpoints.quizzes.mockRejectedValueOnce(new Error('列表离线'))
  endpoints.knowledgeBases.mockRejectedValueOnce(new Error('资料离线'))
  mount()
  expect(screen.getAllByText('—')).toHaveLength(3)
  expect(screen.getByText('正在读取测验…')).toBeVisible()
  const nav = screen.getByRole('navigation', { name: '我的测验' })
  await within(nav).findByText('测验列表加载失败：列表离线')
  expect(screen.queryByText('还没有测验。')).not.toBeInTheDocument()
  fireEvent.click(within(screen.getByRole('banner')).getByRole('button', { name: '创建测验' }))
  const dialog = screen.getByRole('dialog')
  await within(dialog).findByText('测验资料库加载失败：资料离线')
  expect(within(dialog).queryByText('暂无可用于测验的资料库。')).not.toBeInTheDocument()
  fireEvent.change(within(dialog).getByLabelText('测验主题'), { target: { value: '保留主题' } })
  fireEvent.click(within(dialog).getByRole('button', { name: '重试 / Retry' }))
  await within(dialog).findByRole('option', { name: '真实资料库' })
  expect(within(dialog).getByLabelText('测验主题')).toHaveValue('保留主题')
  expect(endpoints.quizzes).toHaveBeenCalledTimes(1)
  fireEvent.click(within(dialog).getByRole('button', { name: '关闭 / Close' }))
  fireEvent.click(within(nav).getByRole('button', { name: '重试 / Retry' }))
  await screen.findByRole('button', { name: /^测验 1/ })
  expect(endpoints.knowledgeBases).toHaveBeenCalledTimes(2)
})

test('a history outage does not block the draft or erase answers when history recovers', async () => {
  endpoints.quizDraft.mockResolvedValue({ answers_json: '["原草稿"]', current_question: 0 })
  endpoints.quizAttempts.mockRejectedValueOnce(new Error('历史离线'))
  mount(); await choose()
  expect(screen.getByRole('textbox', { name: '你的答案' })).toHaveValue('原草稿')
  await within(history()).findByText('作答记录加载失败：历史离线')
  expect(within(history()).queryByText('提交后会在这里保留历史记录。')).not.toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox', { name: '你的答案' }), { target: { value: '未提交新草稿' } })
  endpoints.quizAttempts.mockResolvedValue([attempt])
  fireEvent.click(within(history()).getByRole('button', { name: '重试 / Retry' }))
  await within(history()).findByRole('button', { name: /^80/ })
  expect(screen.getByRole('textbox', { name: '你的答案' })).toHaveValue('未提交新草稿')
  expect(endpoints.quizDraft).toHaveBeenCalledTimes(1)
})

test('draft failure is retryable without a perpetual loading state or loss of valid history', async () => {
  endpoints.quizDraft.mockRejectedValueOnce(new Error('草稿离线'))
  endpoints.quizAttempts.mockResolvedValue([attempt])
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /^测验 1/ }))
  await screen.findByText('测验草稿加载失败：草稿离线')
  expect(screen.queryByText('正在恢复测验草稿…')).not.toBeInTheDocument()
  expect(await within(history()).findByRole('button', { name: /^80/ })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '重试 / Retry' }))
  await screen.findByRole('textbox', { name: '你的答案' })
  expect(endpoints.quizAttempts).toHaveBeenCalledTimes(1)
})

test('a failed draft save prevents switching; retry preserves the edited answer', async () => {
  mount(); await choose()
  fireEvent.change(screen.getByRole('textbox', { name: '你的答案' }), { target: { value: '不能丢失的答案' } })
  endpoints.saveQuizDraft.mockRejectedValue(new Error('写入离线'))
  fireEvent.click(screen.getByRole('button', { name: /^测验 2/ }))
  await screen.findByText('草稿保存失败：写入离线。当前答案已保留，请重试保存后再切换。')
  expect(screen.getByRole('heading', { name: '题目 1' })).toBeVisible()
  expect(screen.getByRole('textbox', { name: '你的答案' })).toHaveValue('不能丢失的答案')
  expect(endpoints.quizDraft).toHaveBeenCalledTimes(1)
  endpoints.saveQuizDraft.mockResolvedValue({})
  fireEvent.click(screen.getByRole('button', { name: '重试 / Retry' }))
  await screen.findByText('第 1 / 1 题 · 草稿已保存')
  fireEvent.click(screen.getByRole('button', { name: /^测验 2/ }))
  await screen.findByRole('heading', { name: '题目 2' })
  expect(endpoints.saveQuizDraft).toHaveBeenCalledWith(1, { answers: ['不能丢失的答案'], current_question: 0 })
})

test('switching locks edits and ignores a second selection while the previous draft is saving', async () => {
  mount(); await choose()
  const pending = deferred()
  endpoints.saveQuizDraft.mockReturnValue(pending.promise)
  fireEvent.click(screen.getByRole('button', { name: /^测验 2/ }))
  expect(screen.getByRole('button', { name: /^测验 1/ })).toBeDisabled()
  expect(screen.getByRole('textbox', { name: '你的答案' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /^测验 1/ }))
  await act(async () => pending.resolve({}))
  await screen.findByRole('heading', { name: '题目 2' })
  expect(endpoints.quizDraft.mock.calls.map(args => args[0])).toEqual([1, 2])
})

test('late history from a previous quiz cannot replace the active quiz history', async () => {
  const late = deferred()
  endpoints.quizAttempts.mockImplementation(id => id === 1 ? late.promise : Promise.resolve([]))
  mount(); await choose(); await choose(2)
  await within(history()).findByText('提交后会在这里保留历史记录。')
  await act(async () => late.resolve([attempt]))
  expect(within(history()).queryByRole('button', { name: /^80/ })).not.toBeInTheDocument()
})

test('a submitted result survives history refresh failure and retry never resubmits', async () => {
  mount(); await choose()
  fireEvent.change(screen.getByRole('textbox', { name: '你的答案' }), { target: { value: '提交答案' } })
  endpoints.quizAttempts.mockRejectedValueOnce(new Error('刷新离线'))
  fireEvent.click(screen.getByRole('button', { name: '提交测验（已答 1 题）' }))
  await screen.findByText(/本次原始得分 100/)
  await within(history()).findByText('作答记录加载失败：刷新离线')
  expect(screen.getByRole('textbox', { name: '你的答案' })).toHaveValue('提交答案')
  expect(screen.getByRole('textbox', { name: '你的答案' })).toBeDisabled()
  expect(within(history()).getByText('已有作答记录可能不是最新状态。')).toBeVisible()
  endpoints.quizAttempts.mockResolvedValue([{ ...attempt, score: 100 }])
  fireEvent.click(within(history()).getByRole('button', { name: '重试 / Retry' }))
  await within(history()).findByRole('button', { name: /^100/ })
  expect(endpoints.submitQuiz).toHaveBeenCalledTimes(1)
})

test('opening an attempt cannot silently discard a draft that failed to save', async () => {
  endpoints.quizAttempts.mockResolvedValue([attempt])
  mount(); await choose()
  fireEvent.change(screen.getByRole('textbox', { name: '你的答案' }), { target: { value: '保留编辑' } })
  endpoints.saveQuizDraft.mockRejectedValue(new Error('写入失败'))
  fireEvent.click(within(history()).getByRole('button', { name: /^80/ }))
  await screen.findByText('草稿保存失败：写入失败。当前答案已保留，请重试保存后再切换。')
  expect(screen.getByRole('textbox', { name: '你的答案' })).toHaveValue('保留编辑')
  expect(screen.queryByText(/本次原始得分/)).not.toBeInTheDocument()
})

test('submit failure preserves answers and reuses its request ID on retry', async () => {
  endpoints.submitQuiz.mockRejectedValueOnce(new Error('提交离线'))
  mount(); await choose()
  fireEvent.change(screen.getByRole('textbox', { name: '你的答案' }), { target: { value: '答案' } })
  fireEvent.click(screen.getByRole('button', { name: '提交测验（已答 1 题）' }))
  await screen.findByText('提交离线')
  expect(screen.getByRole('textbox', { name: '你的答案' })).toHaveValue('答案')
  fireEvent.click(screen.getByRole('button', { name: '提交测验（已答 1 题）' }))
  await screen.findByText(/本次原始得分 100/)
  expect(endpoints.submitQuiz.mock.calls[0][2]).toBe(endpoints.submitQuiz.mock.calls[1][2])
  await waitFor(() => expect(screen.getByRole('textbox', { name: '你的答案' })).toBeDisabled())
})

test('successful empty reads show empty states and disable generation without libraries', async () => {
  endpoints.quizzes.mockResolvedValue([])
  endpoints.knowledgeBases.mockResolvedValue([])
  mount()
  await screen.findByText('还没有测验。')
  fireEvent.click(within(screen.getByRole('banner')).getByRole('button', { name: '创建测验' }))
  const dialog = screen.getByRole('dialog')
  await within(dialog).findByText('暂无可用于测验的资料库。')
  expect(within(dialog).getByRole('button', { name: '生成题目' })).toBeDisabled()
})

test('failed quiz generation retains the chosen library and topic', async () => {
  endpoints.generateQuiz.mockRejectedValue(new Error('模型不可用'))
  mount()
  fireEvent.click(within(screen.getByRole('banner')).getByRole('button', { name: '创建测验' }))
  const dialog = screen.getByRole('dialog')
  await within(dialog).findByRole('option', { name: '真实资料库' })
  fireEvent.change(within(dialog).getByLabelText('测验主题'), { target: { value: '不丢失的主题' } })
  fireEvent.submit(within(dialog).getByRole('button', { name: '生成题目' }).closest('form'))
  await within(dialog).findByText('模型不可用')
  expect(within(dialog).getByLabelText('测验主题')).toHaveValue('不丢失的主题')
  expect(within(dialog).getByLabelText('资料库')).toHaveValue('7')
})
