import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import ReviewPage from './ReviewPage'
import { endpoints } from '../api/client'

vi.mock('../api/client', () => ({ endpoints: { reviews: vi.fn(), plans: vi.fn(), createPlan: vi.fn(), reviewCard: vi.fn() } }))

const card = { id: 1, prompt: '真实复习问题', answer: '真实参考答案', due_at: '2000-01-01T00:00:00Z', review_count: 0 }
const plan = { id: 2, title: '已保存计划', goal: '学习目标' }
beforeEach(() => { vi.resetAllMocks(); endpoints.reviews.mockResolvedValue([card]); endpoints.plans.mockResolvedValue([plan]) })
function mount() { return render(<MemoryRouter><ReviewPage /></MemoryRouter>) }
function cards() { return screen.getByRole('region', { name: '复习卡片' }) }
function plans() { return screen.getByRole('region', { name: '我的计划' }) }
function draft() {
  fireEvent.click(screen.getByRole('button', { name: '制定计划' }))
  const dialog = screen.getByRole('dialog')
  fireEvent.change(within(dialog).getByLabelText('计划名称'), { target: { value: '新计划草稿' } })
  fireEvent.change(within(dialog).getByLabelText('学习目标'), { target: { value: '新目标草稿' } })
  return dialog
}
afterEach(() => vi.useRealTimers())

test('an upcoming card becomes reviewable at its due time without reloading or fetching again', async () => {
  vi.useFakeTimers()
  const start = new Date('2026-10-30T09:00:00.500Z')
  vi.setSystemTime(start)
  endpoints.reviews.mockResolvedValue([{ id: 1, prompt: '到期问题', answer: '答案', due_at: '2026-10-30T09:00:01Z', review_count: 0 }])
  endpoints.plans.mockResolvedValue([])
  await act(async () => { render(<MemoryRouter><ReviewPage /></MemoryRouter>) })
  expect(screen.getByRole('heading', { name: '今天的复习已就绪' })).toBeVisible()
  expect(screen.queryByRole('button', { name: '查看答案' })).not.toBeInTheDocument()
  await act(async () => { vi.advanceTimersByTime(1000) })
  expect(screen.getByRole('heading', { name: '到期问题' })).toBeVisible()
  expect(screen.getByRole('button', { name: '查看答案' })).toBeVisible()
  expect(endpoints.reviews).toHaveBeenCalledTimes(1)
})

test('initial failures show unknown metrics and independent retries, never a completed or empty schedule', async () => {
  endpoints.reviews.mockRejectedValueOnce(new Error('卡片离线'))
  endpoints.plans.mockRejectedValueOnce(new Error('计划离线'))
  mount()
  expect(screen.getAllByText('—')).toHaveLength(3)
  expect(screen.getByText('正在读取复习卡…')).toBeVisible()
  expect(screen.getByText('正在读取学习计划…')).toBeVisible()
  await within(cards()).findByText('复习卡加载失败：卡片离线')
  await within(plans()).findByText('学习计划加载失败：计划离线')
  for (const text of ['今天的复习已就绪', '暂无记录', '还没有计划。', '复习日历']) expect(screen.queryByText(text)).not.toBeInTheDocument()
  fireEvent.click(within(cards()).getByRole('button', { name: '重试 / Retry' }))
  await screen.findByRole('heading', { name: card.prompt })
  expect(endpoints.plans).toHaveBeenCalledOnce()
  fireEvent.click(within(plans()).getByRole('button', { name: '重试 / Retry' }))
  await within(plans()).findByText(plan.title)
})

test('plan retry does not change a flipped card or fetch cards again', async () => {
  endpoints.plans.mockRejectedValueOnce(new Error('计划离线'))
  mount()
  fireEvent.click(await screen.findByRole('button', { name: '查看答案' }))
  await within(plans()).findByText('学习计划加载失败：计划离线')
  fireEvent.click(within(plans()).getByRole('button', { name: '重试 / Retry' }))
  await within(plans()).findByText(plan.title)
  expect(screen.getByText(card.answer)).toBeVisible()
  expect(endpoints.reviews).toHaveBeenCalledOnce()
})

test('successful create keeps its receipt and cached records when refresh fails; each read can recover', async () => {
  mount()
  await screen.findByRole('heading', { name: card.prompt })
  const dialog = draft()
  endpoints.createPlan.mockResolvedValueOnce({ id: 3 })
  endpoints.reviews.mockRejectedValueOnce(new Error('卡片刷新离线'))
  endpoints.plans.mockRejectedValueOnce(new Error('计划刷新离线'))
  fireEvent.click(within(dialog).getByRole('button', { name: '创建计划' }))
  await screen.findByText('计划已创建，复习卡使用你填写的真实答案')
  await screen.findByText('已有复习卡可能不是最新状态。')
  await screen.findByText('已有计划可能不是最新状态。')
  expect(screen.getByRole('heading', { name: card.prompt })).toBeVisible()
  expect(within(plans()).getByText(plan.title)).toBeVisible()
  fireEvent.click(within(plans()).getByRole('button', { name: '重试 / Retry' }))
  await within(plans()).findByText(plan.title)
  expect(endpoints.reviews).toHaveBeenCalledTimes(2)
  expect(endpoints.createPlan).toHaveBeenCalledOnce()
  expect(screen.getByText('计划已创建，复习卡使用你填写的真实答案')).toBeVisible()
})

test('failed create retains draft and disabled inputs prevent edits and duplicate writes while retrying', async () => {
  mount()
  await screen.findByRole('heading', { name: card.prompt })
  const dialog = draft()
  endpoints.createPlan.mockRejectedValueOnce(new Error('创建失败'))
  const submit = within(dialog).getByRole('button', { name: '创建计划' })
  fireEvent.click(submit)
  await within(dialog).findByText('创建失败')
  expect(within(dialog).getByLabelText('计划名称')).toHaveValue('新计划草稿')
  expect(endpoints.reviews).toHaveBeenCalledOnce()
  let release
  endpoints.createPlan.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
  fireEvent.click(submit); fireEvent.click(submit)
  expect(submit).toBeDisabled()
  expect(within(dialog).getByLabelText('计划名称')).toBeDisabled()
  expect(endpoints.createPlan).toHaveBeenCalledTimes(2)
  await act(async () => release({ id: 3 }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('failed rating retains the flipped card and manual rating retry sends exactly one mutation', async () => {
  mount()
  fireEvent.click(await screen.findByRole('button', { name: '查看答案' }))
  endpoints.reviewCard.mockRejectedValueOnce(new Error('评分失败'))
  const button = screen.getByRole('button', { name: '基本掌握' })
  fireEvent.click(button)
  await screen.findByText('评分失败')
  expect(screen.getByText(card.answer)).toBeVisible()
  expect(screen.queryByRole('button', { name: '重试 / Retry' })).not.toBeInTheDocument()
  let release
  endpoints.reviewCard.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
  fireEvent.click(button); fireEvent.click(button)
  expect(button).toBeDisabled()
  expect(endpoints.reviewCard.mock.calls).toEqual([[1, 4], [1, 4]])
  await act(async () => release({ ...card, due_at: '2100-01-01T00:00:00Z', review_count: 1 }))
  await screen.findByText(/^评分已保存，下次复习：/)
  expect(screen.queryByText(card.answer)).not.toBeInTheDocument()
  expect(endpoints.reviews).toHaveBeenCalledOnce()
})

test('a late refresh cannot resurrect a card after a saved rating', async () => {
  mount()
  fireEvent.click(await screen.findByRole('button', { name: '查看答案' }))
  let release
  endpoints.reviews.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
  endpoints.createPlan.mockResolvedValueOnce({ id: 3 })
  const dialog = draft()
  fireEvent.click(within(dialog).getByRole('button', { name: '创建计划' }))
  await screen.findByText('计划已创建，复习卡使用你填写的真实答案')
  endpoints.reviewCard.mockResolvedValueOnce({ ...card, due_at: '2100-01-01T00:00:00Z', review_count: 1 })
  fireEvent.click(screen.getByRole('button', { name: '基本掌握' }))
  await screen.findByText(/^评分已保存，下次复习：/)
  await act(async () => release([card]))
  expect(screen.queryByRole('heading', { name: card.prompt })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '查看答案' })).not.toBeInTheDocument()
})

test('late initial replies after unmount cannot populate a new page', async () => {
  let releaseCards, releasePlans
  endpoints.reviews.mockReturnValueOnce(new Promise(resolve => { releaseCards = resolve }))
  endpoints.plans.mockReturnValueOnce(new Promise(resolve => { releasePlans = resolve }))
  const view = mount(); view.unmount()
  endpoints.reviews.mockResolvedValueOnce([]); endpoints.plans.mockResolvedValueOnce([])
  mount()
  await screen.findByText('今天的复习已就绪')
  await act(async () => { releaseCards([card]); releasePlans([plan]) })
  expect(screen.queryByRole('heading', { name: card.prompt })).not.toBeInTheDocument()
  expect(screen.queryByText(plan.title)).not.toBeInTheDocument()
})
